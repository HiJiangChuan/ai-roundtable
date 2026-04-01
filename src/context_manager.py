"""
Context Manager - Manages the three-layer context structure:
[议题摘要] ≤50字，永久保留
[历史摘要] 第1~N-3轮压缩版（每轮≤80字）
[完整记录] 最近3轮完整对话
"""
from typing import Dict, List, Any, Optional


class ContextManager:
    def __init__(self, full_rounds_kept: int = 3, compress_max: int = 80):
        self.full_rounds_kept = full_rounds_kept
        self.compress_max = compress_max

        self.topic_summary: str = ""
        self.compressed_rounds: List[Dict[str, Any]] = []  # {round: int, summary: str}
        self.full_rounds: List[Dict[str, Any]] = []  # recent full round data
        self._pending_compression: Optional[Dict[str, Any]] = None
        self._quick_context: Optional[Dict[str, Any]] = None

    def set_topic(self, topic: str) -> None:
        self.topic_summary = topic[:100] if len(topic) > 100 else topic

    def set_quick_context(self, quick_entry: dict) -> None:
        """将快问的最后一次问答作为初始上下文"""
        self._quick_context = quick_entry

    def add_round(self, round_data: Dict[str, Any]) -> None:
        """
        Add a completed round to the context.
        round_data: {round: int, speeches: {agent: str}, moderator: str,
                     moderator_raw: str, moderator_parsed: dict}
        """
        self.full_rounds.append(round_data)

        # If we exceed full_rounds_kept, mark oldest for compression
        if len(self.full_rounds) > self.full_rounds_kept:
            self._pending_compression = self.full_rounds[0]

    def needs_compression(self) -> bool:
        """Check if there's a round waiting to be compressed."""
        return self._pending_compression is not None

    def get_round_to_compress(self) -> Optional[Dict[str, Any]]:
        """Get the round data that needs compression."""
        return self._pending_compression

    def apply_compression(self, summary: str) -> None:
        """Apply compression result and remove the full round from memory."""
        if self._pending_compression is not None:
            self.compressed_rounds.append({
                'round': self._pending_compression['round'],
                'summary': summary[:self.compress_max]
            })
            self.full_rounds.pop(0)
            self._pending_compression = None

    def _format_round_content(self, round_data: Dict[str, Any]) -> str:
        """Format a round's data as readable text."""
        lines = [f"=== 第{round_data['round']}轮 ==="]

        speeches = round_data.get('speeches', {})
        for agent, content in speeches.items():
            lines.append(f"[{agent.upper()}] {content}")

        moderator_parsed = round_data.get('moderator_parsed', {})
        if moderator_parsed:
            lines.append(f"\n[主持人综述]")
            if '矛盾点' in moderator_parsed:
                lines.append(f"【矛盾点】{moderator_parsed['矛盾点']}")
            if '下一问' in moderator_parsed:
                lines.append(f"【下一问】{moderator_parsed['下一问']}")
            if '本轮摘要' in moderator_parsed:
                lines.append(f"【本轮摘要】{moderator_parsed['本轮摘要']}")
        elif round_data.get('moderator_raw'):
            lines.append(f"\n[主持人综述]\n{round_data['moderator_raw']}")

        return '\n'.join(lines)

    def get_round_content_for_compression(self, round_data: Dict[str, Any]) -> str:
        """Get formatted round content for the compress prompt."""
        return self._format_round_content(round_data)

    def build_context(self) -> str:
        """Build the full context string for use in prompts."""
        parts = []

        # Layer 1: Topic summary
        if self.topic_summary:
            parts.append(f"[议题摘要]\n{self.topic_summary}")

        # Quick context (if any)
        if self._quick_context:
            qc = self._quick_context
            lines = [f"[快问背景]\n原始问题：{qc.get('question', '')}"]
            for ag, resp in qc.get('responses', {}).items():
                lines.append(f"[{ag.upper()}] {resp[:300]}")
            parts.append("\n".join(lines))

        # Layer 2: Compressed history
        if self.compressed_rounds:
            history_lines = ["[历史摘要]"]
            for item in self.compressed_rounds:
                history_lines.append(f"第{item['round']}轮：{item['summary']}")
            parts.append('\n'.join(history_lines))

        # Layer 3: Full recent rounds
        if self.full_rounds:
            full_lines = ["[完整记录]"]
            for round_data in self.full_rounds:
                full_lines.append(self._format_round_content(round_data))
            parts.append('\n'.join(full_lines))

        return '\n\n'.join(parts) if parts else "(暂无上下文)"
