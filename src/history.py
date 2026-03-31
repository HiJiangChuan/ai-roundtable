"""
History - Session persistence in JSON + Obsidian Markdown formats.

Quick mode : daily file  (base/quick/2026-03-31.md), append per entry
Deep mode  : per-session file (base/deep/2026-03-31 topic.md), append per round
Images     : base/attachments/img_xxx.png  →  ![[attachments/img_xxx.png]] in MD
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


AGENT_CALLOUT = {
    'claude': ('note',    '🔵'),
    'gemini': ('tip',     '🟢'),
    'codex':  ('warning', '🟡'),
}
SPEAKING_ORDER = ['claude', 'codex', 'gemini']


def _callout(kind: str, title: str, body: str) -> str:
    """Render an Obsidian callout block."""
    lines = [f"> [!{kind}]+ {title}"]
    for line in body.splitlines():
        lines.append(f"> {line}" if line.strip() else ">")
    lines.append("")
    return "\n".join(lines)


def _md_image(text: str) -> str:
    """Convert [附件图片: /full/path/img.png] → ![[attachments/img.png]]"""
    return re.sub(
        r'\[附件图片: .+?/([^\s/\n]+)\]',
        lambda m: f"![[attachments/{m.group(1)}]]",
        text,
    )


class History:
    def __init__(self, config: Dict[str, Any], project_root: Optional[Path] = None):
        history_cfg = config.get('history', {})

        vault_raw = history_cfg.get('obsidian_vault', '').strip()
        if vault_raw:
            base = Path(os.path.expanduser(vault_raw)) / 'ai-roundtable'
        else:
            base = Path(os.path.expanduser('~/Documents/ai-roundtable'))

        self.base_dir        = base
        self.quick_dir       = base / 'quick'
        self.deep_dir        = base / 'rounds'
        self.attachments_dir = base / 'attachments'

        for d in (self.quick_dir, self.deep_dir, self.attachments_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Deep dive sessions: session_id → {topic, started_at, rounds, md_path}
        self._sessions: Dict[str, Dict[str, Any]] = {}

        # Quick mode state
        self._quick_path: Optional[Path] = None

    # ── Quick mode ────────────────────────────────────────────────────────────

    def init_quick_session(self) -> Path:
        """Open (or create) today's quick file. Call once at TUI startup."""
        today = datetime.now().strftime('%Y-%m-%d')
        path = self._quick_file_path(today, force_new=False)
        if not path.exists():
            self._write_quick_frontmatter(path, today)
        self._quick_path = path
        return path

    def new_quick_file(self) -> Path:
        """Create a fresh quick file for today (triggered by Ctrl+N)."""
        today = datetime.now().strftime('%Y-%m-%d')
        path = self._quick_file_path(today, force_new=True)
        self._write_quick_frontmatter(path, today)
        self._quick_path = path
        return path

    def append_quick_entry(self, question: str, responses: Dict[str, str]) -> None:
        """Append one Q&A block to the current quick file."""
        if self._quick_path is None:
            self.init_quick_session()

        now     = datetime.now().strftime('%H:%M')
        short_q = question[:30].replace('\n', ' ').strip()

        blocks = [
            f"\n## {now} — {short_q}\n",
            f"**Q:** {_md_image(question)}\n",
        ]
        for agent in SPEAKING_ORDER:
            if agent not in responses:
                continue
            kind, icon = AGENT_CALLOUT[agent]
            blocks.append(_callout(kind, f"{icon} {agent.upper()}", _md_image(responses[agent])))
        blocks.append("---\n")

        with open(self._quick_path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

    def append_quick_compare(self, responses: Dict[str, str]) -> None:
        """Append an inter-critique block to the current quick file."""
        if not self._quick_path or not self._quick_path.exists():
            return

        now = datetime.now().strftime('%H:%M')
        blocks = [f"\n### {now} ↺ Compare\n"]
        for agent in SPEAKING_ORDER:
            if agent not in responses:
                continue
            kind, icon = AGENT_CALLOUT[agent]
            blocks.append(_callout(kind, f"{icon} {agent.upper()} critique", _md_image(responses[agent])))
        blocks.append("---\n")

        with open(self._quick_path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

    def _quick_file_path(self, today: str, force_new: bool) -> Path:
        base = self.quick_dir / f"{today}.md"
        if not force_new:
            return base
        for ch in 'bcdefghijklmnopqrstuvwxyz':
            p = self.quick_dir / f"{today}-{ch}.md"
            if not p.exists():
                return p
        return self.quick_dir / f"{today}-extra.md"

    def _write_quick_frontmatter(self, path: Path, today: str) -> None:
        path.write_text(
            f"---\ndate: {today}\ntype: quick\ntags:\n  - ai-roundtable\n  - quick\n---\n",
            encoding='utf-8',
        )

    # ── Deep Dive mode ────────────────────────────────────────────────────────

    def new_session(self, topic: str) -> str:
        """Create a new deep-dive session. Returns session_id."""
        ts    = datetime.now().strftime('%Y%m%d_%H%M%S')
        sid   = f"session_{ts}"
        today = datetime.now().strftime('%Y-%m-%d')

        safe_topic = re.sub(r'[\\/:*?"<>|]', '', topic)[:30].strip()
        md_path = self.deep_dir / f"{today} {safe_topic}.md"
        if md_path.exists():
            md_path = self.deep_dir / f"{today} {safe_topic} {ts[-6:]}.md"

        self._sessions[sid] = {
            'session_id': sid,
            'topic':      topic,
            'started_at': datetime.now().isoformat(),
            'rounds':     [],
            'md_path':    str(md_path),
        }
        self._write_deep_header(md_path, topic, today)
        self._save_json(sid)
        return sid

    def add_round(self, session_id: str, round_data: Dict[str, Any]) -> None:
        """Append round to in-memory state, JSON backup, and MD file (real-time)."""
        if session_id not in self._sessions:
            return
        self._sessions[session_id]['rounds'].append(round_data)
        md_path = Path(self._sessions[session_id]['md_path'])
        self._append_deep_round(md_path, round_data)
        self._save_json(session_id)

    def append_deep_summary(self, session_id: str, summary: str) -> None:
        """Append final summary section to the deep-dive MD file."""
        if session_id not in self._sessions:
            return
        md_path = Path(self._sessions[session_id]['md_path'])
        with open(md_path, 'a', encoding='utf-8') as f:
            f.write(f"\n---\n\n## Summary\n\n{_md_image(summary)}\n")

    def export_md(self, session_id: str) -> Path:
        """Return the MD path (already written in real-time)."""
        if session_id not in self._sessions:
            raise ValueError(f"Session not found: {session_id}")
        return Path(self._sessions[session_id]['md_path'])

    # kept for backward compat
    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        self._save_json(session_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _write_deep_header(self, path: Path, topic: str, today: str) -> None:
        path.write_text(
            f"---\ntitle: {topic}\ndate: {today}\ntype: deep\nrounds: 0\n"
            f"tags:\n  - ai-roundtable\n  - deep\n---\n\n# {topic}\n\n",
            encoding='utf-8',
        )

    def _append_deep_round(self, path: Path, round_data: Dict[str, Any]) -> None:
        rnd       = round_data.get('round', '?')
        speeches  = round_data.get('speeches', {})
        moderator = round_data.get('moderator', '')
        parsed    = round_data.get('moderator_parsed', {})
        raw       = round_data.get('moderator_raw', '')

        blocks = [f"\n## Round {rnd}\n"]

        for agent in SPEAKING_ORDER:
            if agent not in speeches:
                continue
            kind, icon = AGENT_CALLOUT[agent]
            blocks.append(_callout(kind, f"{icon} {agent.upper()}", _md_image(speeches[agent])))

        if parsed:
            mod_icon = AGENT_CALLOUT.get(moderator, ('abstract', '🎙'))[1]
            body = '\n'.join(
                f"**{k}：** {parsed[k]}"
                for k in ['矛盾点', '下一问', '行动分配', '本轮摘要']
                if k in parsed
            )
            blocks.append(_callout('abstract', f"{mod_icon} Moderator ({moderator.upper()})", body))
        elif raw:
            blocks.append(_callout('abstract', '🎙 Moderator', raw))

        blocks.append("---\n")

        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

        try:
            content = path.read_text(encoding='utf-8')
            content = re.sub(r'^rounds: \d+', f'rounds: {rnd}', content, count=1, flags=re.MULTILINE)
            path.write_text(content, encoding='utf-8')
        except Exception:
            pass

    def _save_json(self, session_id: str) -> None:
        data = {k: v for k, v in self._sessions[session_id].items() if k != 'md_path'}
        (self.base_dir / f"{session_id}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )
