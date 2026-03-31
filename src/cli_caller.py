"""
CLI Caller - Executes CLI commands for each AI agent with timeout and ANSI stripping.
"""
import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


class CliCaller:
    def __init__(self, config: Dict[str, Any], timeout: int = None):
        self.config = config
        self.default_timeout = timeout or (
            config.get('cli', {}).get('timeout')
            or config.get('deep', {}).get('timeout_seconds', 30)
        )
        self.ais = config.get('ais', {})

        # Log file for debugging CLI calls
        log_dir = Path.home() / '.ai-roundtable'
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / 'cli.log'

    def _agent_timeout(self, agent: str) -> int:
        """Per-agent timeout, falls back to default."""
        return self.ais.get(agent, {}).get('timeout', self.default_timeout)

    def _build_command(self, agent: str, prompt: str):
        agent_cfg = self.ais.get(agent, {})
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

    async def call(self, agent: str, prompt: str) -> str:
        if agent not in self.ais:
            return f"[无响应：未知 agent '{agent}']"

        cmd     = self._build_command(agent, prompt)
        timeout = self._agent_timeout(agent)
        t0      = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # Capture whatever stderr has before killing
                stderr_data = b''
                try:
                    proc.kill()
                    _, stderr_data = await asyncio.wait_for(
                        proc.communicate(), timeout=5
                    )
                except Exception:
                    pass

                elapsed   = time.monotonic() - t0
                err_hint  = strip_ansi(stderr_data.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'TIMEOUT', elapsed, err_hint)

                if err_hint:
                    return f"[无响应：超时 {timeout}s — {err_hint[:120]}]"
                return f"[无响应：超时 {timeout}s]"

            elapsed = time.monotonic() - t0

            if proc.returncode != 0:
                err_msg = strip_ansi(stderr.decode('utf-8', errors='replace')).strip()
                self._log(agent, 'ERROR', elapsed, err_msg)
                return f"[无响应：{err_msg[:120]}]" if err_msg else f"[无响应：退出码 {proc.returncode}]"

            output = strip_ansi(stdout.decode('utf-8', errors='replace')).strip()
            if not output:
                err_msg = strip_ansi(stderr.decode('utf-8', errors='replace')).strip()
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
