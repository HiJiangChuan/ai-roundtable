"""Quick Round：所有启用的 AI 并行回答同一个问题。"""
import asyncio
import re
from typing import Any, Dict, List, Optional

from .events import (AgentDelta, AgentIdle, AgentProgress, AgentResponded,
                     AgentStarted, EmitFn, ErrorOccurred, StatusChanged,
                     TitleGenerated)
from .prompts import PromptLoader, render_compare, render_guest_quick
from .store import SessionRecord, SessionStore

_TITLE_PROMPT = ("用4个汉字以内总结以下问题的核心主题，"
                 "只回复标题本身，不加标点、解释或换行：\n")
_TITLE_STRIP = re.compile(r'[\\/:*?"<>|【】《》\[\]\s]')


class QuickSession:
    def __init__(self, session_id: str, agents: List[str], pool,
                 prompts: PromptLoader, store: SessionStore,
                 config: Dict[str, Any], emit: EmitFn):
        self.id = session_id
        self.agents = list(agents)
        self.pool = pool
        self.prompts = prompts
        self.store = store
        self.emit = emit

        quick_cfg = config.get("quick") or {}
        self.context_entries = int(quick_cfg.get("context_entries", 5))
        self.answer_snippet = int(quick_cfg.get("answer_snippet", 500))

        self.entries: List[Dict[str, Any]] = []
        self.record: Optional[SessionRecord] = None
        self.title: str = ""
        self._title_task: Optional[asyncio.Task] = None

    def preload(self, record: SessionRecord,
                entries: List[Dict[str, Any]], title: str = "") -> None:
        """从历史会话恢复：绑定既有记录并预置问答。"""
        self.record = record
        self.entries = list(entries)
        self.title = title

    # ── 上下文 ───────────────────────────────────────────────────────────────

    def _build_context(self) -> str:
        if not self.entries:
            return ""
        recent = self.entries[-self.context_entries:]
        lines = ["[历史对话]"]
        for i, entry in enumerate(recent):
            lines.append(f"\nQ{i + 1}: {entry['question']}")
            for agent, resp in entry.get("responses", {}).items():
                snippet = resp[:self.answer_snippet]
                suffix = "…" if len(resp) > self.answer_snippet else ""
                lines.append(f"[{agent.upper()}] {snippet}{suffix}")
        return "\n".join(lines)

    # ── 提问 ─────────────────────────────────────────────────────────────────

    async def ask(self, question: str) -> None:
        self.emit(StatusChanged(self.id, state="running"))
        try:
            context = self._build_context()
            responses: Dict[str, str] = {}

            async def one(agent: str) -> None:
                self.emit(AgentStarted(self.id, agent=agent, role="quick"))
                prompt = render_guest_quick(
                    self.prompts, agent_name=agent.upper(),
                    question=question, context_history=context)
                res = await self._call(agent, prompt)
                responses[agent] = res.display_text
                self.emit(AgentResponded(self.id, agent=agent,
                                         content=res.display_text, role="quick"))

            await asyncio.gather(*(one(a) for a in self.agents))
            self.entries.append({"question": question, "responses": responses})

            try:
                if self.record is None:
                    self.record = self.store.create_quick()
                self.store.append_quick_entry(self.record, question, responses)
            except OSError as e:
                self.emit(ErrorOccurred(self.id, message=f"历史写入失败: {e}"))

            if len(self.entries) == 1 and not self.title:
                self._title_task = asyncio.create_task(
                    self._generate_title(question))
                self._title_task.add_done_callback(self._title_done)
        except Exception as e:
            self.emit(ErrorOccurred(self.id, message=f"快问失败: {e}"))
        finally:
            self.emit(StatusChanged(self.id, state="ready"))

    async def compare(self) -> None:
        """互评：每个 AI 点评其他 AI 对最后一个问题的回答。"""
        if not self.entries:
            self.emit(ErrorOccurred(self.id, message="没有可互评的回答"))
            return
        self.emit(StatusChanged(self.id, state="running"))
        try:
            last = self.entries[-1]
            question = last["question"]
            all_responses = last.get("responses", {})
            critiques: Dict[str, str] = {}

            async def one(agent: str) -> None:
                self.emit(AgentStarted(self.id, agent=agent, role="compare"))
                others = "\n\n".join(
                    f"[{a.upper()}]\n{resp}"
                    for a, resp in all_responses.items() if a != agent)
                prompt = render_compare(
                    self.prompts, agent_name=agent.upper(),
                    question=question, others_answers=others)
                res = await self._call(agent, prompt)
                critiques[agent] = res.display_text
                self.emit(AgentResponded(self.id, agent=agent,
                                         content=res.display_text, role="compare"))

            await asyncio.gather(*(one(a) for a in self.agents))

            if self.record is not None:
                try:
                    self.store.append_quick_compare(self.record, critiques)
                except OSError as e:
                    self.emit(ErrorOccurred(self.id, message=f"互评历史写入失败: {e}"))
        except Exception as e:
            self.emit(ErrorOccurred(self.id, message=f"互评失败: {e}"))
        finally:
            self.emit(StatusChanged(self.id, state="ready"))

    # ── 标题 ─────────────────────────────────────────────────────────────────

    async def _generate_title(self, question: str) -> None:
        res = await self.pool.call(self.agents[0],
                                   _TITLE_PROMPT + question[:300])
        if not res.ok or not res.text.strip():
            return
        title = _TITLE_STRIP.sub("", res.text.strip().splitlines()[0])[:10]
        if not title:
            return
        self.title = title
        if self.record is not None:
            try:
                self.store.set_quick_title(self.record, title)
            except OSError:
                pass
        self.emit(TitleGenerated(self.id, title=title))

    def _title_done(self, task: asyncio.Task) -> None:
        self._title_task = None
        if not task.cancelled() and task.exception():
            self.emit(ErrorOccurred(self.id,
                                    message=f"标题生成失败: {task.exception()}"))

    # ── 其他 ─────────────────────────────────────────────────────────────────

    async def _call(self, agent: str, prompt: str):
        return await self.pool.call(
            agent, prompt,
            on_delta=lambda t, a=agent: self.emit(
                AgentDelta(self.id, agent=a, text=t)),
            on_progress=lambda l, a=agent: self.emit(
                AgentProgress(self.id, agent=a, line=l)),
            on_idle=lambda e, a=agent: self.emit(
                AgentIdle(self.id, agent=a, elapsed=e)),
        )

    def last_entry(self) -> Dict[str, Any]:
        """升级 Deep Round 时携带的快问上下文。"""
        return self.entries[-1] if self.entries else {}

    def responses_for(self, agent: str) -> List[str]:
        """该 agent 的全部回答（查看/复制用）。"""
        return [e["responses"][agent] for e in self.entries
                if agent in e.get("responses", {})]
