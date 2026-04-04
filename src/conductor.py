"""
Conductor 模式：由一个 AI 主导，将问题分解分配给其他 AI，最终整合结果。

三个阶段：
  Phase 1 — Plan:      Conductor 分析问题，输出 JSON 任务分配
  Phase 2 — Execute:   Workers 并行执行各自子任务（streaming）
  Phase 3 — Synthesize: Conductor 整合所有结果，输出最终答案
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional


class ConductorMode:
    def __init__(self, config: dict, cli_caller, prompt_loader,
                 history=None, conductor_file: Optional[Path] = None,
                 active_agents: Optional[List[str]] = None,
                 conductor_agent: Optional[str] = None):
        self.config = config
        self.cli_caller = cli_caller
        self.prompts = prompt_loader
        self.history = history
        self.conductor_file = conductor_file

        all_agents = active_agents if active_agents is not None else [
            k for k, v in config.get('ais', {}).items() if v.get('enabled', True)
        ]

        # 确定指挥 AI：优先显式指定，其次配置默认，最后 fallback 到第一个
        default = config.get('conductor', {}).get('default_conductor', '')
        if conductor_agent and conductor_agent in all_agents:
            self.conductor = conductor_agent
        elif default and default in all_agents:
            self.conductor = default
        else:
            self.conductor = all_agents[0] if all_agents else 'claude'

        self.workers: List[str] = [a for a in all_agents if a != self.conductor]
        self.history_local: List[Dict[str, Any]] = []

    async def run(self, question: str, cb: Callable) -> None:
        """执行完整 Conductor 流程：规划 → 并行执行 → 整合。"""
        if not self.workers:
            cb("error", message="Conductor 模式需要至少 2 个活跃 AI")
            return

        # Phase 1
        assignments = await self._phase_plan(question, cb)

        # Phase 2
        worker_responses = await self._phase_execute(question, assignments, cb)

        # Phase 3
        synthesis = await self._phase_synthesize(question, assignments, worker_responses, cb)

        # 记录本轮历史
        entry = {
            "question":         question,
            "conductor":        self.conductor,
            "assignments":      assignments,
            "worker_responses": worker_responses,
            "synthesis":        synthesis,
        }
        self.history_local.append(entry)

        # 懒创建历史文件（首条消息时）
        if self.history and self.conductor_file is None:
            try:
                _, self.conductor_file = self.history.new_conductor_session()
                cb("conductor_file_ready", conductor_file=self.conductor_file)
            except Exception as e:
                cb("error", message=f"历史文件创建失败: {e}")

        if self.history and self.conductor_file:
            try:
                self.history.append_conductor_entry(entry, path=self.conductor_file)
            except Exception as e:
                cb("error", message=f"历史写入失败: {e}")

        # 首条消息自动生成标题
        if len(self.history_local) == 1:
            asyncio.create_task(self._generate_title(question, cb))

    # ── Phase 1: Plan ─────────────────────────────────────────────────────────

    async def _phase_plan(self, question: str, cb: Callable) -> Dict[str, str]:
        cb("conductor_planning", conductor=self.conductor)

        prompt = self.prompts.render("conductor_plan", {
            "conductor_name": self.conductor.upper(),
            "workers":        "、".join(w.upper() for w in self.workers),
            "worker_list":    ", ".join(self.workers),
            "question":       question,
        })

        chunks: List[str] = []

        def on_chunk(chunk: str):
            chunks.append(chunk)
            cb("conductor_plan_chunk", chunk=chunk)

        def on_idle(elapsed: float):
            cb("agent_idle", agent=self.conductor, elapsed=elapsed)

        def on_stderr(line: str):
            cb("agent_stderr", agent=self.conductor, line=line)

        raw = await self.cli_caller.call_stream(
            self.conductor, prompt, on_chunk, on_idle=on_idle, on_stderr=on_stderr
        )

        full = raw or "".join(chunks)
        assignments = self._parse_assignments(full)

        if assignments:
            cb("conductor_plan_ready", conductor=self.conductor, assignments=assignments)
        else:
            cb("conductor_plan_failed", message="方案解析失败，将原始问题发给所有 AI")
            assignments = {w: question for w in self.workers}

        return assignments

    def _parse_assignments(self, text: str) -> Optional[Dict[str, str]]:
        """从 Conductor 输出中提取 JSON assignments，失败返回 None。"""
        # 去掉可能的 markdown 代码块
        text = re.sub(r'```[a-z]*\n?', '', text).strip()
        text = re.sub(r'\n?```', '', text).strip()

        def _extract(s: str) -> Optional[Dict[str, str]]:
            try:
                data = json.loads(s)
                a = data.get("assignments", {})
                if not a:
                    return None
                result = {k.lower(): v for k, v in a.items() if k.lower() in self.workers}
                return result if result else None
            except (json.JSONDecodeError, ValueError, AttributeError):
                return None

        # 尝试整体解析
        result = _extract(text)
        if result:
            return result

        # 尝试从文本中提取 JSON 块
        m = re.search(r'\{[\s\S]*?"assignments"[\s\S]*?\}', text)
        if m:
            return _extract(m.group())

        return None

    # ── Phase 2: Execute ──────────────────────────────────────────────────────

    async def _phase_execute(self, question: str,
                              assignments: Dict[str, str],
                              cb: Callable) -> Dict[str, str]:
        responses: Dict[str, str] = {}

        async def ask_worker(agent: str):
            task = assignments.get(agent, question)
            cb("agent_start", agent=agent, role="conductor_worker")

            prompt = self.prompts.render("conductor_worker", {
                "agent_name":     agent.upper(),
                "conductor_name": self.conductor.upper(),
                "question":       question,
                "assigned_task":  task,
            })

            def on_chunk(chunk: str):
                cb("agent_chunk", agent=agent, chunk=chunk)

            def on_idle(elapsed: float):
                cb("agent_idle", agent=agent, elapsed=elapsed)

            def on_stderr(line: str):
                cb("agent_stderr", agent=agent, line=line)

            response = await self.cli_caller.call_stream(
                agent, prompt, on_chunk, on_idle=on_idle, on_stderr=on_stderr
            )
            responses[agent] = response or ""
            cb("agent_response", agent=agent, content=responses[agent],
               role="conductor_worker", task=task)

        await asyncio.gather(*[ask_worker(w) for w in self.workers])
        return responses

    # ── Phase 3: Synthesize ───────────────────────────────────────────────────

    async def _phase_synthesize(self, question: str,
                                 assignments: Dict[str, str],
                                 worker_responses: Dict[str, str],
                                 cb: Callable) -> str:
        cb("conductor_synthesizing", conductor=self.conductor)

        # 构建 workers 摘要，标注无响应的 worker
        parts = []
        for agent in self.workers:
            task = assignments.get(agent, "原始问题")
            resp = worker_responses.get(agent, "")
            if not resp or resp.startswith("[无响应"):
                parts.append(f"[{agent.upper()} — 子任务: {task}]\n（无响应）")
            else:
                parts.append(f"[{agent.upper()} — 子任务: {task}]\n{resp}")
        workers_summary = "\n\n".join(parts)

        prompt = self.prompts.render("conductor_synthesize", {
            "conductor_name": self.conductor.upper(),
            "question":       question,
            "workers_summary": workers_summary,
        })

        chunks: List[str] = []

        def on_chunk(chunk: str):
            chunks.append(chunk)
            cb("conductor_synthesis_chunk", chunk=chunk)

        def on_idle(elapsed: float):
            cb("agent_idle", agent=self.conductor, elapsed=elapsed)

        def on_stderr(line: str):
            cb("agent_stderr", agent=self.conductor, line=line)

        result = await self.cli_caller.call_stream(
            self.conductor, prompt, on_chunk, on_idle=on_idle, on_stderr=on_stderr
        )

        synthesis = result or "".join(chunks)
        cb("conductor_done", conductor=self.conductor, synthesis=synthesis)
        return synthesis

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _generate_title(self, question: str, cb: Callable) -> None:
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
                cb("session_title", title=title, quick_file=self.conductor_file)
        except Exception:
            pass
