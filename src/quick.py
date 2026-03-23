"""快问模式逻辑"""
from typing import Dict, List, Callable, Any


class QuickMode:
    def __init__(self, config: dict, cli_caller, prompt_loader):
        self.config = config
        self.cli_caller = cli_caller
        self.prompts = prompt_loader
        self.agents = ["claude", "gemini", "codex"]
        self.history: List[Dict[str, Any]] = []  # [{question, responses}]

    def _build_context_history(self) -> str:
        """将历史对话格式化为上下文字符串"""
        if not self.history:
            return ""
        lines = ["[历史对话]"]
        for i, entry in enumerate(self.history):
            lines.append(f"\nQ{i+1}: {entry['question']}")
            for agent, resp in entry['responses'].items():
                lines.append(f"[{agent.upper()}] {resp[:200]}...")
        return "\n".join(lines)

    async def run_question(self, question: str, cb: Callable) -> None:
        """并行问三个 AI，结果更新到各自面板"""
        import asyncio
        context = self._build_context_history()
        responses = {}

        async def ask(agent: str):
            cb("agent_start", agent=agent, role="quick")
            prompt = self.prompts.render("guest_quick", {
                "agent_name": agent.upper(),
                "question": question,
                "context_history": context,
            })
            response = await self.cli_caller.call(agent, prompt)
            responses[agent] = response
            cb("agent_response", agent=agent, content=response, role="quick")

        await asyncio.gather(*[ask(ag) for ag in self.agents])
        self.history.append({"question": question, "responses": responses})

    async def run_compare(self, cb: Callable) -> None:
        """三个 AI 互评对方本轮回答"""
        import asyncio
        if not self.history:
            cb("error", message="没有可互评的回答")
            return

        last = self.history[-1]
        question = last["question"]
        all_responses = last["responses"]

        async def critique(agent: str):
            cb("agent_start", agent=agent, role="compare")
            others = "\n\n".join(
                f"[{ag.upper()}]\n{resp}"
                for ag, resp in all_responses.items()
                if ag != agent
            )
            prompt = self.prompts.render("compare", {
                "agent_name": agent.upper(),
                "question": question,
                "others_answers": others,
            })
            response = await self.cli_caller.call(agent, prompt)
            cb("agent_response", agent=agent, content=response, role="compare")

        await asyncio.gather(*[critique(ag) for ag in self.agents])

    def get_context_for_deep(self) -> Dict[str, Any]:
        """获取用于升级到深度讨论的上下文（最后一次问答）"""
        if not self.history:
            return {}
        return self.history[-1]

    def reset(self):
        self.history = []
