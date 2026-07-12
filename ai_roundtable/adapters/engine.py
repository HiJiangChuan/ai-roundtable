"""子进程执行引擎。

完成策略：以各 CLI 自己的协议信号（claude 的 type:result、codex 的 turn.completed）
或自然退出（EOF）判定完成——永不因"慢"而杀。

超时两层：
  idle_notify      — 无任何输出达到该秒数时回调 on_idle（仅通知，不杀）
  safety_timeout   — 绝对兜底墙钟；超过才强杀

生命周期保证：无论正常结束、取消（关 tab / 退出）还是异常，finally 都会杀掉子进程；
存活进程登记在 ProcessRegistry，app 退出时统一清理，不留孤儿进程烧 token。
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Set

from .base import AgentAdapter, CallResult, strip_ansi

# stdout 单行上限。claude 的 result 事件把全文放在一行 JSON 里（非 ASCII 会转义成
# \uXXXX，中文回答体积 ×6），默认 64KB 的 StreamReader limit 会直接炸，必须调大。
STREAM_LIMIT = 8 * 1024 * 1024

LOG_ROTATE_BYTES = 1024 * 1024


class ProcessRegistry:
    """跟踪存活子进程，供 app 退出时统一击杀。"""

    def __init__(self) -> None:
        self._procs: Set[asyncio.subprocess.Process] = set()

    def add(self, proc: asyncio.subprocess.Process) -> None:
        self._procs.add(proc)

    def discard(self, proc: asyncio.subprocess.Process) -> None:
        self._procs.discard(proc)

    def kill_all(self) -> None:
        for proc in list(self._procs):
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
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
            limit=STREAM_LIMIT,
        )
    except FileNotFoundError:
        logger.log(adapter.name, "NOTFOUND", 0)
        return CallResult(ok=False, error=f"命令未找到 '{adapter.cmd}'")
    except OSError as exc:
        logger.log(adapter.name, "SPAWN", 0, str(exc))
        return CallResult(ok=False, error=str(exc)[:120])

    if registry:
        registry.add(proc)

    accumulated: list = []      # delta 累积
    final_text: str = ""        # 协议 final 信号携带的权威全文
    stderr_tail: list = []      # 最近 stderr 行（错误报告用）
    last_activity = time.monotonic()
    was_killed = False

    def touch() -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

    async def read_stdout() -> None:
        nonlocal final_text
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

    async def read_stderr() -> None:
        async for raw in proc.stderr:
            touch()
            text = raw.decode("utf-8", errors="replace")
            stderr_tail.append(strip_ansi(text).strip())
            del stderr_tail[:-20]
            shown = adapter.parse_progress(text)
            if shown and on_progress:
                on_progress(shown)

    async def monitor() -> None:
        nonlocal was_killed
        idle_notified = False
        last_seen = last_activity
        while True:
            await asyncio.sleep(2)
            now = time.monotonic()
            if now - t0 >= safety_timeout:
                was_killed = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return
            if last_activity != last_seen:      # 有新输出：重置提醒
                last_seen = last_activity
                idle_notified = False
            idle = now - last_activity
            if idle >= idle_notify and not idle_notified:
                idle_notified = True
                if on_idle:
                    on_idle(idle)

    monitor_task = asyncio.create_task(monitor())
    try:
        io_tasks = [read_stdout(), read_stderr()]
        if adapter.prompt_via_stdin:
            io_tasks.append(_feed_stdin(proc, prompt.encode("utf-8")))
        await asyncio.gather(*io_tasks)
        await proc.wait()
    except asyncio.CancelledError:
        logger.log(adapter.name, "CANCEL", time.monotonic() - t0)
        raise
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except asyncio.CancelledError:
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
        detail = stderr_text or f"退出码 {proc.returncode}"
        logger.log(adapter.name, "ERROR", elapsed, detail)
        return CallResult(ok=False, error=detail[:200], elapsed=elapsed)

    if not output:
        logger.log(adapter.name, "EMPTY", elapsed, stderr_text)
        return CallResult(ok=False, error="输出为空" + (f"（{stderr_text[:120]}）" if stderr_text else ""),
                          elapsed=elapsed)

    logger.log(adapter.name, "OK", elapsed, f"{len(output)} chars")
    return CallResult(ok=True, text=output, elapsed=elapsed)
