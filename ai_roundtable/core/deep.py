"""Deep Round：主持人轮换的多轮结构化讨论。

状态机：idle → waiting ⇄ running → ended
用户指令：可（下一轮）/ 止（总结收场）/ 深入此节 / @agent 直问 / 其他文本（注入插话）
Solo 模式：只启用 1 个 AI 时，由它一人分饰主持人与全部嘉宾。
"""
import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from .context import ContextManager
from .events import (AgentDelta, AgentIdle, AgentProgress, AgentResponded,
                     AgentStarted, EmitFn, ErrorOccurred, ModeratorParsed,
                     SessionEnded, StatusChanged)
from .parsing import parse_action_assignments, parse_moderator_output
from .prompts import (PromptLoader, render_compress, render_guest,
                      render_moderator, render_opening, render_solo)
from .store import SessionRecord, SessionStore

_DEFAULT_ACTION = {"type": "陈述立场", "instruction": "阐明你的核心立场"}
_DEEPEN_TYPES = ["反驳", "追问", "挑战前提"]

_DIRECT_PROMPT = """你是 {agent}，参加 AI 圆桌讨论的嘉宾。

## 当前上下文
{context}

## 用户直接提问
{question}

请简洁直接地回答这个问题，200字以内："""

_SUMMARY_PROMPT = """你是 {moderator}，作为 AI 圆桌的主持人，请对整场讨论做最终总结。

## 完整讨论记录
{context}

## 任务
用300字以内总结：
1. 各方核心立场差异
2. 达成的共识（如有）
3. 未解决的核心矛盾
4. 讨论的最大价值

请直接输出总结："""


class DeepSession:
    IDLE = "idle"
    WAITING = "waiting"
    RUNNING = "running"
    ENDED = "ended"

    def __init__(self, session_id: str, agents: List[str], pool,
                 prompts: PromptLoader, store: SessionStore,
                 config: Dict[str, Any], emit: EmitFn):
        self.id = session_id
        self.agents = list(agents)
        self.pool = pool
        self.prompts = prompts
        self.store = store
        self.emit = emit

        deep_cfg = config.get("deep") or {}
        self.context = ContextManager(
            full_rounds_kept=int(deep_cfg.get("full_rounds_kept", 3)),
            compress_max=int(deep_cfg.get("compress_summary_max", 80)),
        )

        self.state = self.IDLE
        self.round_num = 0
        self.topic = ""
        self.record: Optional[SessionRecord] = None
        self._last_parsed: Optional[Dict[str, str]] = None
        self._solo = len(self.agents) == 1
        self._rotation = list(self.agents)

    # ── 公共入口 ──────────────────────────────────────────────────────────────

    @property
    def current_moderator(self) -> str:
        return self._moderator_for(max(self.round_num, 0))

    def _moderator_for(self, round_num: int) -> str:
        return self._rotation[round_num % len(self._rotation)]

    async def start(self, topic: str) -> None:
        """开场（第0轮）。完成后进入 waiting。"""
        if self.state != self.IDLE:
            self.emit(StatusChanged(self.id, state="ready",
                                    message="会话已开始"))
            return
        self.state = self.RUNNING
        moderator = self._rotation[0]
        self.emit(StatusChanged(self.id, state="running",
                                message=f"开场中，{moderator} 主持..."))
        try:
            await self._opening(topic)
            self.state = self.WAITING
            self.emit(StatusChanged(self.id, state="ready",
                                    message="开场完毕 · 输入「可」开始第1轮"))
        except Exception as e:
            self.state = self.IDLE
            self.emit(ErrorOccurred(self.id, message=f"开场失败: {e}"))
            self.emit(StatusChanged(self.id, state="ready"))

    async def start_from_quick(self, topic: str,
                               quick_entry: Dict[str, Any]) -> None:
        """从 Quick Round 升级：以快问的最后一次问答为背景，主持人先综述。"""
        if self.state != self.IDLE:
            return
        self.state = self.RUNNING
        moderator = self._rotation[0]
        self.emit(StatusChanged(self.id, state="running",
                                message=f"{moderator} 基于快问内容综述..."))
        try:
            self.topic = topic
            self.context.set_topic(topic)
            if quick_entry:
                self.context.set_quick_context(quick_entry)
            self.record = self.store.create_deep(topic)

            speeches = quick_entry.get("responses", {})
            speech_lines = "\n\n".join(
                f"[{a.upper()}]\n{resp}" for a, resp in speeches.items())
            guests_list, action_format = self._guests_vars()
            prompt = render_moderator(
                self.prompts, moderator_name=moderator.capitalize(),
                context=self.context.build_context(), round_num=0,
                round_speeches=speech_lines, guests_list=guests_list,
                guests_action_format=action_format)

            self.emit(AgentStarted(self.id, agent=moderator,
                                   role="moderator", round=0))
            raw, parsed = await self._moderator_call(moderator, prompt)
            self._last_parsed = parsed or {
                "矛盾点": "议题初始",
                "下一问": quick_entry.get("question", topic),
                "行动分配": "",
                "本轮摘要": f"议题：{topic}",
            }
            self.emit(ModeratorParsed(self.id, moderator=moderator, round=0,
                                      sections=self._last_parsed))
            self.state = self.WAITING
            self.emit(StatusChanged(self.id, state="ready",
                                    message="已升级为 Deep Round · 输入「可」开始第1轮"))
        except Exception as e:
            self.state = self.IDLE
            self.emit(ErrorOccurred(self.id, message=f"升级失败: {e}"))
            self.emit(StatusChanged(self.id, state="ready"))

    async def handle(self, user_input: str) -> None:
        """处理用户指令。"""
        if self.state == self.ENDED:
            self.emit(StatusChanged(self.id, state="ended", message="会话已结束"))
            return
        if self.state == self.RUNNING:
            self.emit(StatusChanged(self.id, state="running",
                                    message="请等待当前轮完成..."))
            return
        if self.state == self.IDLE:
            await self.start(user_input.strip())
            return

        stripped = user_input.strip()
        if stripped == "可":
            await self._guarded(self._next_round)
        elif stripped == "止":
            await self._guarded(self._end)
        elif stripped == "深入此节":
            await self._guarded(self._deepen)
        elif stripped.startswith("@"):
            await self._guarded(lambda: self._direct(stripped))
        else:
            self.context.add_user_note(stripped)
            self.emit(StatusChanged(
                self.id, state="ready",
                message=f"已注入用户插话（{len(stripped)}字）· 输入「可」继续"))

    # ── 内部：开场 ────────────────────────────────────────────────────────────

    async def _opening(self, topic: str) -> None:
        self.topic = topic
        self.context.set_topic(topic)
        self.record = self.store.create_deep(topic)
        moderator = self._rotation[0]

        if self._solo:
            self.emit(AgentStarted(self.id, agent=moderator,
                                   role="guest", round=0))
            prompt = render_solo(self.prompts, topic=topic,
                                 context=self.context.build_context(),
                                 round_num=0, moderator_question=topic)
            res = await self._call(moderator, prompt)
            self.emit(AgentResponded(self.id, agent=moderator,
                                     content=res.display_text,
                                     role="guest", round=0))
            self._last_parsed = self._parse_solo(res.display_text) or {
                "矛盾点": "议题初始", "下一问": topic,
                "行动分配": "", "本轮摘要": f"议题：{topic}",
            }
            return

        guests_list, action_format = self._guests_vars(opening=True)
        prompt = render_opening(
            self.prompts, moderator_name=moderator.capitalize(), topic=topic,
            guests_list=guests_list, guests_action_format=action_format)
        self.emit(AgentStarted(self.id, agent=moderator,
                               role="moderator", round=0))
        raw, parsed = await self._moderator_call(moderator, prompt)
        self._last_parsed = parsed or {
            "矛盾点": "议题初始", "下一问": topic,
            "行动分配": "", "本轮摘要": f"议题：{topic}",
        }
        self.emit(ModeratorParsed(self.id, moderator=moderator, round=0,
                                  sections=self._last_parsed))

    # ── 内部：讨论轮 ──────────────────────────────────────────────────────────

    async def _next_round(self) -> None:
        self.round_num += 1
        round_num = self.round_num
        moderator = self._moderator_for(round_num)
        self.emit(StatusChanged(self.id, state="running",
                                message=f"第{round_num}轮开始，{moderator} 主持..."))

        question = (self._last_parsed or {}).get("下一问", "")
        speeches: Dict[str, str] = {}

        if self._solo:
            await self._solo_round(round_num, question, speeches)
            raw, parsed = "", None
            solo_parsed = self._parse_solo(next(iter(speeches.values()), ""))
            if solo_parsed:
                self._last_parsed = solo_parsed
        else:
            assignments = {}
            if self._last_parsed and self._last_parsed.get("行动分配"):
                assignments = parse_action_assignments(
                    self._last_parsed["行动分配"])
            if not assignments:
                assignments = {a: dict(_DEFAULT_ACTION) for a in self.agents}

            if round_num == 1:
                await self._parallel_speeches(round_num, question,
                                              assignments, speeches)
            else:
                await self._sequential_speeches(round_num, question,
                                                assignments, speeches)
            raw, parsed = await self._run_moderator(round_num, moderator,
                                                    speeches)
            # 解析失败时保留上一轮的综述：下一轮沿用旧「下一问」好过空问题
            if parsed:
                self._last_parsed = parsed

        round_data = {
            "round": round_num,
            "moderator": moderator,
            "speeches": speeches,
            "moderator_raw": raw,
            "moderator_parsed": parsed or {},
        }
        self.context.add_round(round_data)
        await self._compress_if_needed()

        try:
            if self.record:
                self.store.append_deep_round(self.record, round_data)
        except OSError as e:
            self.emit(ErrorOccurred(self.id, message=f"历史写入失败: {e}"))

        self.state = self.WAITING
        self.emit(StatusChanged(self.id, state="ready",
                                message=f"轮{round_num} · 等待: 可/止/深入此节"))

    async def _parallel_speeches(self, round_num: int, question: str,
                                 assignments: Dict, speeches: Dict) -> None:
        async def speak(agent: str) -> None:
            self.emit(AgentStarted(self.id, agent=agent,
                                   role="guest", round=round_num))
            assignment = assignments.get(agent, _DEFAULT_ACTION)
            prompt = render_guest(
                self.prompts, agent_name=agent.capitalize(),
                context=self.context.build_context(), round_num=round_num,
                moderator_question=question,
                action_type=assignment.get("type", _DEFAULT_ACTION["type"]),
                action_instruction=assignment.get(
                    "instruction", _DEFAULT_ACTION["instruction"]),
                prior_speeches="")  # 并行轮：看不到他人发言
            res = await self._call(agent, prompt)
            speeches[agent] = res.display_text
            self.emit(AgentResponded(self.id, agent=agent,
                                     content=res.display_text,
                                     role="guest", round=round_num))

        await asyncio.gather(*(speak(a) for a in self.agents))

    async def _sequential_speeches(self, round_num: int, question: str,
                                   assignments: Dict, speeches: Dict) -> None:
        for agent in self.agents:
            self.emit(AgentStarted(self.id, agent=agent,
                                   role="guest", round=round_num))
            assignment = assignments.get(agent, _DEFAULT_ACTION)
            prior_lines = [f"[{a.upper()}] {speeches[a]}"
                           for a in self.agents if a in speeches]
            prior = "\n\n".join(prior_lines) if prior_lines else "（你是第一位发言者）"
            prompt = render_guest(
                self.prompts, agent_name=agent.capitalize(),
                context=self.context.build_context(), round_num=round_num,
                moderator_question=question,
                action_type=assignment.get("type", _DEFAULT_ACTION["type"]),
                action_instruction=assignment.get(
                    "instruction", _DEFAULT_ACTION["instruction"]),
                prior_speeches=prior)
            res = await self._call(agent, prompt)
            speeches[agent] = res.display_text
            self.emit(AgentResponded(self.id, agent=agent,
                                     content=res.display_text,
                                     role="guest", round=round_num))

    async def _solo_round(self, round_num: int, question: str,
                          speeches: Dict[str, str]) -> None:
        agent = self.agents[0]
        self.emit(AgentStarted(self.id, agent=agent,
                               role="guest", round=round_num))
        prompt = render_solo(self.prompts, topic=self.topic,
                             context=self.context.build_context(),
                             round_num=round_num,
                             moderator_question=question or self.topic)
        res = await self._call(agent, prompt)
        speeches[agent] = res.display_text
        self.emit(AgentResponded(self.id, agent=agent,
                                 content=res.display_text,
                                 role="guest", round=round_num))

    @staticmethod
    def _parse_solo(text: str) -> Optional[Dict[str, str]]:
        """从 solo 输出的【主持人综述】里提取下一个问题/核心矛盾，驱动下一轮。"""
        q = re.search(r"下一个问题[：:]\s*(.+)", text)
        if not q:
            return None
        c = re.search(r"核心矛盾[：:]\s*(.+)", text)
        return {
            "矛盾点": c.group(1).strip() if c else "",
            "下一问": q.group(1).strip(),
            "行动分配": "",
            "本轮摘要": "",
        }

    async def _run_moderator(self, round_num: int, moderator: str,
                             speeches: Dict[str, str]) -> Tuple[str, Optional[Dict]]:
        self.emit(AgentStarted(self.id, agent=moderator,
                               role="moderator", round=round_num))
        round_speeches = "\n\n".join(
            f"[{a.upper()}]\n{speeches[a]}" for a in self.agents
            if a in speeches)
        guests_list, action_format = self._guests_vars()
        prompt = render_moderator(
            self.prompts, moderator_name=moderator.capitalize(),
            context=self.context.build_context(), round_num=round_num,
            round_speeches=round_speeches, guests_list=guests_list,
            guests_action_format=action_format)

        raw, parsed = await self._moderator_call(moderator, prompt)
        if parsed:
            self.emit(ModeratorParsed(self.id, moderator=moderator,
                                      round=round_num, sections=parsed))
        else:
            self.emit(StatusChanged(self.id, state="running",
                                    message="主持人格式仍不符，跳过综述"))
        return raw, parsed

    async def _moderator_call(self, moderator: str,
                              prompt: str) -> Tuple[str, Optional[Dict]]:
        """调用主持人并解析结构化输出；格式不符时重试一次。"""
        res = await self._call(moderator, prompt)
        parsed = parse_moderator_output(res.text) if res.ok else None
        if parsed is None:
            self.emit(StatusChanged(self.id, state="running",
                                    message="主持人格式不符，重试..."))
            res = await self._call(moderator, prompt)
            parsed = parse_moderator_output(res.text) if res.ok else None
        return res.display_text, parsed

    # ── 内部：压缩 / 深入 / 直问 / 收场 ──────────────────────────────────────

    async def _compress_if_needed(self) -> None:
        if not self.context.needs_compression():
            return
        oldest = self.context.get_round_to_compress()
        summary = (oldest.get("moderator_parsed") or {}).get("本轮摘要", "")
        if not summary:
            self.emit(StatusChanged(self.id, state="running",
                                    message="压缩历史上下文中..."))
            prompt = render_compress(
                self.prompts,
                round_content=self.context.format_round(oldest))
            res = await self._call(self.current_moderator, prompt)
            summary = res.text if res.ok else \
                f"第{oldest['round']}轮讨论（压缩失败，内容省略）"
        self.context.apply_compression(summary)

    async def _deepen(self) -> None:
        """深入当前矛盾点：不推进轮次，顺序发言，无主持人综述。"""
        if self._last_parsed is None:
            self.state = self.WAITING
            self.emit(StatusChanged(self.id, state="ready",
                                    message="没有当前矛盾点可深入"))
            return
        round_num = self.round_num
        self.emit(StatusChanged(self.id, state="running",
                                message=f"深入当前节点，轮{round_num}..."))

        assignments = {
            agent: {"type": _DEEPEN_TYPES[i % len(_DEEPEN_TYPES)],
                    "instruction": "围绕矛盾点深入探讨"}
            for i, agent in enumerate(self.agents)
        }
        question = self._last_parsed.get("矛盾点", "请深入当前矛盾点")
        speeches: Dict[str, str] = {}
        await self._sequential_speeches(round_num, question,
                                        assignments, speeches)

        # 深入内容也进入上下文与历史（旧版会丢弃，后续轮次看不到）
        round_data = {"round": round_num, "moderator": "",
                      "speeches": speeches, "moderator_raw": "",
                      "moderator_parsed": {}, "deepen": True}
        self.context.add_round(round_data)
        await self._compress_if_needed()
        try:
            if self.record:
                self.store.append_deep_round(self.record, round_data)
        except OSError as e:
            self.emit(ErrorOccurred(self.id, message=f"历史写入失败: {e}"))

        self.state = self.WAITING
        self.emit(StatusChanged(self.id, state="ready",
                                message="深入完毕 · 「可」继续下一轮，或继续「深入此节」"))

    async def _direct(self, user_input: str) -> None:
        m = re.match(r"^@(\w+)\s+(.*)", user_input, re.DOTALL)
        if not m:
            self.state = self.WAITING
            hint = "/".join(self.agents)
            self.emit(StatusChanged(self.id, state="ready",
                                    message=f"格式错误，请用 @{hint} 内容"))
            return
        agent = m.group(1).lower()
        question = m.group(2).strip()
        if agent not in self.pool.adapters:
            self.state = self.WAITING
            self.emit(StatusChanged(self.id, state="ready",
                                    message=f"未知 agent: {agent}"))
            return

        self.emit(AgentStarted(self.id, agent=agent, role="guest",
                               round=self.round_num))
        self.emit(StatusChanged(self.id, state="running",
                                message=f"询问 {agent}..."))
        prompt = _DIRECT_PROMPT.format(
            agent=agent.capitalize(),
            context=self.context.build_context(), question=question)
        res = await self._call(agent, prompt)
        self.emit(AgentResponded(self.id, agent=agent,
                                 content=res.display_text, role="direct",
                                 round=self.round_num, extra=question))
        self.state = self.WAITING
        self.emit(StatusChanged(self.id, state="ready",
                                message=f"轮{self.round_num} · 等待: 可/止/深入此节"))

    async def _end(self) -> None:
        self.emit(StatusChanged(self.id, state="running", message="生成总结..."))
        moderator = self.current_moderator
        prompt = _SUMMARY_PROMPT.format(
            moderator=moderator.capitalize(),
            context=self.context.build_context())
        res = await self._call(moderator, prompt)
        summary = res.display_text

        md_path = None
        try:
            if self.record:
                self.store.append_deep_summary(self.record, summary)
                md_path = self.record.md_path
        except OSError:
            pass

        self.state = self.ENDED
        end_msg = summary
        if md_path:
            end_msg += f"\n\n[会话已保存至: {md_path}]"
        self.emit(SessionEnded(self.id, summary=end_msg))
        self.emit(StatusChanged(self.id, state="ended", message="会话已结束"))

    # ── 工具 ─────────────────────────────────────────────────────────────────

    async def _guarded(self, fn) -> None:
        self.state = self.RUNNING
        try:
            await fn()
        except Exception as e:
            self.emit(ErrorOccurred(self.id, message=f"执行失败: {e}"))
        finally:
            if self.state == self.RUNNING:
                self.state = self.WAITING
                self.emit(StatusChanged(self.id, state="ready"))

    def _guests_vars(self, opening: bool = False) -> Tuple[str, str]:
        guests_list = "、".join(a.capitalize() for a in self.agents)
        if opening:
            action_format = "\n".join(
                f"{a.capitalize()}：陈述立场 - 从你的视角阐明对此议题的核心立场"
                for a in self.agents)
        else:
            action_format = "\n".join(
                f"{a.capitalize()}：{{行动类型}} - {{具体说明}}"
                for a in self.agents)
        return guests_list, action_format

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

    def responses_for(self, agent: str) -> List[str]:
        """该 agent 的全部发言（查看/复制用），来自持久化记录。"""
        if not self.record:
            return []
        parts = []
        for rnd in self.record.data.get("rounds", []):
            if agent in rnd.get("speeches", {}):
                parts.append(rnd["speeches"][agent])
        return parts
