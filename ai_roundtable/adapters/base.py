"""Adapter 基类与数据类型。

一个 adapter 描述一个 AI CLI 的调用约定：命令怎么拼、prompt 怎么送（stdin 或 argv）、
stdout 每行怎么解析成流事件。子进程的运行与生命周期统一由 engine.run_cli 负责。
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

EnvOverrides = Dict[str, Optional[str]]

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# CLI 启动横幅等无信息量的 stderr 行，不作为进度展示
PROGRESS_NOISE = ("yolo mode", "tool calls will be automatically approved",
                  "dangerously skip", "all tool calls")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


@dataclass
class StreamEvent:
    """单行 stdout 解析结果。

    kind:
      delta     — 回答内容片段
      progress  — 工具调用等进度信息（仅展示）
      final     — 完成信号；text 非空时为权威全文，为空时用累积的 delta
      heartbeat — 无内容，仅重置 idle 计时
    """
    kind: str
    text: str = ""


@dataclass
class CallResult:
    ok: bool
    text: str = ""       # 成功时为回答全文
    error: str = ""      # 失败原因（人类可读）
    elapsed: float = 0.0

    @property
    def display_text(self) -> str:
        """用于展示与持久化的文本；错误也留痕。"""
        return self.text if self.ok else f"[无响应：{self.error}]"


class AgentAdapter:
    """基类。子类按 CLI 特性覆盖 build_command / parse_line。"""

    prompt_via_stdin: bool = True

    def __init__(self, name: str, cfg: Optional[Dict[str, Any]] = None):
        self.name = name
        self.cfg = cfg or {}
        self.cmd = self.cfg.get("cmd", name)
        self.extra_flags: List[str] = list(self.cfg.get("flags") or [])

    def build_command(self, prompt: str) -> List[str]:
        raise NotImplementedError

    def env_overrides(self) -> EnvOverrides:
        """子进程环境变量增删；值为 None 表示从环境中删除该变量（区别于置空）。"""
        return {}

    def parse_line(self, line: str) -> List[StreamEvent]:
        """默认：纯文本 CLI，每行即内容。"""
        text = strip_ansi(line)
        if text.strip():
            return [StreamEvent("delta", text)]
        return []

    def parse_progress(self, line: str) -> Optional[str]:
        """stderr 行 → 进度展示文本；返回 None 表示忽略。"""
        text = strip_ansi(line).strip()
        if not text:
            return None
        lowered = text.lower()
        if any(noise in lowered for noise in PROGRESS_NOISE):
            return None
        return text
