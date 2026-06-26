"""
History - Session persistence in JSON + Obsidian Markdown formats.

Quick mode : daily numbered files  (base/quick/2026-03-31-001.md)
Deep mode  : per-session file      (base/rounds/2026-03-31 topic.md)
Images     : base/attachments/img_xxx.png  →  ![[attachments/img.png]] in MD
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


AGENT_CALLOUT = {
    'claude': ('note',    '🔵'),
    'agy':    ('tip',     '🟢'),
    'codex':  ('warning', '🟡'),
}
SPEAKING_ORDER = ['claude', 'codex', 'agy']


def _callout(kind: str, title: str, body: str) -> str:
    lines = [f"> [!{kind}]+ {title}"]
    for line in body.splitlines():
        lines.append(f"> {line}" if line.strip() else ">")
    lines.append("")
    return "\n".join(lines)


def _md_image(text: str) -> str:
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
        self.quick_dir       = base / 'Quick Round'
        self.deep_dir        = base / 'Deep Round'
        self.attachments_dir = base / 'attachments'

        for d in (self.quick_dir, self.deep_dir, self.attachments_dir):
            d.mkdir(parents=True, exist_ok=True)

        self._sessions: Dict[str, Dict[str, Any]] = {}

    # ── Quick mode ────────────────────────────────────────────────────────────

    def new_quick_session(self) -> Tuple[str, Path]:
        """Create a new numbered quick session file. Returns (session_id, path)."""
        today = datetime.now().strftime('%Y-%m-%d')
        day_dir = self.quick_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        # Find the highest numeric prefix among existing files to avoid collisions
        max_num = 0
        for f in day_dir.glob('*.md'):
            stem = f.stem.split('-')[0]
            if stem.isdigit():
                max_num = max(max_num, int(stem))
        num = max_num + 1
        session_id = f"{num:03d}"
        path = day_dir / f"{session_id}.md"
        self._write_quick_frontmatter(path, today, session_id)
        return session_id, path

    def append_quick_entry(self, question: str, responses: Dict[str, str],
                           path: Optional[Path] = None) -> None:
        if path is None:
            return

        now     = datetime.now().strftime('%H:%M')
        short_q = question[:30].replace('\n', ' ').strip()

        blocks = [f"\n## {now} — {short_q}\n", f"**Q:** {_md_image(question)}\n"]
        for agent in SPEAKING_ORDER:
            if agent not in responses:
                continue
            kind, icon = AGENT_CALLOUT[agent]
            blocks.append(_callout(kind, f"{icon} {agent.upper()}", _md_image(responses[agent])))
        blocks.append("---\n")

        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

    def append_quick_compare(self, responses: Dict[str, str],
                             path: Optional[Path] = None) -> None:
        if path is None or not path.exists():
            return

        now = datetime.now().strftime('%H:%M')
        blocks = [f"\n### {now} ↺ Compare\n"]
        for agent in SPEAKING_ORDER:
            if agent not in responses:
                continue
            kind, icon = AGENT_CALLOUT[agent]
            blocks.append(_callout(kind, f"{icon} {agent.upper()} critique",
                                   _md_image(responses[agent])))
        blocks.append("---\n")

        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

    def load_last_entries(self, path: Path, n: int = 3) -> List[Dict[str, Any]]:
        """Parse a quick session file and return last n Q&A entries."""
        if not path.exists():
            return []
        content = path.read_text(encoding='utf-8')

        # Split on ## HH:MM — title sections
        sections = re.split(r'\n(?=## \d{2}:\d{2} — )', content)
        entries = []

        for section in sections:
            if not section.startswith('## '):
                continue
            # Extract question
            q_match = re.search(r'\*\*Q:\*\* (.+?)(?=\n>)', section, re.DOTALL)
            if not q_match:
                continue
            question = q_match.group(1).strip()

            # Extract responses per agent
            responses = {}
            for agent in SPEAKING_ORDER:
                icon_map = {'claude': '🔵', 'codex': '🟡', 'agy': '🟢'}
                icon = icon_map[agent]
                pattern = rf'> \[!\w+\]\+ {re.escape(icon)} {agent.upper()}\n((?:>.*\n?)*)'
                m = re.search(pattern, section, re.IGNORECASE)
                if m:
                    body = re.sub(r'^> ?', '', m.group(1), flags=re.MULTILINE).strip()
                    responses[agent] = body

            if question:
                entries.append({'question': question, 'responses': responses})

        return entries[-n:]

    def get_sessions_for_modal(self) -> List[Dict[str, Any]]:
        """Scan quick/DATE/ and rounds/DATE/ dirs, return metadata list for history modal."""
        sessions = []

        # Quick sessions
        for md_file in sorted(self.quick_dir.glob('????-??-??/*.md'), reverse=True):
            meta = self._parse_quick_meta(md_file)
            if meta:
                sessions.append(meta)

        # Deep sessions
        for md_file in sorted(self.deep_dir.glob('????-??-??/*.md'), reverse=True):
            meta = self._parse_deep_meta(md_file)
            if meta:
                sessions.append(meta)

        # Filter out empty sessions, sort by date desc
        sessions = [s for s in sessions if s.get('entries', 0) > 0]
        sessions.sort(key=lambda x: x.get('mtime', 0), reverse=True)
        return sessions

    def _parse_quick_meta(self, path: Path) -> Optional[Dict]:
        try:
            content = path.read_text(encoding='utf-8')
            m = re.search(r'## \d{2}:\d{2} — (.+)', content)
            title = m.group(1).strip() if m else '空会话'
            count = len(re.findall(r'^## \d{2}:\d{2}', content, re.MULTILINE))
            # Date from parent directory name: quick/2026-03-31/001.md
            date_str = path.parent.name
            return {
                'type': 'rapid-fire',
                'title': title[:30],
                'file': path,
                'date': date_str,
                'entries': count,
                'mtime': path.stat().st_mtime,
            }
        except Exception:
            return None

    def _parse_deep_meta(self, path: Path) -> Optional[Dict]:
        try:
            content = path.read_text(encoding='utf-8')
            m = re.search(r'^title: (.+)$', content, re.MULTILINE)
            title = m.group(1).strip() if m else path.stem
            rounds = len(re.findall(r'^## Round \d+', content, re.MULTILINE))
            # Date from parent directory name: rounds/2026-03-31/topic.md
            date_str = path.parent.name
            return {
                'type': 'deep-dive',
                'title': title[:30],
                'file': path,
                'date': date_str,
                'entries': rounds,
                'mtime': path.stat().st_mtime,
            }
        except Exception:
            return None

    def _write_quick_frontmatter(self, path: Path, today: str, session_id: str) -> None:
        path.write_text(
            f"---\ndate: {today}\nsession: {session_id}\ntype: rapid-fire\n"
            f"tags:\n  - ai-roundtable\n  - rapid-fire\n---\n",
            encoding='utf-8',
        )

    # ── Deep Round mode ───────────────────────────────────────────────────────

    def new_session(self, topic: str) -> str:
        ts    = datetime.now().strftime('%Y%m%d_%H%M%S')
        sid   = f"session_{ts}"
        today = datetime.now().strftime('%Y-%m-%d')

        day_dir = self.deep_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(day_dir.glob('*.md'))
        num = len(existing) + 1
        md_path = day_dir / f"{num:03d}.md"

        self._sessions[sid] = {
            'session_id': sid,
            'topic':      topic,
            'started_at': datetime.now().isoformat(),
            'rounds':     [],
            'md_path':    str(md_path),
        }
        self._write_deep_header(md_path, topic, today)
        return sid

    def add_round(self, session_id: str, round_data: Dict[str, Any]) -> None:
        if session_id not in self._sessions:
            return
        self._sessions[session_id]['rounds'].append(round_data)
        md_path = Path(self._sessions[session_id]['md_path'])
        self._append_deep_round(md_path, round_data)

    def append_deep_summary(self, session_id: str, summary: str) -> None:
        if session_id not in self._sessions:
            return
        md_path = Path(self._sessions[session_id]['md_path'])
        with open(md_path, 'a', encoding='utf-8') as f:
            f.write(f"\n---\n\n## Summary\n\n{_md_image(summary)}\n")

    def export_md(self, session_id: str) -> Path:
        if session_id not in self._sessions:
            raise ValueError(f"Session not found: {session_id}")
        return Path(self._sessions[session_id]['md_path'])

    # ── Internals ─────────────────────────────────────────────────────────────

    def _write_deep_header(self, path: Path, topic: str, today: str) -> None:
        path.write_text(
            f"---\ntitle: {topic}\ndate: {today}\ntype: deep-dive\nrounds: 0\n"
            f"tags:\n  - ai-roundtable\n  - deep-dive\n---\n\n# {topic}\n\n",
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
            blocks.append(_callout('abstract',
                                   f"{mod_icon} Moderator ({moderator.upper()})", body))
        elif raw:
            blocks.append(_callout('abstract', '🎙 Moderator', raw))

        blocks.append("---\n")

        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(blocks))

        try:
            content = path.read_text(encoding='utf-8')
            content = re.sub(r'^rounds: \d+', f'rounds: {rnd}', content,
                             count=1, flags=re.MULTILINE)
            path.write_text(content, encoding='utf-8')
        except Exception:
            pass

