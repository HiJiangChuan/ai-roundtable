"""快问模式逻辑"""
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional


class QuickMode:
    def __init__(self, config: dict, cli_caller, prompt_loader,
                 history=None, quick_file: Optional[Path] = None):
        self.config = config
        self.cli_caller = cli_caller
        self.prompts = prompt_loader
        self.history = history
        self.quick_file = quick_file          # file this session writes to
        self.agents = ["claude", "gemini", "codex"]
        self.history_local: List[Dict[str, Any]] = []

    def _build_context_history(self) -> str:
        if not self.history_local:
            return ""
        lines = ["[历史对话]"]
        for i, entry in enumerate(self.history_local):
            lines.append(f"\nQ{i+1}: {entry['question']}")
            for agent, resp in entry['responses'].items():
                lines.append(f"[{agent.upper()}] {resp[:200]}...")
        return "\n".join(lines)

    async def run_question(self, question: str, cb: Callable) -> None:
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
        self.history_local.append({"question": question, "responses": responses})

        if self.history and self.quick_file:
            try:
                self.history.append_quick_entry(question, responses, path=self.quick_file)
            except Exception:
                pass

        # Generate title from first question only
        if len(self.history_local) == 1:
            asyncio.create_task(self._generate_title(question, cb))

    async def _generate_title(self, question: str, cb: Callable) -> None:
        import re
        prompt = (
            "用4个汉字以内总结以下问题的核心主题，"
            "只回复标题本身，不加标点、解释或换行：\n"
            f"{question[:300]}"
        )
        try:
            raw = await self.cli_caller.call('claude', prompt)
            title = raw.strip().splitlines()[0]
            title = re.sub(r'[\\/:*?"<>|【】《》\s]', '', title)[:10]
            if title:
                cb("session_title", title=title)
        except Exception:
            pass

    async def run_compare(self, cb: Callable) -> None:
        import asyncio
        if not self.history_local:
            cb("error", message="没有可互评的回答")
            return

        last = self.history_local[-1]
        question = last["question"]
        all_responses = last["responses"]
        compare_responses: Dict[str, str] = {}

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
            compare_responses[agent] = response
            cb("agent_response", agent=agent, content=response, role="compare")

        await asyncio.gather(*[critique(ag) for ag in self.agents])

        if self.history and self.quick_file:
            try:
                self.history.append_quick_compare(compare_responses, path=self.quick_file)
            except Exception:
                pass

    def get_context_for_deep(self) -> Dict[str, Any]:
        if not self.history_local:
            return {}
        return self.history_local[-1]

    def reset(self):
        self.history_local = []
