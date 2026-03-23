"""
History - Manages session persistence in JSON and Markdown formats.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class History:
    def __init__(self, config: Dict[str, Any], project_root: Optional[Path] = None):
        history_cfg = config.get('history', {})
        save_dir = history_cfg.get('save_dir', './history')
        if project_root and not Path(save_dir).is_absolute():
            self.save_dir = Path(project_root) / save_dir
        else:
            self.save_dir = Path(os.path.expanduser(save_dir))
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.formats = history_cfg.get('format', ['json', 'md'])
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def new_session(self, topic: str) -> str:
        """Create a new session and return the session_id."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        session_id = f"session_{ts}"
        self._sessions[session_id] = {
            'session_id': session_id,
            'topic': topic,
            'started_at': datetime.now().isoformat(),
            'rounds': []
        }
        self.save(session_id, self._sessions[session_id])
        return session_id

    def add_round(self, session_id: str, round_data: Dict[str, Any]) -> None:
        """Add round data to the session."""
        if session_id not in self._sessions:
            return
        self._sessions[session_id]['rounds'].append(round_data)
        self.save(session_id, self._sessions[session_id])

    def export_md(self, session_id: str) -> Path:
        """Export session as Markdown file. Returns the file path."""
        if session_id not in self._sessions:
            raise ValueError(f"Session not found: {session_id}")

        data = self._sessions[session_id]
        md_path = self.save_dir / f"{session_id}.md"

        lines = [
            f"# AI 圆桌 · {data['topic']}",
            f"",
            f"**Session ID:** {session_id}",
            f"**开始时间:** {data.get('started_at', 'unknown')}",
            f"",
            "---",
            ""
        ]

        for round_data in data.get('rounds', []):
            round_num = round_data.get('round', '?')
            lines.append(f"## 第{round_num}轮")
            lines.append("")

            speeches = round_data.get('speeches', {})
            for agent, content in speeches.items():
                emoji = {'claude': '🔵', 'gemini': '🟢', 'codex': '🟡'}.get(agent, '🔸')
                lines.append(f"### {emoji} {agent.upper()}")
                lines.append("")
                lines.append(content)
                lines.append("")

            moderator_parsed = round_data.get('moderator_parsed', {})
            moderator = round_data.get('moderator', '')
            if moderator_parsed:
                emoji = {'claude': '🔵', 'gemini': '🟢', 'codex': '🟡'}.get(moderator, '🎙')
                lines.append(f"### {emoji} 主持人综述（{moderator.upper()}）")
                lines.append("")
                for key in ['矛盾点', '下一问', '行动分配', '本轮摘要']:
                    if key in moderator_parsed:
                        lines.append(f"**【{key}】**")
                        lines.append(moderator_parsed[key])
                        lines.append("")
            elif round_data.get('moderator_raw'):
                lines.append(f"### 🎙 主持人综述")
                lines.append("")
                lines.append(round_data['moderator_raw'])
                lines.append("")

            lines.append("---")
            lines.append("")

        md_path.write_text('\n'.join(lines), encoding='utf-8')
        return md_path

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        """Save session data to JSON."""
        if 'json' in self.formats:
            json_path = self.save_dir / f"{session_id}.json"
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
