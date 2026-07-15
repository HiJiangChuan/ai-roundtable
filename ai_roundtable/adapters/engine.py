"""子进程执行引擎。

完成策略：以各 CLI 自己的协议信号（claude 的 type:result、codex 的 turn.completed）
或自然退出（EOF）判定完成——永不因"慢"而杀。

超时两层：
  idle_notify      — 无任何输出达到该秒数时回调 on_idle（仅通知，不杀）
  safety_timeout   — 绝对兜底墙钟，用 asyncio.wait_for 包住整个 IO 泵：
                     即使孙进程握着 stdout 管道让 EOF 永远不来，也保证按时返回

进程隔离（参考 ai-cli-commander/spawn.py）：
- start_new_session=True：独立进程组，防止 SIGHUP 传播，且 pgid == pid
- 击杀用 os.killpg 覆盖整棵进程树——CLI 派生的孙进程若成为孤儿，会继续
  烧 token、占用 daemon 连接槽，是"越用越超时"的根源
- 终端环境变量按缺省注入（setdefault，不覆盖真实终端环境）
- adapter 可通过 env_overrides() 增删环境变量（如删除 CLAUDECODE 防嵌套）

生命周期保证：无论正常结束、取消（关 tab / 退出）还是异常，finally 都会杀掉
整个进程组；存活进程登记在 ProcessRegistry，app 退出时统一清理。
"""
import asyncio
import errno
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Set

from .base import AgentAdapter, CallResult, strip_ansi

# stdout 单行上限。claude 的 result 事件把全文放在一行 JSON 里（非 ASCII 会转义成
# \uXXXX，中文回答体积 ×6），默认 64KB 的 StreamReader limit 会直接炸，必须调大。
STREAM_LIMIT = 8 * 1024 * 1024

LOG_ROTATE_BYTES = 1024 * 1024

# 缺省注入的终端环境（setdefault：真实终端环境优先）。
# 部分 CLI 检测不到这些变量时会认为自己不在终端中而挂起或改变输出行为。
_TERMINAL_ENV = {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
    "LANG": "en_US.UTF-8",
}


def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """杀死子进程及其整个进程组。

    start_new_session=True 保证 pgid == pid，killpg 能覆盖 CLI 派生的孙进程；
    即使直接子进程已退出，只要组内还有存活成员，pgid 依然有效。
    进程组不存在时回退为只杀直接子进程。
    """
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _build_env(adapter: AgentAdapter) -> dict:
    env = os.environ.copy()
    for key, value in _TERMINAL_ENV.items():
        env.setdefault(key, value)
    for key, value in adapter.env_overrides().items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


class ProcessRegistry:
    """跟踪存活子进程，供 app 退出时统一击杀。"""

    def __init__(self) -> None:
        self._procs: Set[asyncio.subprocess.Process] = set()

    def add(self, proc: asyncio.subprocess.Process) -> None:
        self._procs.add(proc)

    def discard(self, proc: asyncio.subprocess.Process) -> None:
        self._procs.discard(proc)

    def kill_all(self) -> None:
        # 登记在册的都是进行中的调用：无条件按进程组击杀，不留孤儿
        for proc in list(self._procs):
            kill_process_tree(proc)
        self._procs.clear()


class CliLogger:
    """一行一条的调用日志，超过 1MB 轮转到 .1。"""

    def __init__(self, path: Optional[Path]):
        self.path = path

    def log(self, agent: str, status: str, elapsed: float, detail: str = "") -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > LOG_ROTATE_BYTES:
                self.path.replace(self.path.with_suffix(".log.1"))
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {agent:6s} {status:8s} {elapsed:6.1f}s"
            if detail:
                line += f"  {detail[:200]}"
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


async def _feed_stdin(proc: asyncio.subprocess.Process, payload: bytes) -> None:
    """并发写 stdin（与读 stdout 同时进行，避免管道互堵死锁）。"""
    try:
        proc.stdin.write(payload)
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # 子进程提前退出：让 stdout/rc 路径去报告
    finally:
        try:
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass


async def _drain(stream: asyncio.StreamReader) -> None:
    """按块排空剩余输出并丢弃：单行超限后子进程可能还在写，不排空会堵死管道。"""
    try:
        while await stream.read(65536):
            pass
    except Exception:
        pass


async def run_cli(
    adapter: AgentAdapter,
    prompt: str,
    *,
    on_delta: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    on_idle: Optional[Callable[[float], None]] = None,
    idle_notify: float = 25.0,
    safety_timeout: float = 900.0,
    registry: Optional[ProcessRegistry] = None,
    logger: Optional[CliLogger] = None,
) -> CallResult:
    logger = logger or CliLogger(None)
    t0 = time.monotonic()

    cmd = adapter.build_command(prompt)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if adapter.prompt_via_stdin
                  else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_env(adapter),
            limit=STREAM_LIMIT,
            start_new_session=True,  # 独立进程组：防 SIGHUP，且可整组击杀
        )
    except FileNotFoundError:
        logger.log(adapter.name, "NOTFOUND", 0)
        return CallResult(ok=False, error=f"命令未找到 '{adapter.cmd}'")
    except OSError as exc:
        logger.log(adapter.name, "SPAWN", 0, str(exc))
        if exc.errno == errno.E2BIG:
            return CallResult(ok=False,
                              error="prompt 过长，超出系统 argv 上限；请缩短问题或减少上下文")
        return CallResult(ok=False, error=str(exc)[:120])

    if registry:
        registry.add(proc)

    accumulated: list = []      # delta 累积
    final_text: str = ""        # 协议 final 信号携带的权威全文
    stderr_tail: list = []      # 最近 stderr 行（错误报告用）
    stream_note: str = ""       # 读流异常说明（如单行超限）
    last_activity = time.monotonic()

    def touch() -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

    async def read_stdout() -> None:
        nonlocal final_text, stream_note
        try:
            async for raw in proc.stdout:
                touch()
                # 保留换行原样交给 adapter：纯文本 CLI 靠它分行，JSON 解析器自会 strip
                line = raw.decode("utf-8", errors="replace")
                for ev in adapter.parse_line(line):
                    if ev.kind == "delta" and ev.text:
                        accumulated.append(ev.text)
                        if on_delta:
                            on_delta(ev.text)
                    elif ev.kind == "progress" and ev.text:
                        if on_progress:
                            on_progress(ev.text)
                    elif ev.kind == "final":
                        final_text = ev.text or final_text
        except (ValueError, asyncio.LimitOverrunError):
            # 单行超过 STREAM_LIMIT：不能让异常炸穿引擎，排空后按已有内容收尾
            stream_note = f"stdout 单行超过 {STREAM_LIMIT // (1024 * 1024)}MB 缓冲上限"
            await _drain(proc.stdout)

    async def read_stderr() -> None:
        try:
            async for raw in proc.stderr:
                touch()
                text = raw.decode("utf-8", errors="replace")
                stderr_tail.append(strip_ansi(text).strip())
                del stderr_tail[:-20]
                shown = adapter.parse_progress(text)
                if shown and on_progress:
                    on_progress(shown)
        except (ValueError, asyncio.LimitOverrunError):
            await _drain(proc.stderr)

    async def pump() -> None:
        io_tasks = [read_stdout(), read_stderr()]
        if adapter.prompt_via_stdin:
            io_tasks.append(_feed_stdin(proc, prompt.encode("utf-8")))
        await asyncio.gather(*io_tasks)
        await proc.wait()

    async def idle_monitor() -> None:
        idle_notified = False
        last_seen = last_activity
        while True:
            await asyncio.sleep(2)
            if last_activity != last_seen:      # 有新输出：重置提醒
                last_seen = last_activity
                idle_notified = False
            idle = time.monotonic() - last_activity
            if idle >= idle_notify and not idle_notified:
                idle_notified = True
                if on_idle:
                    on_idle(idle)

    monitor_task = asyncio.create_task(idle_monitor())
    was_killed = False
    clean = False
    try:
        # 兜底墙钟包住整个 IO 泵：不依赖 EOF 到达（孙进程可能一直握着管道）
        await asyncio.wait_for(pump(), timeout=safety_timeout)
        clean = True
    except asyncio.TimeoutError:
        was_killed = True
    except asyncio.CancelledError:
        logger.log(adapter.name, "CANCEL", time.monotonic() - t0)
        raise
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        # 超时/取消/异常：无条件整组击杀（直接子进程可能已死，孙进程还在）
        if not clean:
            kill_process_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        if registry:
            registry.discard(proc)

    elapsed = time.monotonic() - t0
    stderr_text = " / ".join(t for t in stderr_tail if t)[-300:]

    if was_killed:
        logger.log(adapter.name, "TIMEOUT", elapsed, stderr_text)
        return CallResult(ok=False, error=f"超时 {int(safety_timeout)}s",
                          elapsed=elapsed)

    output = (final_text or "".join(accumulated)).strip()

    if proc.returncode != 0 and not output:
        detail = stderr_text or stream_note or f"退出码 {proc.returncode}"
        logger.log(adapter.name, "ERROR", elapsed, detail)
        return CallResult(ok=False, error=detail[:200], elapsed=elapsed)

    if not output:
        detail = stream_note or stderr_text
        logger.log(adapter.name, "EMPTY", elapsed, detail)
        return CallResult(ok=False, error="输出为空" + (f"（{detail[:120]}）" if detail else ""),
                          elapsed=elapsed)

    logger.log(adapter.name, "OK", elapsed,
               f"{len(output)} chars" + (f"（{stream_note}）" if stream_note else ""))
    return CallResult(ok=True, text=output, elapsed=elapsed)
