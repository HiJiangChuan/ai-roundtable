from ai_roundtable.core.parsing import (parse_action_assignments,
                                        parse_moderator_output)
from tests.conftest import MODERATOR_OK


def test_parse_full_output():
    parsed = parse_moderator_output(MODERATOR_OK)
    assert parsed is not None
    assert parsed["矛盾点"] == "效率与安全之争"
    assert parsed["下一问"].startswith("应该优先")
    assert "Alpha：反驳" in parsed["行动分配"]
    assert "分歧" in parsed["本轮摘要"]


def test_parse_partial_accepts_essentials_only():
    text = "【矛盾点】\nA vs B\n\n【下一问】\n哪个对？"
    parsed = parse_moderator_output(text)
    assert parsed == {"矛盾点": "A vs B", "下一问": "哪个对？"}


def test_parse_missing_essential_returns_none():
    assert parse_moderator_output("【行动分配】\nA：反驳 - x") is None
    assert parse_moderator_output("完全自由发挥的文本") is None
    assert parse_moderator_output("【矛盾点】\n只有矛盾点") is None


def test_parse_empty_section_not_counted():
    text = "【矛盾点】\n\n【下一问】\n问题"
    assert parse_moderator_output(text) is None


def test_action_assignments_basic():
    text = ("Alpha：反驳 - 反驳效率论\n"
            "Beta: 补充 — 补充案例\n"
            "Gamma：挑战前提 - 质疑假设")
    parsed = parse_action_assignments(text)
    assert parsed["alpha"] == {"type": "反驳", "instruction": "反驳效率论"}
    assert parsed["beta"]["type"] == "补充"
    assert parsed["gamma"]["type"] == "挑战前提"


def test_action_assignments_tolerates_llm_noise():
    text = ("- **Alpha**：反驳 - 直接反驳\n"
            "* Beta：追问 - 提出问题\n"
            "这是一行无关说明\n")
    parsed = parse_action_assignments(text)
    assert parsed["alpha"]["type"] == "反驳"
    assert parsed["beta"]["type"] == "追问"
    assert len(parsed) == 2


def test_action_assignments_empty():
    assert parse_action_assignments("") == {}
