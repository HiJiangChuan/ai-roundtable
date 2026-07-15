"""Adapter 注册表与 AgentPool。

AgentPool 是 session 层调用 AI 的唯一入口：
    result = await pool.call("claude", prompt, on_delta=..., on_progress=..., on_idle=...)
已知 CLI（claude/codex/agy）用专用 adapter，未知名字回退配置驱动的 GenericAdapter。

并发限流：同一 agent 的并发调用经过 per-agent Semaphore（多 tab、后台标题任务
可能同时打同一个 CLI；agy 这类 daemon 型 CLI 连接数有限，超发会排队直至超时）。
上限取 ais.<name>.max_concurrent，缺省用 limits.max_concurrent_per_agent（默认 2）。
"""
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .base import AgentAdapter, CallResult, StreamEvent, strip_ansi
from .engine import CliLogger, ProcessRegistry, run_cli
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .agy import AgyAdapter
from .kimi import KimiAdapter
from .generic import GenericAdapter

__all__ = ["AgentAdapter", "AgentPool", "CallResult", "StreamEvent",
           "ProcessRegistry", "CliLogger", "make_adapter", "strip_ansi"]

ADAPTER_CLASSES = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "agy": AgyAdapter,
    "kimi": KimiAdapter,
}


def make_adapter(name: str, cfg: Optional[Dict[str, Any]] = None) -> AgentAdapter:
    cls = ADAPTER_CLASSES.get(name, GenericAdapter)
    return cls(name, cfg)


class AgentPool:
    def __init__(self, config: Dict[str, Any],
                 registry: Optional[ProcessRegistry] = None,
                 log_path: Optional[Path] = None):
        self.adapters: Dict[str, AgentAdapter] = {
            name: make_adapter(name, cfg)
            for name, cfg in (config.get("ais") or {}).items()
        }
        limits = config.get("limits") or {}
        self.idle_notify = float(limits.get("idle_notify_seconds", 25))
        self.safety_timeout = float(limits.get("safety_timeout_seconds", 900))
        self.max_concurrent = int(limits.get("max_concurrent_per_agent", 2))
        self.registry = registry or ProcessRegistry()
        self.logger = CliLogger(log_path)
        self._sems: Dict[str, asyncio.Semaphore] = {}

    def _sem(self, agent: str) -> asyncio.Semaphore:
        sem = self._sems.get(agent)
        if sem is None:
            adapter = self.adapters.get(agent)
            limit = int((adapter.cfg or {}).get("max_concurrent",
                                                self.max_concurrent)) \
                if adapter else self.max_concurrent
            sem = self._sems[agent] = asyncio.Semaphore(max(1, limit))
        return sem

    async def call(self, agent: str, prompt: str, *,
                   on_delta: Optional[Callable[[str], None]] = None,
                   on_progress: Optional[Callable[[str], None]] = None,
                   on_idle: Optional[Callable[[float], None]] = None,
                   safety_timeout: Optional[float] = None) -> CallResult:
        adapter = self.adapters.get(agent)
        if adapter is None:
            return CallResult(ok=False, error=f"未知 agent '{agent}'")
        async with self._sem(agent):
            return await run_cli(
                adapter, prompt,
                on_delta=on_delta, on_progress=on_progress, on_idle=on_idle,
                idle_notify=self.idle_notify,
                safety_timeout=safety_timeout or self.safety_timeout,
                registry=self.registry,
                logger=self.logger,
            )

    def kill_all(self) -> None:
        self.registry.kill_all()
