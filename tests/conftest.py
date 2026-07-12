"""共享 fixtures：临时路径、测试配置、FakePool。"""
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from ai_roundtable.adapters import CallResult
from ai_roundtable.config import AppPaths


@pytest.fixture
def paths(tmp_path) -> AppPaths:
    return AppPaths(
        config_dir=tmp_path / "config",
        prompts_dir=tmp_path / "config" / "prompts",
        sessions_dir=tmp_path / "data" / "sessions",
        state_dir=tmp_path / "state",
    )


@pytest.fixture
def config(tmp_path) -> dict:
    return {
        "ais": {
            "alpha": {"cmd": "alpha-cli", "icon": "🅰️", "color": "blue",
                      "callout": "note", "enabled": True},
            "beta": {"cmd": "beta-cli", "icon": "🅱️", "color": "green",
                     "callout": "tip", "enabled": True},
            "gamma": {"cmd": "gamma-cli", "icon": "🌀", "color": "yellow",
                      "callout": "warning", "enabled": True},
        },
        "quick": {"context_entries": 5, "answer_snippet": 200},
        "deep": {"full_rounds_kept": 3, "compress_summary_max": 80},
        "limits": {"idle_notify_seconds": 25, "safety_timeout_seconds": 900},
        "history": {"obsidian_vault": str(tmp_path / "vault")},
    }


MODERATOR_OK = """【矛盾点】
效率与安全之争

【下一问】
应该优先保证哪一个？

【行动分配】
Alpha：反驳 - 反驳效率优先论
Beta：补充 - 补充安全案例
Gamma：挑战前提 - 质疑二元对立

【本轮摘要】
各方就效率与安全的优先级产生分歧。"""


class FakePool:
    """脚本化的 AgentPool 替身。

    scripts[agent] 可以是：
      str            — 每次调用都返回该文本
      list[str]      — 依次弹出；None 项表示这次调用失败
      callable(p)->s — 按 prompt 动态生成
    """

    def __init__(self, scripts: Optional[Dict] = None,
                 default: str = "answer",
                 agents: Optional[List[str]] = None):
        self.scripts = scripts or {}
        self.default = default
        self.calls: List[tuple] = []          # (agent, prompt)
        self.adapters = {name: object()
                         for name in (agents or list(self.scripts))}

    def _next_text(self, agent: str, prompt: str):
        script = self.scripts.get(agent, self.default)
        if callable(script):
            return script(prompt)
        if isinstance(script, list):
            return script.pop(0) if script else self.default
        return script

    async def call(self, agent, prompt, *, on_delta=None,
                   on_progress=None, on_idle=None) -> CallResult:
        self.calls.append((agent, prompt))
        text = self._next_text(agent, prompt)
        if text is None:
            return CallResult(ok=False, error="fake failure")
        if isinstance(text, Exception):
            raise text
        if on_delta and text:
            mid = max(1, len(text) // 2)
            on_delta(text[:mid])
            on_delta(text[mid:])
        return CallResult(ok=True, text=text)

    def kill_all(self) -> None:
        pass


@pytest.fixture
def collect():
    """emit 收集器：events 列表 + emit 函数。"""
    events: list = []
    return events, events.append
