"""
CLI Caller - Executes CLI commands for each AI agent with timeout and ANSI stripping.
"""
import asyncio
import re
import shlex
from typing import Dict, Any


ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    return ANSI_ESCAPE.sub('', text)


class CliCaller:
    def __init__(self, config: Dict[str, Any], timeout: int = None):
        self.config = config
        if timeout is not None:
            self.timeout = timeout
        else:
            # legacy fallback: check cli.timeout, then deep.timeout_seconds
            self.timeout = (
                config.get('cli', {}).get('timeout')
                or config.get('deep', {}).get('timeout_seconds', 30)
            )
        self.ais = config.get('ais', {})

    def _build_command(self, agent: str, prompt: str):
        """Build command list for the given agent.

        Supports two styles:
          flag:       cmd prompt_flag prompt [flags...]  e.g. claude -p "..." --dangerously-skip-permissions
          subcommand: cmd subcommand prompt [flags...]   e.g. codex exec "..."
        """
        agent_cfg = self.ais.get(agent, {})
        cmd = agent_cfg.get('cmd', agent)
        flags = agent_cfg.get('flags', [])

        subcommand = agent_cfg.get('subcommand')
        if subcommand:
            return [cmd, subcommand, prompt] + flags

        prompt_flag = agent_cfg.get('prompt_flag', '-p')
        return [cmd, prompt_flag, prompt] + flags

    async def call(self, agent: str, prompt: str) -> str:
        """
        Call the CLI for an agent with the given prompt.
        Returns the response string, or [无响应：reason] on failure.
        """
        if agent not in self.ais:
            return f"[无响应：未知 agent '{agent}']"

        cmd = self._build_command(agent, prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return "[无响应：超时]"

            if proc.returncode != 0:
                err_msg = strip_ansi(stderr.decode('utf-8', errors='replace')).strip()
                if err_msg:
                    return f"[无响应：{err_msg[:100]}]"
                return f"[无响应：退出码 {proc.returncode}]"

            output = stdout.decode('utf-8', errors='replace')
            output = strip_ansi(output).strip()

            if not output:
                return "[无响应：输出为空]"

            return output

        except FileNotFoundError:
            return f"[无响应：命令未找到 '{self.ais[agent].get('cmd', agent)}']"
        except Exception as e:
            return f"[无响应：{str(e)[:100]}]"
