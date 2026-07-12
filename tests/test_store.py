import json

import yaml

from ai_roundtable.core.store import SessionStore


def make_store(config, paths):
    return SessionStore(config, paths.sessions_dir)


def test_quick_roundtrip(config, paths):
    store = make_store(config, paths)
    rec = store.create_quick()
    assert rec.md_path.name == "001.md"
    assert rec.json_path.exists()

    store.append_quick_entry(rec, "什么是好架构？",
                             {"alpha": "回答A", "beta": "回答B"})
    md = rec.md_path.read_text(encoding="utf-8")
    assert "**Q:** 什么是好架构？" in md
    assert "> [!note]+ 🅰️ ALPHA" in md
    assert "> 回答A" in md

    payload = json.loads(rec.json_path.read_text(encoding="utf-8"))
    assert payload["data"]["events"][0]["question"] == "什么是好架构？"
    assert payload["data"]["events"][0]["responses"]["beta"] == "回答B"


def test_quick_custom_agent_persisted(config, paths):
    """回归：旧版硬编码三个 agent，自定义 agent 的回答被静默丢弃。"""
    config["ais"]["delta"] = {"cmd": "delta-cli", "icon": "🔺"}
    store = make_store(config, paths)
    rec = store.create_quick()
    store.append_quick_entry(rec, "q", {"delta": "第四个AI的回答"})
    md = rec.md_path.read_text(encoding="utf-8")
    assert "🔺 DELTA" in md
    assert "> 第四个AI的回答" in md


def test_numbering_no_overwrite_after_delete(config, paths):
    """回归：旧版 deep 用 len+1 编号，删除旧文件后会覆盖现存会话。"""
    store = make_store(config, paths)
    r1 = store.create_deep("话题一")
    r2 = store.create_deep("话题二")
    assert (r1.md_path.name, r2.md_path.name) == ("001.md", "002.md")
    r1.md_path.unlink()                      # 用户在 Obsidian 里删掉 001
    r3 = store.create_deep("话题三")
    assert r3.md_path.name == "003.md"       # 不是 002：不覆盖既有文件
    assert "话题二" in r2.md_path.read_text(encoding="utf-8")


def test_quick_title_rename(config, paths):
    store = make_store(config, paths)
    rec = store.create_quick()
    store.append_quick_entry(rec, "q", {"alpha": "a"})
    store.set_quick_title(rec, "架构")
    assert rec.md_path.name == "001-架构.md"
    assert rec.md_path.exists()
    payload = json.loads(rec.json_path.read_text(encoding="utf-8"))
    assert payload["title"] == "架构"
    assert payload["md_path"].endswith("001-架构.md")
    # 已带标题的文件不再重命名
    store.set_quick_title(rec, "新标题")
    assert rec.md_path.name == "001-架构.md"


def test_deep_frontmatter_survives_hostile_topic(config, paths):
    """回归：旧版把话题原文拼进 YAML，冒号/换行会产出非法 frontmatter。"""
    store = make_store(config, paths)
    topic = "微服务: 该拆吗?\n第二行 #tag"
    rec = store.create_deep(topic)
    content = rec.md_path.read_text(encoding="utf-8")
    frontmatter = content.split("---")[1]
    parsed = yaml.safe_load(frontmatter)
    assert parsed["title"] == topic
    assert parsed["type"] == "deep-dive"


def test_deep_round_and_summary(config, paths):
    store = make_store(config, paths)
    rec = store.create_deep("话题")
    store.append_deep_round(rec, {
        "round": 1, "moderator": "beta",
        "speeches": {"alpha": "发言A", "beta": "发言B"},
        "moderator_raw": "raw",
        "moderator_parsed": {"矛盾点": "X", "下一问": "Y"},
    })
    md = rec.md_path.read_text(encoding="utf-8")
    assert "## Round 1" in md
    assert "rounds: 1" in md
    assert "🅱️ Moderator (BETA)" in md
    assert "**矛盾点：** X" in md

    store.append_deep_summary(rec, "最终总结")
    md = rec.md_path.read_text(encoding="utf-8")
    assert "## Summary" in md and "最终总结" in md
    payload = json.loads(rec.json_path.read_text(encoding="utf-8"))
    assert payload["data"]["summary"] == "最终总结"
    assert len(payload["data"]["rounds"]) == 1


def test_image_token_converted(config, paths):
    store = make_store(config, paths)
    rec = store.create_quick()
    store.append_quick_entry(
        rec, "看图 [附件图片: /home/u/x/attachments/img_1.png]",
        {"alpha": "回答"})
    md = rec.md_path.read_text(encoding="utf-8")
    assert "![[attachments/img_1.png]]" in md


def test_list_sessions_json_and_legacy(config, paths):
    store = make_store(config, paths)
    # 新格式会话
    rec = store.create_quick()
    store.append_quick_entry(rec, "新问题", {"alpha": "a"})
    store.set_quick_title(rec, "新会话")
    # 空会话不应出现在列表
    store.create_quick()
    # 旧版纯 MD 文件（未被 JSON 接管）
    legacy_dir = store.quick_dir / "2026-01-01"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "001-旧话题.md").write_text(
        "---\ndate: 2026-01-01\ntype: rapid-fire\n---\n"
        "\n## 09:00 — 旧问题\n\n**Q:** 旧问题\n\n"
        "> [!note]+ 🔵 CLAUDE\n> 旧回答第一行\n> 旧回答第二行\n\n---\n",
        encoding="utf-8")

    sessions = store.list_sessions()
    titles = [s["title"] for s in sessions]
    assert "新会话" in titles
    assert "旧问题" in titles
    assert len(sessions) == 2         # 空会话被过滤

    legacy_meta = next(s for s in sessions if s["title"] == "旧问题")
    assert legacy_meta["json_path"] is None
    assert legacy_meta["entries"] == 1


def test_load_quick_record_json_and_legacy(config, paths):
    store = make_store(config, paths)
    rec = store.create_quick()
    for i in range(5):
        store.append_quick_entry(rec, f"问题{i}", {"alpha": f"答{i}"})
    sessions = store.list_sessions()
    meta = next(s for s in sessions if s["json_path"] is not None)
    loaded, entries = store.load_quick_record(meta, n=3)
    assert loaded.id == rec.id
    assert [e["question"] for e in entries] == ["问题2", "问题3", "问题4"]

    # 旧版文件：接管后可继续追加
    legacy_dir = store.quick_dir / "2026-01-01"
    legacy_dir.mkdir(parents=True)
    legacy_md = legacy_dir / "002-旧.md"
    legacy_md.write_text(
        "---\ntype: rapid-fire\n---\n"
        "\n## 09:00 — 旧问题\n\n**Q:** 旧问题\n\n"
        "> [!note]+ 🔵 CLAUDE\n> 旧回答\n\n---\n",
        encoding="utf-8")
    meta = next(s for s in store.list_sessions()
                if s["file"] == legacy_md)
    adopted, entries = store.load_quick_record(meta)
    assert entries == [{"question": "旧问题", "responses": {"claude": "旧回答"}}]
    store.append_quick_entry(adopted, "新问题", {"alpha": "新答"})
    assert "新问题" in legacy_md.read_text(encoding="utf-8")
    # 接管后 list 不再重复列出该文件
    files = [str(s["file"]) for s in store.list_sessions()]
    assert files.count(str(legacy_md)) == 1
