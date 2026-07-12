"""Codex CLI 适配器。

调用：`codex exec --json -`，prompt 走 stdin（`-` 显式声明）。
`exec --json` 在 item.completed 时给出整段文本（无 token 级流式）；
turn.completed / turn.failed 是完成信号。
"""
import json
from typing import List

from .base import AgentAdapter, StreamEvent


class CodexAdapter(AgentAdapter):
    prompt_via_stdin = True

    def build_command(self, prompt: str) -> List[str]:
        return [self.cmd, "exec", "--json", *self.extra_flags, "-"]

    def parse_line(self, line: str) -> List[StreamEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []

        t = data.get("type", "")
        if t == "item.started":
            item = data.get("item", {})
            item_type = item.get("type", "")
            if item_type == "command_execution":
                cmd = (item.get("command") or "")[:60]
                return [StreamEvent("progress", f"⚙️ {cmd}…" if cmd else "⚙️ 执行中…")]
            if item_type == "web_search":
                query = (item.get("query") or "")[:60]
                return [StreamEvent("progress", f"🔍 {query}…" if query else "🔍 搜索中…")]
            return [StreamEvent("heartbeat")]
        if t == "item.completed":
            item = data.get("item", {})
            if item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    return [StreamEvent("delta", text)]
            return [StreamEvent("heartbeat")]
        if t == "turn.completed":
            return [StreamEvent("final")]
        if t == "turn.failed":
            err = (data.get("error") or {}).get("message", "")
            events = [StreamEvent("final")]
            if err:
                events.insert(0, StreamEvent("progress", f"✗ {err[:120]}"))
            return events
        return [StreamEvent("heartbeat")]
