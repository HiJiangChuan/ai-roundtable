"""Kimi CLI 适配器。

调用：`kimi --print --input-format text --output-format stream-json`，prompt 走 stdin。
输出为消息级 JSON 行（非 token 级）：
    {"role":"assistant","content":[{"type":"think","think":"…"},{"type":"text","text":"…"}]}
think 块作为进度预览展示，text 块是回答内容；进程自然退出即完成。
注意：kimi 的 print 模式自身会自动批准工具调用（CLI 内建行为，无关我们的 flags）。
"""
import json
from typing import List, Optional

from .base import AgentAdapter, StreamEvent, strip_ansi

_STDERR_NOISE = ("to resume this session",)


class KimiAdapter(AgentAdapter):
    prompt_via_stdin = True

    def build_command(self, prompt: str) -> List[str]:
        return [self.cmd, "--print",
                "--input-format", "text",
                "--output-format", "stream-json",
                *self.extra_flags]

    def parse_line(self, line: str) -> List[StreamEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []

        if data.get("role") != "assistant":
            return [StreamEvent("heartbeat")]

        events: List[StreamEvent] = []
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    events.append(StreamEvent("delta", text))
            elif btype == "think":
                think = (block.get("think") or "").strip()
                if think:
                    events.append(StreamEvent("progress", f"🤔 {think[:80]}"))
            elif btype == "tool_call":
                name = (block.get("name") or block.get("tool") or "")[:40]
                events.append(StreamEvent("progress",
                                          f"⚙️ {name}…" if name else "⚙️ 工具调用…"))
        return events or [StreamEvent("heartbeat")]

    def parse_progress(self, line: str) -> Optional[str]:
        text = strip_ansi(line).strip()
        if text and any(n in text.lower() for n in _STDERR_NOISE):
            return None
        return super().parse_progress(line)
