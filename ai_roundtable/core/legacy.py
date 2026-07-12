"""旧版（重写前）Markdown 会话文件的只读解析。

旧版没有 JSON 真相源，历史数据只存在于 Obsidian Markdown 里，
这里保留当年的 regex 解析逻辑，让用户的既有会话仍可在历史列表中查看/续聊。
仅用于读旧文件；新会话一律走 store.py 的 JSON。
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# 旧版硬编码的三个 agent 的 callout 图标（旧文件里只可能出现这三个）
_LEGACY_ICONS = {"claude": "🔵", "codex": "🟡", "agy": "🟢", "gemini": "🟣"}


def parse_quick_meta(path: Path) -> Optional[Dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8")
        m = re.search(r"## \d{2}:\d{2} — (.+)", content)
        title = m.group(1).strip() if m else path.stem
        count = len(re.findall(r"^## \d{2}:\d{2}", content, re.MULTILINE))
        return {
            "type": "quick",
            "title": title[:30],
            "file": path,
            "json_path": None,
            "date": path.parent.name,
            "entries": count,
            "mtime": path.stat().st_mtime,
        }
    except OSError:
        return None


def parse_deep_meta(path: Path) -> Optional[Dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8")
        m = re.search(r"^title: (.+)$", content, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem
        rounds = len(re.findall(r"^## Round \d+", content, re.MULTILINE))
        return {
            "type": "deep",
            "title": title[:30],
            "file": path,
            "json_path": None,
            "date": path.parent.name,
            "entries": rounds,
            "mtime": path.stat().st_mtime,
        }
    except OSError:
        return None


def load_quick_entries(path: Path, n: int = 3) -> List[Dict[str, Any]]:
    """从旧版 quick MD 文件解析最后 n 条问答。"""
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    sections = re.split(r"\n(?=## \d{2}:\d{2} — )", content)
    entries = []
    for section in sections:
        if not section.startswith("## "):
            continue
        q_match = re.search(r"\*\*Q:\*\* (.+?)(?=\n>)", section, re.DOTALL)
        if not q_match:
            continue
        question = q_match.group(1).strip()
        responses = {}
        for agent, icon in _LEGACY_ICONS.items():
            pattern = (rf"> \[!\w+\]\+ {re.escape(icon)} {agent.upper()}\n"
                       rf"((?:>.*\n?)*)")
            m = re.search(pattern, section, re.IGNORECASE)
            if m:
                body = re.sub(r"^> ?", "", m.group(1), flags=re.MULTILINE).strip()
                responses[agent] = body
        if question:
            entries.append({"question": question, "responses": responses})
    return entries[-n:]
