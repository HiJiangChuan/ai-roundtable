"""模板契约测试：每个 render_* 帮助函数 × 真实打包模板渲染一遍。

旧版正是因为调用点与模板变量脱节，导致 solo 开场和 quick→deep 升级双双必崩——
这组测试保证任何一侧改动脱节都会立刻红。
"""
import pytest

from ai_roundtable.config import PKG_PROMPTS_DIR
from ai_roundtable.core import prompts as P

CONTRACTS = [
    (P.render_guest_quick,
     dict(agent_name="CLAUDE", question="什么是好架构？", context_history="")),
    (P.render_compare,
     dict(agent_name="CLAUDE", question="q", others_answers="[BETA]\n回答")),
    (P.render_opening,
     dict(moderator_name="Claude", topic="AI 会取代程序员吗",
          guests_list="Claude、Agy、Codex",
          guests_action_format="Claude：陈述立场 - 阐明核心立场")),
    (P.render_guest,
     dict(agent_name="Claude", context="(暂无上下文)", round_num=1,
          moderator_question="为什么？", action_type="反驳",
          action_instruction="反驳上一位", prior_speeches="")),
    (P.render_moderator,
     dict(moderator_name="Claude", context="c", round_num=2,
          round_speeches="[ALPHA]\n发言", guests_list="Claude、Agy",
          guests_action_format="Claude：{行动类型} - {具体说明}")),
    (P.render_solo,
     dict(topic="议题", context="(暂无上下文)", round_num=0,
          moderator_question="议题")),
    (P.render_compress, dict(round_content="=== 第1轮 ===")),
]


@pytest.fixture
def loader():
    return P.PromptLoader(PKG_PROMPTS_DIR)


@pytest.mark.parametrize("helper,kwargs", CONTRACTS,
                         ids=[h.__name__ for h, _ in CONTRACTS])
def test_render_contract(loader, helper, kwargs):
    text = helper(loader, **kwargs)
    assert text.strip()
    assert "{{" not in text


def test_all_required_templates_shipped(loader):
    assert loader.check_all() == []


def test_user_dir_overrides_package(tmp_path):
    (tmp_path / "guest_quick.md").write_text(
        "自定义 {{agent_name}} {{question}} {{context_history}}",
        encoding="utf-8")
    loader = P.PromptLoader(tmp_path)
    text = P.render_guest_quick(loader, agent_name="A", question="q",
                                context_history="")
    assert text.startswith("自定义 A")
    # 用户目录没有的模板回退包内
    assert "圆桌" in loader.render("compress", {"round_content": "x"})


def test_unresolved_placeholder_raises(tmp_path):
    (tmp_path / "broken.md").write_text("{{a}} {{missing}}", encoding="utf-8")
    loader = P.PromptLoader(tmp_path)
    with pytest.raises(ValueError, match="missing"):
        loader.render("broken", {"a": "1"})


def test_invalidate_reloads_edited_template(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("v1", encoding="utf-8")
    loader = P.PromptLoader(tmp_path)
    assert loader.render("t", {}) == "v1"
    f.write_text("v2", encoding="utf-8")
    assert loader.render("t", {}) == "v1"     # 缓存
    loader.invalidate("t")
    assert loader.render("t", {}) == "v2"
