"""
CLI Caller - Executes CLI commands for each AI agent.

Completion strategy (per AI):
  Claude  — waits for `type: result` JSON event (explicit done signal), then EOF
  Gemini  — plain-text output, each stdout line is a content chunk; EOF = done
            (stream-json was tested but buffers the full response — no real streaming)
  Codex   — waits for `turn.completed` JSON event, then EOF

Timeout strategy (two layers):
  idle_timeout   — reset on any stdout/stderr output;
                   fires on_idle(elapsed) when no output for this long (UI notification only)
  safety_timeout — absolute 900s wall-clock limit; kills the process as last resort only
"""
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Any, Optional

# Extra flags appended only for streaming calls.
# Gemini is intentionally absent: stream-json buffers the full response before emitting,
# so plain-text stdout gives true line-by-line streaming with far better UX.
STREAM_FLAGS: Dict[str, list] = {
    'claude': ['--output-format', 'stream-json', '--verbose', '--include-partial-messages'],
    'codex':  ['--json'],
}

# Agents whose stdout is JSONL. Gemini uses plain-text streaming (each line = chunk).
STREAM_JSON_AGENTS = {'claude', 'codex'}

# Absolute safety timeout (seconds). Kills any process that hasn't exited by then.
SAFETY_TIMEOUT = 900  # 15 minutes

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


class CliCaller:
    def __init__(self, config: Dict[str, Any], timeout: int = None):
        self.config = config
        self.default_timeout = timeout or config.get('deep', {}).get('timeout_seconds', 30)
        self.ais = config.get('ais', {})

        log_dir = Path.home() / '.ai-roundtable'
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / 'cli.log'

    def _idle_timeout(self, agent: str) -> float:
        """Idle timeout: no stdout/stderr for this long → fire on_idle (no kill)."""
        cfg_timeout = self.ais.get(agent, {}).get('timeout', 300)
        return min(60.0, cfg_timeout / 4)

    def _build_command(self, agent: str, prompt: str):
        agent_cfg  = self.ais.get(agent, {})
        cmd        = agent_cfg.get('cmd', agent)
        flags      = agent_cfg.get('flags', [])
        subcommand = agent_cfg.get('subcommand')
        if subcommand:
            return [cmd, subcommand, prompt] + flags
        return [cmd, agent_cfg.get('prompt_flag', '-p'), prompt] + flags

    def _log(self, agent: str, status: str, elapsed: float, detail: str = '') -> None:
        ts = datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {agent:6s} {status:8s} {elapsed:5.1f}s"
        if detail:
            line += f"  {detail[:120]}"
        try:
            with open(self._log_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    async def _run_process(
        self,
        agent: str,
        cmd: list,
        on_stdout_line: Callable[[bytes], None],
        on_idle: Optional[Callable[[float], None]] = None,
        on_stderr_line: Optional[Callable[[str], None]] = None,
    ) -> tuple:
        """
        Run subprocess until natural exit (EOF on stdout/stderr).

        Completion is driven by the AI's own protocol:
          - Claude: emits `type: result` then exits
          - Gemini: emits `type: result` then exits (stream-json mode)
          - Codex:  emits `turn.completed` then exits

        Resets idle timer on any stdout or stderr output.
        Fires on_idle when no output for idle_timeout seconds (notification only, no kill).
        Kills unconditionally only if SAFETY_TIMEOUT (900s) is reached.

        Returns (returncode, stderr_bytes, was_killed).
        """
        idle_timeout = self._idle_timeout(agent)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        last_activity = time.monotonic()
        start_time    = time.monotonic()
        stderr_chunks: list = []
        idle_notified = False
        was_killed    = False
        finished      = asyncio.Event()

        async def read_stdout():
            nonlocal last_activity, idle_notified
            async for line in proc.stdout:
                last_activity = time.monotonic()
                idle_notified = False
                on_stdout_line(line)

        async def read_stderr():
            nonlocal last_activity, idle_notified
            async for line in proc.stderr:
                last_activity = time.monotonic()
                idle_notified = False
                stderr_chunks.append(line)
                if on_stderr_line:
                    text = strip_ansi(line.decode('utf-8', errors='replace')).strip()
                    if text:
                        on_stderr_line(text)

        async def monitor():
            nonlocal idle_notified, was_killed
            while not finished.is_set():
                await asyncio.sleep(2)
                now     = time.monotonic()
                elapsed = now - start_time
                idle    = now - last_activity

                # Absolute safety timeout — last resort only
                if elapsed >= SAFETY_TIMEOUT:
                    was_killed = True
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    return

                # Idle notification (no kill)
                if idle >= idle_timeout and not idle_notified:
                    idle_notified = True
                    if on_idle:
                        on_idle(idle)

        stdout_task  = asyncio.create_task(read_stdout())
        stderr_task  = asyncio.create_task(read_stderr())
        monitor_task = asyncio.create_task(monitor())

        await asyncio.gather(stdout_task, stderr_task)
        await proc.wait()
        finished.set()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        return proc.returncode, b''.join(stderr_chunks), was_killed

    async def call(self, agent: str, prompt: str,
                   on_idle: Optional[Callable[[float], None]] = None) -> str:
        if agent not in self.ais:
            return f"[无响应：未知 agent '{agent}']"

        cmd = self._build_command(agent, prompt)
        t0  = time.monotonic()
        stdout_lines: list = []

        try:
            returncode, stderr_bytes, was_killed = await self._run_process(
                agent, cmd,
                on_stdout_line=stdout_lines.append,
                on_idle=on_idle,
            )
            elapsed = time.monotonic() - t0

            if was_killed:
                err_hint = strip_ansi(stderr_bytes.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'TIMEOUT', elapsed, err_hint)
                return f"[无响应：超时 {SAFETY_TIMEOUT}s]"

            if returncode != 0:
                err_msg = strip_ansi(stderr_bytes.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'ERROR', elapsed, err_msg)
                return f"[无响应：{err_msg[:120]}]" if err_msg else f"[无响应：退出码 {returncode}]"

            output = strip_ansi(b''.join(stdout_lines).decode('utf-8', errors='replace')).strip()
            if not output:
                err_msg = strip_ansi(stderr_bytes.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'EMPTY', elapsed, err_msg)
                return "[无响应：输出为空]"

            self._log(agent, 'OK', elapsed, f"{len(output)} chars")
            return output

        except FileNotFoundError:
            self._log(agent, 'NOTFOUND', 0)
            return f"[无响应：命令未找到 '{self.ais[agent].get('cmd', agent)}']"
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._log(agent, 'EXCEPT', elapsed, str(e))
            return f"[无响应：{str(e)[:100]}]"

    async def call_stream(self, agent: str, prompt: str,
                          on_chunk: Callable[[str], None],
                          on_idle: Optional[Callable[[float], None]] = None,
                          on_stderr: Optional[Callable[[str], None]] = None) -> str:
        if agent not in self.ais:
            return f"[无响应：未知 agent '{agent}']"

        cmd = self._build_command(agent, prompt) + STREAM_FLAGS.get(agent, [])
        t0  = time.monotonic()

        full_text  = ""
        final_text = ""

        if agent in STREAM_JSON_AGENTS:
            # JSONL streaming: parse each line as a structured event
            def on_stdout_line(raw: bytes):
                nonlocal full_text, final_text
                line = raw.decode('utf-8', errors='replace').strip()
                if not line:
                    return
                chunk, is_final = self._parse_stream_line(agent, line)
                if is_final:
                    final_text = chunk
                elif chunk and chunk != '\x00':
                    full_text += chunk
                    on_chunk(chunk)
        else:
            # Plain-text streaming (Gemini): each stdout line is content
            def on_stdout_line(raw: bytes):
                nonlocal full_text
                line = strip_ansi(raw.decode('utf-8', errors='replace'))
                if line.strip():
                    full_text += line
                    on_chunk(line)

        try:
            returncode, stderr_bytes, was_killed = await self._run_process(
                agent, cmd,
                on_stdout_line=on_stdout_line,
                on_idle=on_idle,
                on_stderr_line=on_stderr,
            )
            elapsed = time.monotonic() - t0

            if was_killed:
                self._log(agent, 'TIMEOUT', elapsed)
                return f"[无响应：超时 {SAFETY_TIMEOUT}s]"

            result = (final_text or full_text).strip()
            if not result:
                err = strip_ansi(stderr_bytes.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'EMPTY', elapsed, err)
                return "[无响应：输出为空]"

            self._log(agent, 'OK', elapsed, f"{len(result)} chars (stream)")
            return result

        except FileNotFoundError:
            self._log(agent, 'NOTFOUND', 0)
            return f"[无响应：命令未找到 '{self.ais[agent].get('cmd', agent)}']"
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._log(agent, 'EXCEPT', elapsed, str(e))
            return f"[无响应：{str(e)[:100]}]"

    def _parse_stream_line(self, agent: str, line: str):
        """Parse one JSONL line. Returns (text, is_final).
        Only called for STREAM_JSON_AGENTS (claude, codex). Gemini uses plain-text.

        Claude:
          stream_event + text_delta → content chunk
          type:result               → final (contains full text)

        Codex (exec --json):
          item.completed agent_message → content chunk
          turn.completed               → done signal (no text, use accumulated chunks)
          turn.failed                  → done signal (error)
        """
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return "", False

        if agent == 'claude':
            t = data.get('type', '')
            if t == 'system':
                # Earliest stdout signal — heartbeat to reset idle timer
                return '\x00', False
            elif t == 'stream_event':
                ev = data.get('event', {})
                if ev.get('type') == 'content_block_delta':
                    delta = ev.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        return delta.get('text', ''), False
            elif t == 'result':
                return data.get('result', ''), True

        elif agent == 'codex':
            t = data.get('type', '')
            if t == 'item.completed':
                item = data.get('item', {})
                if item.get('type') == 'agent_message':
                    return item.get('text', ''), False  # content chunk
            elif t == 'turn.completed':
                # Turn done; text already collected via item.completed events
                return '', True
            elif t == 'turn.failed':
                return '', True
            elif t == 'system':
                return '\x00', False  # heartbeat

        return "", False
