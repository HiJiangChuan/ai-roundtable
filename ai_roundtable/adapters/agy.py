"""Antigravity CLI (agy) 适配器。

调用：`agy --print <prompt>`（print 模式，prompt 走 argv——stdin 支持未验证）。
输出为纯文本逐行流式；进程自然退出即完成。
--print-timeout 默认仅 5 分钟，显式调大对齐引擎的 900s 兜底。
"""
from typing import List

from .base import AgentAdapter


class AgyAdapter(AgentAdapter):
    prompt_via_stdin = False

    def build_command(self, prompt: str) -> List[str]:
        return [self.cmd, "--print", prompt,
                "--print-timeout=15m",
                *self.extra_flags]
    # parse_line 继承基类：纯文本行即 delta
