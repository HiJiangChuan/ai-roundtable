"""
Orchestrator - Core state machine for AI Roundtable discussions.

States: idle -> waiting -> running -> ended
"""
import asyncio
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cli_caller import CliCaller
from prompt_loader import PromptLoader
from context_manager import ContextManager
from history import History


def parse_moderator_output(text: str) -> Optional[Dict[str, str]]:
    """
    Parse structured moderator output into a dict.
    Returns None if format doesn't match.
    """
    result = {}
    sections = ['矛盾点', '下一问', '行动分配', '本轮摘要']

    for i, section in enumerate(sections):
        pattern = r'【' + section + r'】\s*(.*?)(?=【|$)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            result[section] = match.group(1).strip()

    # Must have all four sections
    if len(result) < 4:
        return None

    return result


def parse_action_assignments(action_text: str) -> Dict[str, Dict[str, str]]:
    """
    Parse action assignment text into per-agent action dicts.
    Returns {agent: {type: str, instruction: str}}
    Supports any agent name (not hardcoded to Claude/Codex/Gemini).
    """
    assignments = {}
    for line in action_text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        match = re.match(r'^(\w+)[：:]\s*([^-–—]+?)\s*[-–—]\s*(.+)$', line)
        if match:
            assignments[match.group(1).lower()] = {
                'type': match.group(2).strip(),
                'instruction': match.group(3).strip(),
            }
    return assignments


class Orchestrator:
    # States
    STATE_IDLE = "idle"
    STATE_WAITING = "waiting"
    STATE_RUNNING = "running"
    STATE_ENDED = "ended"

    def __init__(self, project_root: Path, config: Dict[str, Any],
                 history=None, active_agents: Optional[List[str]] = None):
        self.project_root = Path(project_root)
        self.config = config

        self._state = self.STATE_IDLE
        self._round_num = 0
        self._session_id: Optional[str] = None
        self._topic: str = ""
        self._last_moderator_parsed: Optional[Dict[str, str]] = None

        # Active agents — derived from config order, filtered by enabled flag
        if active_agents is not None:
            self._active_agents = active_agents
        else:
            self._active_agents = [
                k for k, v in config.get('ais', {}).items()
                if v.get('enabled', True)
            ]

        # Solo mode: 1 agent plays all roles (李继刚 圆桌 style)
        self._solo = len(self._active_agents) == 1

        # Moderator rotation and speaking order derived from active agents
        self._moderator_rotation: List[str] = self._active_agents
        self._speaking_order: List[str] = self._active_agents

        # Components
        prompts_dir = self.project_root / 'prompts'
        self.prompt_loader = PromptLoader(prompts_dir)

        # Build cli config with timeout from deep section
        timeout = config.get('deep', {}).get('timeout_seconds', 30)
        self.cli_caller = CliCaller(config, timeout=timeout)

        deep_cfg = config.get('deep', {})
        self.context_manager = ContextManager(
            full_rounds_kept=deep_cfg.get('full_rounds_kept', 3),
            compress_max=deep_cfg.get('compress_summary_max', 80)
        )

        self.history = history if history is not None else History(config, project_root=self.project_root)

    @property
    def state(self) -> str:
        return self._state

    @property
    def round_num(self) -> int:
        return self._round_num

    @property
    def current_moderator(self) -> str:
        if self._round_num == 0:
            return self._moderator_rotation[0]
        return self._get_moderator_for_round(self._round_num)

    def _get_moderator_for_round(self, round_num: int) -> str:
        return self._moderator_rotation[round_num % len(self._moderator_rotation)]

    async def start_session(self, topic: str, cb: Callable) -> None:
        """Run the opening (round 0). After completion, state becomes 'waiting'."""
        if self._state != self.STATE_IDLE:
            cb("error", message="Session already started")
            return

        self._state = self.STATE_RUNNING
        self._topic = topic
        self.context_manager.set_topic(topic)
        self._session_id = self.history.new_session(topic)

        moderator = self._moderator_rotation[0]
        cb("status", message=f"开场中，{moderator} 主持...", state=self._state)
        cb("agent_start", agent=moderator, round=0, role="moderator")

        try:
            if self._solo:
                prompt = self.prompt_loader.render('solo_roundtable', {
                    'topic': topic,
                })
            else:
                guests = [a for a in self._active_agents if a != moderator] + [moderator]
                guests_list = "、".join(a.capitalize() for a in self._active_agents)
                guests_action_format = "\n".join(
                    f"{a.capitalize()}：陈述立场 - 从你的视角阐明对此议题的核心立场"
                    for a in self._active_agents
                )
                prompt = self.prompt_loader.render('opening', {
                    'moderator_name': moderator.capitalize(),
                    'topic': topic,
                    'guests_list': guests_list,
                    'guests_action_format': guests_action_format,
                })
        except FileNotFoundError as e:
            cb("error", message=str(e))
            self._state = self.STATE_IDLE
            return

        raw = await self.cli_caller.call(moderator, prompt)

        if self._solo:
            cb("agent_response", agent=moderator, round=0, content=raw, role="moderator")
            self._last_moderator_parsed = {'矛盾点': '议题初始', '下一问': topic,
                                           '行动分配': '', '本轮摘要': f'议题：{topic}'}
        else:
            parsed = parse_moderator_output(raw)
            if parsed is None:
                cb("status", message="开场格式不符，重试...", state=self._state)
                raw = await self.cli_caller.call(moderator, prompt)
                parsed = parse_moderator_output(raw)

            cb("agent_response", agent=moderator, round=0, content=raw, role="moderator")

            if parsed:
                self._last_moderator_parsed = parsed
                cb("moderator_output", moderator=moderator, round=0, parsed=parsed, raw=raw)
            else:
                self._last_moderator_parsed = {
                    '矛盾点': '议题初始', '下一问': topic,
                    '行动分配': '', '本轮摘要': f'议题：{topic}'
                }
                cb("moderator_output", moderator=moderator, round=0,
                   parsed=self._last_moderator_parsed, raw=raw)

        self._state = self.STATE_WAITING
        cb("status", message=f"Session {self._session_id} · 开场完毕 · 输入「可」开始第1轮",
           state=self._state)

    async def init_from_quick(self, topic: str, quick_context: dict, cb: Callable) -> None:
        """从 Quick Round 升级到 Deep Round，携带快问历史"""
        self._state = self.STATE_RUNNING
        self._topic = topic
        self.context_manager.set_topic(topic)
        self._session_id = self.history.new_session(topic)

        # 将快问的最后一次问答注入为第0轮
        if quick_context:
            self.context_manager.set_quick_context(quick_context)

        # Gemini 基于已有内容直接综述（不用 opening.md，用 moderator.md）
        moderator = self._moderator_rotation[0]
        cb("status", message=f"{moderator} 基于快问内容综述...", state=self._state)

        speeches = quick_context.get('responses', {})
        speech_lines = "\n\n".join(
            f"[{ag.upper()}]\n{resp}" for ag, resp in speeches.items()
        )
        context = self.context_manager.build_context()
        prompt = self.prompt_loader.render('moderator', {
            'moderator_name': moderator.capitalize(),
            'context': context,
            'round_num': '0',
            'round_speeches': speech_lines,
        })
        raw = await self.cli_caller.call(moderator, prompt)
        parsed = parse_moderator_output(raw)
        if not parsed:
            raw = await self.cli_caller.call(moderator, prompt)
            parsed = parse_moderator_output(raw)

        if parsed:
            self._last_moderator_parsed = parsed
        else:
            self._last_moderator_parsed = {
                '矛盾点': '议题初始',
                '下一问': quick_context.get('question', topic),
                '行动分配': '',
                '本轮摘要': f'议题：{topic}'
            }

        cb("moderator_output", moderator=moderator, round=0,
           parsed=self._last_moderator_parsed, raw=raw)
        self._state = self.STATE_WAITING
        cb("status", message="Quick Round 已升级为 Deep Round · 输入「可」开始第1轮", state=self._state)

    async def handle_command(self, user_input: str, cb: Callable) -> None:
        """Handle user commands: 可/止/深入此节/@agent/free text."""
        if self._state == self.STATE_ENDED:
            cb("status", message="会话已结束", state=self._state)
            return

        if self._state == self.STATE_RUNNING:
            cb("status", message="请等待当前轮完成...", state=self._state)
            return

        stripped = user_input.strip()

        if stripped == '可':
            await self._run_next_round(cb)

        elif stripped == '止':
            await self._end_session(cb)

        elif stripped == '深入此节':
            await self._deepen_current(cb)

        elif stripped.startswith('@'):
            await self._handle_direct_question(stripped, cb)

        else:
            # Free text - inject as context, prompt user to continue
            cb("status",
               message=f"已注入用户插话：「{stripped[:30]}...」· 输入「可」继续",
               state=self._state)
            # Store the user interjection in context
            self.context_manager.set_topic(
                self.context_manager.topic_summary + f"（用户补充：{stripped[:30]}）"
            )

    async def _run_next_round(self, cb: Callable) -> None:
        """Execute the next discussion round."""
        self._state = self.STATE_RUNNING
        self._round_num += 1
        round_num = self._round_num
        moderator = self._get_moderator_for_round(round_num)

        cb("status", message=f"第{round_num}轮开始，{moderator} 主持...", state=self._state)

        moderator_question = (self._last_moderator_parsed or {}).get('下一问', '')
        speeches: Dict[str, str] = {}

        if self._solo:
            # Solo: one AI plays all roles in a single call
            await self._run_solo_round(round_num, moderator, moderator_question, speeches, cb)
            moderator_raw, moderator_parsed = "", None
        else:
            # Get action assignments from last moderator output
            action_assignments = {}
            if self._last_moderator_parsed and '行动分配' in self._last_moderator_parsed:
                action_assignments = parse_action_assignments(
                    self._last_moderator_parsed['行动分配']
                )
            if not action_assignments:
                action_assignments = {
                    agent: {'type': '陈述立场', 'instruction': '阐明你的核心立场'}
                    for agent in self._speaking_order
                }

            if round_num == 1:
                await self._run_parallel_speeches(
                    round_num, moderator, moderator_question,
                    action_assignments, speeches, cb
                )
            else:
                await self._run_sequential_speeches(
                    round_num, moderator, moderator_question,
                    action_assignments, speeches, cb
                )

            moderator_raw, moderator_parsed = await self._run_moderator(
                round_num, moderator, speeches, cb
            )

        # Build round data
        round_data = {
            'round': round_num,
            'moderator': moderator,
            'speeches': speeches,
            'moderator_raw': moderator_raw,
            'moderator_parsed': moderator_parsed or {}
        }

        # Update context
        self.context_manager.add_round(round_data)
        self._last_moderator_parsed = moderator_parsed

        # Compress if needed (v2.0: use 【本轮摘要】 as compression result)
        if self.context_manager.needs_compression():
            oldest = self.context_manager.get_round_to_compress()
            summary = (oldest.get('moderator_parsed') or {}).get('本轮摘要', '')
            if not summary:
                # fallback: use compress prompt
                await self._do_compression(cb)
            else:
                self.context_manager.apply_compression(summary)

        # Save to history (non-fatal if it fails)
        try:
            self.history.add_round(self._session_id, round_data)
        except Exception:
            pass

        self._state = self.STATE_WAITING
        cb("status",
           message=f"Session {self._session_id} · 轮{round_num} · 等待: 可/止/深入此节",
           state=self._state)

    async def _run_parallel_speeches(
        self, round_num: int, moderator: str, moderator_question: str,
        action_assignments: Dict, speeches: Dict, cb: Callable
    ) -> None:
        """Run all agent speeches in parallel (round 1)."""
        agents = self._speaking_order

        async def speak(agent: str):
            cb("agent_start", agent=agent, round=round_num, role="guest")
            assignment = action_assignments.get(agent, {})
            action_type = assignment.get('type', '陈述立场')
            action_instruction = assignment.get('instruction', '阐明你的核心立场')

            context = self.context_manager.build_context()
            prompt = self.prompt_loader.render('guest', {
                'agent_name': agent.capitalize(),
                'context': context,
                'round_num': str(round_num),
                'moderator_question': moderator_question,
                'action_type': action_type,
                'action_instruction': action_instruction,
                'prior_speeches': ''  # Parallel: no prior speeches visible
            })

            response = await self.cli_caller.call(agent, prompt)
            speeches[agent] = response
            cb("agent_response", agent=agent, round=round_num, content=response, role="guest")

        await asyncio.gather(*[speak(agent) for agent in agents])

    async def _run_sequential_speeches(
        self, round_num: int, moderator: str, moderator_question: str,
        action_assignments: Dict, speeches: Dict, cb: Callable
    ) -> None:
        """Run agent speeches sequentially (rounds >= 2)."""
        for agent in self._speaking_order:
            cb("agent_start", agent=agent, round=round_num, role="guest")
            assignment = action_assignments.get(agent, {})
            action_type = assignment.get('type', '陈述立场')
            action_instruction = assignment.get('instruction', '阐明你的核心立场')

            # Build prior speeches text
            prior_lines = []
            for prior_agent in self._speaking_order:
                if prior_agent == agent:
                    break
                if prior_agent in speeches:
                    prior_lines.append(f"[{prior_agent.upper()}] {speeches[prior_agent]}")
            prior_speeches = '\n\n'.join(prior_lines) if prior_lines else '（你是第一位发言者）'

            context = self.context_manager.build_context()
            prompt = self.prompt_loader.render('guest', {
                'agent_name': agent.capitalize(),
                'context': context,
                'round_num': str(round_num),
                'moderator_question': moderator_question,
                'action_type': action_type,
                'action_instruction': action_instruction,
                'prior_speeches': prior_speeches
            })

            response = await self.cli_caller.call(agent, prompt)
            speeches[agent] = response
            cb("agent_response", agent=agent, round=round_num, content=response, role="guest")

    async def _run_solo_round(
        self, round_num: int, agent: str, moderator_question: str,
        speeches: Dict[str, str], cb: Callable
    ) -> None:
        """Solo mode: one AI plays all roles and produces the full round as one response."""
        cb("agent_start", agent=agent, round=round_num, role="guest")
        context = self.context_manager.build_context()
        prompt = self.prompt_loader.render('solo_roundtable', {
            'topic': self._topic,
            'round_num': str(round_num),
            'moderator_question': moderator_question,
            'context': context,
        })
        response = await self.cli_caller.call(agent, prompt)
        speeches[agent] = response
        cb("agent_response", agent=agent, round=round_num, content=response, role="guest")

    async def _run_moderator(
        self, round_num: int, moderator: str,
        speeches: Dict[str, str], cb: Callable
    ):
        """Run the moderator summary. Returns (raw, parsed)."""
        cb("agent_start", agent=moderator, round=round_num, role="moderator")

        # Format speeches for moderator
        speech_lines = []
        for agent in self._speaking_order:
            if agent in speeches:
                speech_lines.append(f"[{agent.upper()}]\n{speeches[agent]}")
        round_speeches = '\n\n'.join(speech_lines)

        guests_list = "、".join(a.capitalize() for a in self._active_agents)
        guests_action_format = "\n".join(
            f"{a.capitalize()}：{{行动类型}} - {{具体说明}}" for a in self._active_agents
        )
        context = self.context_manager.build_context()
        prompt = self.prompt_loader.render('moderator', {
            'moderator_name': moderator.capitalize(),
            'context': context,
            'round_num': str(round_num),
            'round_speeches': round_speeches,
            'guests_list': guests_list,
            'guests_action_format': guests_action_format,
        })

        raw = await self.cli_caller.call(moderator, prompt)
        parsed = parse_moderator_output(raw)

        # Retry once if format fails
        if parsed is None:
            cb("status", message="主持人格式不符，重试...", state=self._state)
            raw = await self.cli_caller.call(moderator, prompt)
            parsed = parse_moderator_output(raw)

        if parsed:
            cb("agent_response", agent=moderator, round=round_num, content=raw, role="moderator")
            cb("moderator_output", moderator=moderator, round=round_num, parsed=parsed, raw=raw)
        else:
            cb("agent_response", agent=moderator, round=round_num, content=raw, role="moderator")
            cb("status", message="主持人格式仍不符，跳过综述", state=self._state)

        return raw, parsed

    async def _do_compression(self, cb: Callable) -> None:
        """Compress the oldest full round into summary."""
        round_to_compress = self.context_manager.get_round_to_compress()
        if not round_to_compress:
            return

        cb("status", message="压缩历史上下文中...", state=self._state)
        moderator = self.current_moderator
        round_content = self.context_manager.get_round_content_for_compression(round_to_compress)

        prompt = self.prompt_loader.render('compress', {
            'round_content': round_content
        })

        summary = await self.cli_caller.call(moderator, prompt)
        if summary.startswith('[无响应'):
            # Use a basic fallback summary
            summary = f"第{round_to_compress['round']}轮讨论（压缩失败，内容省略）"

        self.context_manager.apply_compression(summary)

    async def _deepen_current(self, cb: Callable) -> None:
        """Deepen the current discussion point without advancing round number."""
        if self._last_moderator_parsed is None:
            cb("status", message="没有当前矛盾点可深入", state=self._state)
            return

        self._state = self.STATE_RUNNING
        round_num = self._round_num
        moderator = self._get_moderator_for_round(round_num)

        cb("status", message=f"深入当前节点，轮{round_num}...", state=self._state)

        # Override action assignments to focus on 反驳/追问 — cycle through types
        deep_types = ['反驳', '追问', '挑战前提']
        action_assignments = {
            agent: {'type': deep_types[i % len(deep_types)],
                    'instruction': '围绕矛盾点深入探讨'}
            for i, agent in enumerate(self._speaking_order)
        }

        moderator_question = self._last_moderator_parsed.get('矛盾点', '请深入当前矛盾点')
        speeches: Dict[str, str] = {}

        # Use sequential speaking for deeper exploration
        await self._run_sequential_speeches(
            round_num, moderator, moderator_question,
            action_assignments, speeches, cb
        )

        # Don't run moderator summary for deep rounds, just show speeches
        self._state = self.STATE_WAITING
        cb("status",
           message=f"深入完毕 · 输入「可」继续下一轮，或继续「深入此节」",
           state=self._state)

    async def _handle_direct_question(self, user_input: str, cb: Callable) -> None:
        """Handle @agent question format."""
        match = re.match(r'^@(\w+)\s+(.*)', user_input, re.DOTALL)
        if not match:
            agents_hint = "/".join(self._active_agents)
            cb("status", message=f"格式错误，请用 @{agents_hint} 内容", state=self._state)
            return

        agent_name = match.group(1).lower()
        question = match.group(2).strip()

        if agent_name not in self.config.get('ais', {}):
            cb("status", message=f"未知 agent: {agent_name}", state=self._state)
            return

        self._state = self.STATE_RUNNING
        cb("agent_start", agent=agent_name, round=self._round_num, role="guest")
        cb("status", message=f"询问 {agent_name}...", state=self._state)

        context = self.context_manager.build_context()
        # Build a simple prompt for the direct question
        prompt = f"""你是 {agent_name.capitalize()}，参加 AI 圆桌讨论的嘉宾。

## 当前上下文
{context}

## 用户直接提问
{question}

请简洁直接地回答这个问题，200字以内："""

        response = await self.cli_caller.call(agent_name, prompt)
        cb("agent_response", agent=agent_name, round=self._round_num, content=response, role="guest")
        cb("side_response", agent=agent_name, content=response, question=question)

        self._state = self.STATE_WAITING
        cb("status",
           message=f"Session {self._session_id} · 轮{self._round_num} · 等待: 可/止/深入此节",
           state=self._state)

    async def _end_session(self, cb: Callable) -> None:
        """End the session with a summary."""
        self._state = self.STATE_RUNNING
        cb("status", message="生成总结...", state=self._state)

        # Generate final summary using context
        context = self.context_manager.build_context()
        moderator = self.current_moderator if self._round_num > 0 else self._moderator_rotation[0]

        summary_prompt = f"""你是 {moderator.capitalize()}，作为 AI 圆桌的主持人，请对整场讨论做最终总结。

## 完整讨论记录
{context}

## 任务
用300字以内总结：
1. 各方核心立场差异
2. 达成的共识（如有）
3. 未解决的核心矛盾
4. 讨论的最大价值

请直接输出总结："""

        summary = await self.cli_caller.call(moderator, summary_prompt)

        # Append summary to MD and get path
        md_path = None
        try:
            self.history.append_deep_summary(self._session_id, summary)
            md_path = self.history.export_md(self._session_id)
        except Exception:
            pass

        self._state = self.STATE_ENDED

        end_msg = summary
        if md_path:
            end_msg += f"\n\n[会话已保存至: {md_path}]"

        cb("session_end", summary=end_msg)
        cb("status", message="会话已结束", state=self._state)
