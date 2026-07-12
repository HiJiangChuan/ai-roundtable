"""通用适配器：配置驱动的未知 CLI。

用户在 config.yml 的 ais 下新增任意 agent 时使用：
  cmd / subcommand / prompt_flag / flags 与旧版配置格式兼容，
  输出按纯文本逐行流式处理。
"""
from typing import List

from .base import AgentAdapter


class GenericAdapter(AgentAdapter):
    prompt_via_stdin = False

    def build_command(self, prompt: str) -> List[str]:
        subcommand = self.cfg.get("subcommand")
        if subcommand:
            return [self.cmd, subcommand, prompt, *self.extra_flags]
        prompt_flag = self.cfg.get("prompt_flag", "-p")
        return [self.cmd, prompt_flag, prompt, *self.extra_flags]
