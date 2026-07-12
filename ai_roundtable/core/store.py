"""会话持久化。

真相源：~/.local/share/ai-roundtable/sessions/*.json（原子写入）。
导出视图：Obsidian vault 里的 Markdown（callout 格式与旧版字节兼容），只写不读。
旧版纯 MD 会话通过 core.legacy 只读接入历史列表。

目录布局（vault 侧，与旧版一致）：
  <base>/Quick Round/YYYY-MM-DD/NNN[-标题].md
  <base>/Deep Round/YYYY-MM-DD/NNN.md
  <base>/attachments/img_*.png
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from . import legacy

# 内置 agent 的 callout 类型兜底；未知 agent 从循环里按序取
_CALLOUT_CYCLE = ["note", "tip", "warning", "info", "quote", "example"]
_KNOWN_CALLOUTS = {"claude": "note", "agy": "tip", "codex": "warning",
                   "kimi": "info"}


def _callout(kind: str, title: str, body: str) -> str:
    lines = [f"> [!{kind}]+ {title}"]
    for line in body.splitlines():
        lines.append(f"> {line}" if line.strip() else ">")
    lines.append("")
    return "\n".join(lines)


def _md_image(text: str) -> str:
    return re.sub(
        r"\[附件图片: .+?/([^\s/\n]+)\]",
        lambda m: f"![[attachments/{m.group(1)}]]",
        text,
    )


def _yaml_scalar(value: str) -> str:
    """把用户文本安全地放进 frontmatter 一行（冒号/引号/换行都不炸）。"""
    dumped = yaml.safe_dump({"title": value}, allow_unicode=True,
                            default_flow_style=False, width=10 ** 6)
    return dumped.strip()


def _next_number(day_dir: Path) -> int:
    """目录内下一个编号：扫描既有数字前缀取 max+1，删过文件也不会撞号。"""
    max_num = 0
    if day_dir.exists():
        for f in day_dir.glob("*.md"):
            stem = f.stem.split("-")[0]
            if stem.isdigit():
                max_num = max(max_num, int(stem))
    return max_num + 1


@dataclass
class SessionRecord:
    id: str
    type: str                      # 'quick' | 'deep'
    created: str                   # ISO 时间
    title: str
    md_path: Path
    json_path: Path
    data: Dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self, config: Dict[str, Any], sessions_dir: Path):
        history_cfg = config.get("history") or {}
        vault_raw = (history_cfg.get("obsidian_vault") or "").strip()
        if vault_raw:
            base = Path(os.path.expanduser(vault_raw)) / "ai-roundtable"
        else:
            base = Path(os.path.expanduser("~/Documents/ai-roundtable"))

        self.base_dir = base
        self.quick_dir = base / "Quick Round"
        self.deep_dir = base / "Deep Round"
        self.attachments_dir = base / "attachments"
        self.sessions_dir = Path(sessions_dir)
        for d in (self.quick_dir, self.deep_dir, self.attachments_dir,
                  self.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)

        ais = config.get("ais") or {}
        self._agent_order = list(ais.keys())
        self._styles: Dict[str, tuple] = {}
        for i, (name, cfg) in enumerate(ais.items()):
            cfg = cfg or {}
            kind = cfg.get("callout") or _KNOWN_CALLOUTS.get(
                name, _CALLOUT_CYCLE[i % len(_CALLOUT_CYCLE)])
            icon = cfg.get("icon") or "⚪"
            self._styles[name] = (kind, icon)

    # ── 通用 ─────────────────────────────────────────────────────────────────

    def _agent_style(self, agent: str) -> tuple:
        return self._styles.get(agent, ("note", "⚪"))

    def _ordered_agents(self, responses: Dict[str, str]) -> List[str]:
        ordered = [a for a in self._agent_order if a in responses]
        ordered += [a for a in responses if a not in ordered]
        return ordered

    def _write_json(self, rec: SessionRecord) -> None:
        payload = {
            "id": rec.id,
            "type": rec.type,
            "created": rec.created,
            "title": rec.title,
            "md_path": str(rec.md_path),
            "data": rec.data,
        }
        tmp = rec.json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(rec.json_path)

    def _new_id(self, kind: str) -> str:
        base = f"{kind}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        sid = base
        i = 1
        while (self.sessions_dir / f"{sid}.json").exists():
            i += 1
            sid = f"{base}_{i}"
        return sid

    def _append_md(self, path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    # ── Quick ────────────────────────────────────────────────────────────────

    def create_quick(self) -> SessionRecord:
        today = datetime.now().strftime("%Y-%m-%d")
        day_dir = self.quick_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        num = _next_number(day_dir)
        md_path = day_dir / f"{num:03d}.md"
        md_path.write_text(
            f"---\ndate: {today}\nsession: {num:03d}\ntype: rapid-fire\n"
            f"tags:\n  - ai-roundtable\n  - rapid-fire\n---\n",
            encoding="utf-8",
        )
        sid = self._new_id("quick")
        rec = SessionRecord(
            id=sid, type="quick", created=datetime.now().isoformat(),
            title="", md_path=md_path,
            json_path=self.sessions_dir / f"{sid}.json",
            data={"events": []},
        )
        self._write_json(rec)
        return rec

    def adopt_legacy_quick(self, md_path: Path, title: str,
                           entries: List[Dict[str, Any]]) -> SessionRecord:
        """续聊旧版 MD 会话：建 JSON 记录接管该文件，预置已加载的问答。"""
        sid = self._new_id("quick")
        rec = SessionRecord(
            id=sid, type="quick", created=datetime.now().isoformat(),
            title=title, md_path=Path(md_path),
            json_path=self.sessions_dir / f"{sid}.json",
            data={"events": [{"kind": "qa", **e} for e in entries]},
        )
        self._write_json(rec)
        return rec

    def append_quick_entry(self, rec: SessionRecord, question: str,
                           responses: Dict[str, str]) -> None:
        now = datetime.now().strftime("%H:%M")
        rec.data["events"].append({
            "kind": "qa", "time": now,
            "question": question, "responses": responses,
        })
        self._write_json(rec)

        short_q = question[:30].replace("\n", " ").strip()
        blocks = [f"\n## {now} — {short_q}\n", f"**Q:** {_md_image(question)}\n"]
        for agent in self._ordered_agents(responses):
            kind, icon = self._agent_style(agent)
            blocks.append(_callout(kind, f"{icon} {agent.upper()}",
                                   _md_image(responses[agent])))
        blocks.append("---\n")
        self._append_md(rec.md_path, "\n".join(blocks))

    def append_quick_compare(self, rec: SessionRecord,
                             responses: Dict[str, str]) -> None:
        now = datetime.now().strftime("%H:%M")
        rec.data["events"].append({
            "kind": "compare", "time": now, "responses": responses,
        })
        self._write_json(rec)

        blocks = [f"\n### {now} ↺ Compare\n"]
        for agent in self._ordered_agents(responses):
            kind, icon = self._agent_style(agent)
            blocks.append(_callout(kind, f"{icon} {agent.upper()} critique",
                                   _md_image(responses[agent])))
        blocks.append("---\n")
        self._append_md(rec.md_path, "\n".join(blocks))

    def set_quick_title(self, rec: SessionRecord, title: str) -> None:
        """记录标题；纯数字命名的文件同步改名 001.md → 001-标题.md。"""
        rec.title = title
        if rec.md_path.stem.isdigit():
            new_path = rec.md_path.parent / f"{rec.md_path.stem}-{title}.md"
            try:
                rec.md_path.rename(new_path)
                rec.md_path = new_path
            except OSError:
                pass
        self._write_json(rec)

    # ── Deep ─────────────────────────────────────────────────────────────────

    def create_deep(self, topic: str) -> SessionRecord:
        today = datetime.now().strftime("%Y-%m-%d")
        day_dir = self.deep_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        num = _next_number(day_dir)
        md_path = day_dir / f"{num:03d}.md"

        heading = topic.replace("\n", " ").strip()
        md_path.write_text(
            f"---\n{_yaml_scalar(topic)}\ndate: {today}\ntype: deep-dive\n"
            f"rounds: 0\ntags:\n  - ai-roundtable\n  - deep-dive\n---\n\n"
            f"# {heading}\n\n",
            encoding="utf-8",
        )
        sid = self._new_id("deep")
        rec = SessionRecord(
            id=sid, type="deep", created=datetime.now().isoformat(),
            title=topic[:30], md_path=md_path,
            json_path=self.sessions_dir / f"{sid}.json",
            data={"topic": topic, "rounds": [], "summary": None},
        )
        self._write_json(rec)
        return rec

    def append_deep_round(self, rec: SessionRecord,
                          round_data: Dict[str, Any]) -> None:
        rec.data["rounds"].append(round_data)
        self._write_json(rec)

        rnd = round_data.get("round", "?")
        speeches = round_data.get("speeches", {})
        moderator = round_data.get("moderator", "")
        parsed = round_data.get("moderator_parsed") or {}
        raw = round_data.get("moderator_raw", "")

        blocks = [f"\n## Round {rnd}\n"]
        for agent in self._ordered_agents(speeches):
            kind, icon = self._agent_style(agent)
            blocks.append(_callout(kind, f"{icon} {agent.upper()}",
                                   _md_image(speeches[agent])))
        if parsed:
            mod_icon = self._agent_style(moderator)[1] if moderator else "🎙"
            body = "\n".join(
                f"**{k}：** {parsed[k]}"
                for k in ("矛盾点", "下一问", "行动分配", "本轮摘要")
                if k in parsed
            )
            blocks.append(_callout("abstract",
                                   f"{mod_icon} Moderator ({moderator.upper()})",
                                   body))
        elif raw:
            blocks.append(_callout("abstract", "🎙 Moderator", raw))
        blocks.append("---\n")
        self._append_md(rec.md_path, "\n".join(blocks))

        # frontmatter 的 rounds 计数仅是展示元数据，失败可忽略
        try:
            content = rec.md_path.read_text(encoding="utf-8")
            content = re.sub(r"^rounds: \d+", f"rounds: {rnd}", content,
                             count=1, flags=re.MULTILINE)
            rec.md_path.write_text(content, encoding="utf-8")
        except OSError:
            pass

    def append_deep_summary(self, rec: SessionRecord, summary: str) -> None:
        rec.data["summary"] = summary
        self._write_json(rec)
        self._append_md(rec.md_path,
                        f"\n---\n\n## Summary\n\n{_md_image(summary)}\n")

    # ── 历史列表 ──────────────────────────────────────────────────────────────

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = []
        claimed_md = set()

        for json_file in self.sessions_dir.glob("*.json"):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            md_path = Path(payload.get("md_path", ""))
            claimed_md.add(str(md_path))
            data = payload.get("data") or {}
            if payload.get("type") == "quick":
                count = sum(1 for e in data.get("events", [])
                            if e.get("kind") == "qa")
            else:
                count = len(data.get("rounds", []))
            if count == 0:
                continue
            try:
                mtime = json_file.stat().st_mtime
            except OSError:
                mtime = 0
            sessions.append({
                "type": payload.get("type", "quick"),
                "title": (payload.get("title") or md_path.stem)[:30],
                "file": md_path,
                "json_path": json_file,
                "date": md_path.parent.name,
                "entries": count,
                "mtime": mtime,
            })

        # 旧版纯 MD 会话（未被任何 JSON 接管的）
        for md_file in self.quick_dir.glob("????-??-??/*.md"):
            if str(md_file) in claimed_md:
                continue
            meta = legacy.parse_quick_meta(md_file)
            if meta and meta["entries"] > 0:
                sessions.append(meta)
        for md_file in self.deep_dir.glob("????-??-??/*.md"):
            if str(md_file) in claimed_md:
                continue
            meta = legacy.parse_deep_meta(md_file)
            if meta and meta["entries"] > 0:
                sessions.append(meta)

        sessions.sort(key=lambda s: s.get("mtime", 0), reverse=True)
        return sessions

    def load_quick_record(self, meta: Dict[str, Any],
                          n: int = 3) -> tuple:
        """打开历史 quick 会话 → (SessionRecord, 最近 n 条问答)。

        JSON 会话直接续用原记录；旧版 MD 会话解析后接管。
        """
        if meta.get("json_path"):
            payload = json.loads(
                Path(meta["json_path"]).read_text(encoding="utf-8"))
            rec = SessionRecord(
                id=payload["id"], type=payload["type"],
                created=payload.get("created", ""),
                title=payload.get("title", ""),
                md_path=Path(payload["md_path"]),
                json_path=Path(meta["json_path"]),
                data=payload.get("data") or {"events": []},
            )
            entries = [e for e in rec.data.get("events", [])
                       if e.get("kind") == "qa"]
            entries = [{"question": e.get("question", ""),
                        "responses": e.get("responses", {})}
                       for e in entries[-n:]]
            return rec, entries

        entries = legacy.load_quick_entries(Path(meta["file"]), n=n)
        rec = self.adopt_legacy_quick(Path(meta["file"]),
                                      meta.get("title", ""), entries)
        return rec, entries
