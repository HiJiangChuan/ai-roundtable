"""Deep Round 的三层上下文结构：

[议题摘要] ≤100字，永久保留
[历史摘要] 更早轮次的压缩版（每轮≤compress_max字）
[完整记录] 最近 full_rounds_kept 轮完整对话

另有 [快问背景]（从 Quick Round 升级时注入）与 [用户插话]（讨论中用户补充，全文保留）。
"""
from typing import Any, Dict, List, Optional


class ContextManager:
    def __init__(self, full_rounds_kept: int = 3, compress_max: int = 80):
        self.full_rounds_kept = full_rounds_kept
        self.compress_max = compress_max

        self.topic_summary: str = ""
        self.compressed_rounds: List[Dict[str, Any]] = []  # {round, summary}
        self.full_rounds: List[Dict[str, Any]] = []
        self.user_notes: List[str] = []
        self._pending_compression: Optional[Dict[str, Any]] = None
        self._quick_context: Optional[Dict[str, Any]] = None

    def set_topic(self, topic: str) -> None:
        self.topic_summary = topic[:100]

    def add_user_note(self, note: str) -> None:
        """用户插话：全文注入上下文（上限 500 字防爆），不再截断塞进议题摘要。"""
        note = note.strip()
        if note:
            self.user_notes.append(note[:500])

    def set_quick_context(self, quick_entry: Dict[str, Any]) -> None:
        """将快问的最后一次问答作为初始上下文。"""
        self._quick_context = quick_entry

    def add_round(self, round_data: Dict[str, Any]) -> None:
        self.full_rounds.append(round_data)
        if len(self.full_rounds) > self.full_rounds_kept:
            self._pending_compression = self.full_rounds[0]

    def needs_compression(self) -> bool:
        return self._pending_compression is not None

    def get_round_to_compress(self) -> Optional[Dict[str, Any]]:
        return self._pending_compression

    def apply_compression(self, summary: str) -> None:
        if self._pending_compression is not None:
            self.compressed_rounds.append({
                "round": self._pending_compression["round"],
                "summary": summary[:self.compress_max],
            })
            self.full_rounds.pop(0)
            self._pending_compression = None

    def format_round(self, round_data: Dict[str, Any]) -> str:
        lines = [f"=== 第{round_data['round']}轮 ==="]
        for agent, content in round_data.get("speeches", {}).items():
            lines.append(f"[{agent.upper()}] {content}")
        parsed = round_data.get("moderator_parsed") or {}
        if parsed:
            lines.append("\n[主持人综述]")
            for key in ("矛盾点", "下一问", "本轮摘要"):
                if key in parsed:
                    lines.append(f"【{key}】{parsed[key]}")
        elif round_data.get("moderator_raw"):
            lines.append(f"\n[主持人综述]\n{round_data['moderator_raw']}")
        return "\n".join(lines)

    def build_context(self) -> str:
        parts = []
        if self.topic_summary:
            parts.append(f"[议题摘要]\n{self.topic_summary}")

        if self._quick_context:
            qc = self._quick_context
            lines = [f"[快问背景]\n原始问题：{qc.get('question', '')}"]
            for agent, resp in qc.get("responses", {}).items():
                lines.append(f"[{agent.upper()}] {resp[:300]}")
            parts.append("\n".join(lines))

        if self.user_notes:
            parts.append("[用户插话]\n" + "\n".join(f"- {n}" for n in self.user_notes))

        if self.compressed_rounds:
            lines = ["[历史摘要]"]
            for item in self.compressed_rounds:
                lines.append(f"第{item['round']}轮：{item['summary']}")
            parts.append("\n".join(lines))

        if self.full_rounds:
            lines = ["[完整记录]"]
            for round_data in self.full_rounds:
                lines.append(self.format_round(round_data))
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else "(暂无上下文)"
