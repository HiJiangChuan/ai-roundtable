"""Session 层集成测试（FakePool 驱动，覆盖四条路径：quick / deep 多人 / deep solo / 升级）。"""
import asyncio

import pytest

from ai_roundtable.core.deep import DeepSession
from ai_roundtable.core.events import (AgentDelta, AgentResponded,
                                       AgentStarted, ErrorOccurred,
                                       ModeratorParsed, SessionEnded,
                                       StatusChanged, TitleGenerated)
from ai_roundtable.core.prompts import PromptLoader
from ai_roundtable.core.quick import QuickSession
from ai_roundtable.core.store import SessionStore
from ai_roundtable.config import PKG_PROMPTS_DIR
from tests.conftest import MODERATOR_OK, FakePool

AGENTS = ["alpha", "beta", "gamma"]


@pytest.fixture
def store(config, paths):
    return SessionStore(config, paths.sessions_dir)


@pytest.fixture
def loader():
    return PromptLoader(PKG_PROMPTS_DIR)


def make_quick(config, store, loader, pool, emit, agents=AGENTS):
    return QuickSession("tab-1", agents, pool, loader, store, config, emit)


def make_deep(config, store, loader, pool, emit, agents=AGENTS):
    return DeepSession("tab-1", agents, pool, loader, store, config, emit)


def of_type(events, cls):
    return [e for e in events if type(e) is cls]


# ── Quick ────────────────────────────────────────────────────────────────────

async def test_quick_ask_full_flow(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": "回答A", "beta": "回答B", "gamma": None})
    session = make_quick(config, store, loader, pool, emit)

    await session.ask("什么是好架构？")

    assert len(session.entries) == 1
    responses = session.entries[0]["responses"]
    assert responses["alpha"] == "回答A"
    assert responses["gamma"].startswith("[无响应：")     # 失败也留痕

    assert [e.state for e in of_type(events, StatusChanged)] == ["running", "ready"]
    assert {e.agent for e in of_type(events, AgentStarted)} == set(AGENTS)
    assert {e.agent for e in of_type(events, AgentResponded)} == set(AGENTS)
    assert all(e.session_id == "tab-1" for e in events)
    assert of_type(events, AgentDelta)                     # 有流式片段

    # 持久化落盘
    assert session.record is not None
    assert "什么是好架构" in session.record.md_path.read_text(encoding="utf-8")

    # 标题任务在后台生成
    assert session._title_task is not None
    await session._title_task
    titles = of_type(events, TitleGenerated)
    assert titles and session.title
    assert session.record.md_path.stem.endswith(session.title)


async def test_quick_followup_carries_context(config, store, loader, collect):
    events, emit = collect
    pool = FakePool(default="ok")
    session = make_quick(config, store, loader, pool, emit)
    session.title = "已有"           # 跳过标题生成
    await session.ask("第一个问题")
    await session.ask("追问")

    followup_prompts = [p for a, p in pool.calls if "追问" in p]
    assert followup_prompts
    assert all("[历史对话]" in p and "第一个问题" in p for p in followup_prompts)


async def test_quick_answer_snippet_truncated(config, store, loader, collect):
    events, emit = collect
    config["quick"]["answer_snippet"] = 50
    pool = FakePool(default="长" * 200)
    session = make_quick(config, store, loader, pool, emit)
    session.title = "已有"
    await session.ask("q1")
    await session.ask("q2")
    followup = next(p for a, p in pool.calls if "q2" in p)
    assert "长" * 50 + "…" in followup
    assert "长" * 51 not in followup


async def test_quick_compare(config, store, loader, collect):
    events, emit = collect
    pool = FakePool(default="回答")
    session = make_quick(config, store, loader, pool, emit)
    session.title = "已有"
    await session.ask("问题")
    events.clear()

    await session.compare()
    compares = of_type(events, AgentResponded)
    assert len(compares) == len(AGENTS)
    assert all(e.role == "compare" for e in compares)
    md = session.record.md_path.read_text(encoding="utf-8")
    assert "↺ Compare" in md

    # 互评的 prompt 只包含他人回答
    compare_prompts = [p for a, p in pool.calls if "评价其他" in p or "others" in p]
    assert compare_prompts


async def test_quick_compare_without_history(config, store, loader, collect):
    events, emit = collect
    session = make_quick(config, store, loader, FakePool(), emit)
    await session.compare()
    assert of_type(events, ErrorOccurred)


# ── Deep 多人 ─────────────────────────────────────────────────────────────────

def smart_pool():
    """按 prompt 内容分角色应答：主持人类 prompt 回结构化综述，其余回普通发言。

    判别词取自模板正文："完成主持人综述"（moderator.md）/"主持开场"（opening.md），
    嘉宾 prompt 的上下文里只会出现"[主持人综述]"，不会误中。
    """
    def responder_for(agent):
        def respond(prompt):
            if "完成主持人综述" in prompt or "主持开场" in prompt:
                return MODERATOR_OK
            return f"{agent}说"
        return respond
    return FakePool({a: responder_for(a) for a in AGENTS}, agents=AGENTS)


async def test_deep_opening_and_round(config, store, loader, collect):
    events, emit = collect
    # 开场（alpha 主持）→ 第1轮（beta 主持）：主持人调用返回结构化输出
    pool = FakePool({
        "alpha": [MODERATOR_OK, "alpha的发言", MODERATOR_OK],
        "beta": ["beta的发言", MODERATOR_OK],
        "gamma": "gamma的发言",
    }, agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)

    await session.start("AI 会取代程序员吗")
    assert session.state == DeepSession.WAITING
    mods = of_type(events, ModeratorParsed)
    assert mods and mods[0].round == 0
    assert mods[0].sections["下一问"]

    events.clear()
    await session.handle("可")
    assert session.round_num == 1
    responded = of_type(events, AgentResponded)
    assert {e.agent for e in responded} == set(AGENTS)
    # 第1轮并行：发言 prompt 不含他人内容（"你的行动类型"仅出现在 guest 模板）
    guest_prompts = [p for a, p in pool.calls if "你的行动类型" in p]
    assert len(guest_prompts) == 3
    assert all("第一位发言者" not in p for p in guest_prompts)

    # 落盘
    assert len(session.record.data["rounds"]) == 1
    md = session.record.md_path.read_text(encoding="utf-8")
    assert "## Round 1" in md


async def test_deep_round2_sequential_sees_priors(config, store, loader, collect):
    events, emit = collect
    pool = smart_pool()
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    await session.handle("可")     # 轮1 并行
    await session.handle("可")     # 轮2 顺序

    # 轮2 顺序发言：后发言者的 prompt 包含先发言者内容
    seq_prompts = [p for a, p in pool.calls
                   if "你的行动类型" in p and "第 2 轮" in p]
    assert len(seq_prompts) == 3
    assert "第一位发言者" in seq_prompts[0]
    assert "ALPHA" in seq_prompts[1]      # beta 能看到 alpha
    assert "BETA" in seq_prompts[2]       # gamma 能看到两位


async def test_deep_compression_after_kept_rounds(config, store, loader, collect):
    events, emit = collect
    config["deep"]["full_rounds_kept"] = 2
    pool = smart_pool()
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    for _ in range(3):
        await session.handle("可")
    # 3 轮完成、保留 2 轮 → 第 1 轮被压缩（用【本轮摘要】，零额外调用）
    assert len(session.context.full_rounds) == 2
    assert session.context.compressed_rounds[0]["round"] == 1
    assert "分歧" in session.context.compressed_rounds[0]["summary"]


async def test_deep_moderator_retry_then_fallback(config, store, loader, collect):
    events, emit = collect
    # 主持人两次都输出坏格式 → 重试一次后放弃，开场用默认综述兜底
    pool = FakePool({"alpha": ["坏格式", "还是坏格式"],
                     "beta": "b", "gamma": "c"}, agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题X")
    assert session.state == DeepSession.WAITING
    alpha_calls = [p for a, p in pool.calls if a == "alpha"]
    assert len(alpha_calls) == 2                       # 重试了一次
    mods = of_type(events, ModeratorParsed)
    assert mods[0].sections["下一问"] == "话题X"        # 兜底默认值


async def test_deep_free_text_becomes_note(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": MODERATOR_OK, "beta": "b", "gamma": "c"},
                    agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    note = "我觉得你们都忽略了成本因素，这在真实项目里往往是决定性的"
    await session.handle(note)
    assert session.context.user_notes == [note]        # 全文保留


async def test_deep_direct_question(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": MODERATOR_OK, "beta": "直答", "gamma": "c"},
                    agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    events.clear()

    await session.handle("@beta 你怎么看待成本问题")
    direct = [e for e in of_type(events, AgentResponded) if e.role == "direct"]
    assert direct and direct[0].agent == "beta"
    assert direct[0].extra == "你怎么看待成本问题"
    assert session.state == DeepSession.WAITING

    events.clear()
    await session.handle("@ghost 问题")
    assert any("未知 agent" in e.message for e in of_type(events, StatusChanged))


async def test_deep_deepen_records_context(config, store, loader, collect):
    events, emit = collect
    pool = smart_pool()
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    await session.handle("可")
    rounds_before = len(session.record.data["rounds"])

    await session.handle("深入此节")
    assert session.round_num == 1                       # 轮次不推进
    assert len(session.record.data["rounds"]) == rounds_before + 1
    assert session.record.data["rounds"][-1]["deepen"] is True
    # 深入内容进入上下文（旧版会丢）
    assert len(session.context.full_rounds) == 2


async def test_deep_end_session(config, store, loader, collect):
    events, emit = collect
    pool = smart_pool()
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    await session.handle("可")
    events.clear()

    await session.handle("止")
    assert session.state == DeepSession.ENDED
    ended = of_type(events, SessionEnded)
    assert ended and "会话已保存至" in ended[0].summary
    assert session.record.data["summary"]

    events.clear()
    await session.handle("可")                          # 结束后指令被拒
    assert session.round_num == 1


async def test_deep_error_recovers_state(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": MODERATOR_OK,
                     "beta": RuntimeError("pool 爆炸"), "gamma": "c"},
                    agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)
    await session.start("话题")
    await session.handle("可")                          # beta 抛异常
    assert of_type(events, ErrorOccurred)
    assert session.state == DeepSession.WAITING          # 状态恢复，可继续


# ── Deep Solo（回归：旧版开场必崩）────────────────────────────────────────────

SOLO_ROUND = """**【主持人开场/过渡】**
本轮聚焦效率与安全。

**【人物甲 · 工程师】**
效率优先。

**【主持人综述】**
核心矛盾：效率与安全不可兼得
下一个问题：什么情况下应当牺牲效率？"""


async def test_solo_opening_works(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": SOLO_ROUND}, agents=["alpha"])
    session = make_deep(config, store, loader, pool, emit, agents=["alpha"])

    await session.start("效率 vs 安全")
    assert session.state == DeepSession.WAITING          # 旧版这里直接 ValueError
    assert not of_type(events, ErrorOccurred)
    responded = of_type(events, AgentResponded)
    assert responded and responded[0].agent == "alpha"
    # 从 solo 综述里提取了下一问
    assert session._last_parsed["下一问"] == "什么情况下应当牺牲效率？"


async def test_solo_round_advances(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": SOLO_ROUND}, agents=["alpha"])
    session = make_deep(config, store, loader, pool, emit, agents=["alpha"])
    await session.start("话题")
    await session.handle("可")
    assert session.round_num == 1
    assert len(session.record.data["rounds"]) == 1
    # 下一轮的 prompt 带着上一轮提取的问题
    last_prompt = pool.calls[-1][1]
    assert "什么情况下应当牺牲效率？" in last_prompt


# ── Quick → Deep 升级（回归：旧版必崩 + 死 tab）──────────────────────────────

async def test_upgrade_from_quick_works(config, store, loader, collect):
    events, emit = collect
    pool = FakePool({"alpha": MODERATOR_OK, "beta": "b", "gamma": "c"},
                    agents=AGENTS)
    session = make_deep(config, store, loader, pool, emit)

    quick_entry = {"question": "微服务该拆吗",
                   "responses": {"alpha": "该", "beta": "不该", "gamma": "看情况"}}
    await session.start_from_quick("微服务该拆吗", quick_entry)

    assert session.state == DeepSession.WAITING          # 旧版：ValueError + 卡死 RUNNING
    assert not of_type(events, ErrorOccurred)
    mods = of_type(events, ModeratorParsed)
    assert mods and mods[0].round == 0
    # 快问内容注入了上下文
    assert "快问背景" in session.context.build_context()
    # 升级后可以正常推进
    await session.handle("可")
    assert session.round_num == 1
