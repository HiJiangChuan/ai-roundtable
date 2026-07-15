"""Claude Code CLI 适配器。

调用：prompt 走 stdin（避开 ARG_MAX、不暴露在进程列表），
     `--output-format stream-json` 获得 token 级流式输出。
完成信号：type:result 事件（携带权威全文），随后自然退出。
"""
import json
from typing import List

from .base import AgentAdapter, EnvOverrides, StreamEvent


class ClaudeAdapter(AgentAdapter):
    prompt_via_stdin = True

    def build_command(self, prompt: str) -> List[str]:
        return [self.cmd, "-p",
                "--output-format", "stream-json",
                "--verbose", "--include-partial-messages",
                *self.extra_flags]

    def env_overrides(self) -> EnvOverrides:
        # 删除（而非置空）CLAUDECODE：在 Claude Code 终端里运行本 TUI 时，
        # 子 claude 会因该变量认为自己被嵌套而改变行为
        return {"CLAUDECODE": None}

    def parse_line(self, line: str) -> List[StreamEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []

        t = data.get("type", "")
        if t == "system":
            # 最早出现的 stdout 信号，用于重置 idle 计时
            return [StreamEvent("heartbeat")]
        if t == "stream_event":
            ev = data.get("event", {})
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        return [StreamEvent("delta", text)]
            return [StreamEvent("heartbeat")]
        if t == "result":
            return [StreamEvent("final", data.get("result", "") or "")]
        return [StreamEvent("heartbeat")]
