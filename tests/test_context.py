from ai_roundtable.core.context import ContextManager


def _round(n, **extra):
    return {"round": n, "speeches": {"alpha": f"第{n}轮发言"},
            "moderator_raw": "", "moderator_parsed":
                {"矛盾点": f"矛盾{n}", "下一问": f"问{n}", "本轮摘要": f"摘要{n}"},
            **extra}


def test_compression_lifecycle():
    cm = ContextManager(full_rounds_kept=2, compress_max=10)
    cm.set_topic("测试议题")
    cm.add_round(_round(1))
    cm.add_round(_round(2))
    assert not cm.needs_compression()
    cm.add_round(_round(3))
    assert cm.needs_compression()
    assert cm.get_round_to_compress()["round"] == 1
    cm.apply_compression("很长的摘要超过十个字会被截断")
    assert not cm.needs_compression()
    assert len(cm.full_rounds) == 2
    assert cm.compressed_rounds[0]["round"] == 1
    assert len(cm.compressed_rounds[0]["summary"]) == 10

    ctx = cm.build_context()
    assert "[议题摘要]" in ctx and "测试议题" in ctx
    assert "[历史摘要]" in ctx and "第1轮：" in ctx
    assert "[完整记录]" in ctx and "第3轮" in ctx


def test_user_notes_kept_in_full():
    cm = ContextManager()
    long_note = "这是一条超过三十个字符的用户插话，旧版会被截断到三十字丢失信息，现在应当全文保留下来"
    cm.add_user_note(long_note)
    cm.add_user_note("  ")          # 空白忽略
    assert cm.user_notes == [long_note]
    assert long_note in cm.build_context()


def test_quick_context_injection():
    cm = ContextManager()
    cm.set_quick_context({"question": "原始问题",
                          "responses": {"alpha": "A" * 500}})
    ctx = cm.build_context()
    assert "[快问背景]" in ctx and "原始问题" in ctx
    assert "A" * 300 in ctx and "A" * 301 not in ctx    # 300 字截断


def test_empty_context_placeholder():
    assert ContextManager().build_context() == "(暂无上下文)"


def test_topic_truncated_to_100():
    cm = ContextManager()
    cm.set_topic("长" * 150)
    assert len(cm.topic_summary) == 100
