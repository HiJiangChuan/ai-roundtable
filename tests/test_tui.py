"""TUI 无头测试（Textual pilot）。

重点回归两个旧版架构 bug：
1. 多 tab 事件串台 —— 后台 tab 的回答绝不能出现在前台 tab 的面板/回放里
2. exclusive worker 互相取消 —— 一个 tab 提问不能杀掉另一个 tab 进行中的请求
"""
import asyncio

import pytest

from ai_roundtable.core.events import AgentResponded
from ai_roundtable.core.prompts import PromptLoader
from ai_roundtable.core.store import SessionStore
from ai_roundtable.config import PKG_PROMPTS_DIR
from ai_roundtable.tui.app import RoundtableApp
from ai_roundtable.tui.widgets import RoundtableInput
from tests.conftest import MODERATOR_OK, FakePool

AGENTS = ["alpha", "beta"]


def make_app(config, paths, pool, agents=AGENTS, initial_mode="quick"):
    return RoundtableApp(
        config=config,
        paths=paths,
        agents=agents,
        pool=pool,
        store=SessionStore(config, paths.sessions_dir),
        prompt_loader=PromptLoader(PKG_PROMPTS_DIR),
        initial_mode=initial_mode,
    )


async def submit(pilot, text: str):
    inp = pilot.app.query_one("#main-input", RoundtableInput)
    inp.focus()
    inp.value = text
    await pilot.press("enter")


async def settle(pilot, checks=40):
    """等待所有 worker 与消息队列清空。"""
    for _ in range(checks):
        await pilot.pause(0.05)
        app = pilot.app
        if not any(w.is_running for w in app.workers) and \
           not any(t.busy for t in app._tabs.values()):
            return
    raise AssertionError("workers did not settle")


async def test_boot_renders_agent_panels(config, paths):
    app = make_app(config, paths, FakePool(default="ok"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for agent in AGENTS:
            assert app.query_one(f"#log-{agent}")
            assert app.query_one(f"#title-{agent}")
        assert app._active == "tab-1"
        assert not app.query_one("#moderator-wrap").display   # quick 模式隐藏


async def test_quick_question_renders_and_persists(config, paths):
    pool = FakePool({"alpha": "Alpha的回答", "beta": "Beta的回答"})
    app = make_app(config, paths, pool)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await submit(pilot, "什么是好架构？")
        await settle(pilot)

        tab = app._tabs["tab-1"]
        assert len(tab.session.entries) == 1
        responded = [e for e in tab.replay if isinstance(e, AgentResponded)]
        assert {e.agent for e in responded} == set(AGENTS)
        assert len(app._log("alpha").lines) > 0
        # 标题任务完成后 tab 改名
        if tab.session._title_task:
            await tab.session._title_task
            await pilot.pause()
        assert tab.title != "新对话"


async def test_cross_tab_isolation_no_bleed(config, paths):
    """回归：tab1 的慢响应在 tab2 激活时完成，内容必须落在 tab1。"""
    gate = asyncio.Event()

    async def slow_alpha(prompt):
        await gate.wait()
        return "慢回答"

    pool = FakePool({"alpha": lambda p: slow_alpha(p), "beta": "快回答"})
    app = make_app(config, paths, pool)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await submit(pilot, "tab1 的问题")
        await pilot.pause(0.1)

        await pilot.press("ctrl+n")           # 切到新 tab2
        await pilot.pause()
        assert app._active == "tab-2"
        assert len(app._log("alpha").lines) == 0   # tab2 面板干净

        gate.set()                            # tab1 的慢响应此刻完成
        await settle(pilot)

        tab1, tab2 = app._tabs["tab-1"], app._tabs["tab-2"]
        # 内容归属 tab1，tab2 无任何污染（旧版会写进当前激活的 tab2）
        assert [e for e in tab1.replay if isinstance(e, AgentResponded)]
        assert tab2.replay == []
        assert len(app._log("alpha").lines) == 0
        assert tab1.unseen                    # 后台完成 → 未读标记
        assert not tab1.busy

        await pilot.press("ctrl+1")           # 切回 tab1 可见内容
        await pilot.pause()
        assert len(app._log("alpha").lines) > 0
        assert not app._tabs["tab-1"].unseen


async def test_parallel_tabs_do_not_cancel_each_other(config, paths):
    """回归：旧版 exclusive worker 共用 default group，新提问会取消他 tab 任务。"""
    gate = asyncio.Event()
    calls = {"n": 0}

    async def slow(prompt):
        calls["n"] += 1
        await gate.wait()
        return "完成"

    pool = FakePool({"alpha": lambda p: slow(p), "beta": lambda p: slow(p)})
    app = make_app(config, paths, pool)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await submit(pilot, "tab1 问题")
        await pilot.pause(0.1)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await submit(pilot, "tab2 问题")      # 旧版：这里会取消 tab1 的 worker
        await pilot.pause(0.1)

        assert calls["n"] == 4                # 两个 tab × 两个 agent 全部在跑
        gate.set()
        await settle(pilot)

        assert len(app._tabs["tab-1"].session.entries) == 1
        assert len(app._tabs["tab-2"].session.entries) == 1


async def test_deep_mode_flow(config, paths):
    def responder(agent):
        def respond(prompt):
            if "完成主持人综述" in prompt or "主持开场" in prompt:
                return MODERATOR_OK
            return f"{agent}的发言"
        return respond

    pool = FakePool({a: responder(a) for a in AGENTS}, agents=AGENTS)
    app = make_app(config, paths, pool, initial_mode="deep")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#moderator-wrap").display
        await submit(pilot, "AI 会取代程序员吗")
        await settle(pilot)
        tab = app._tabs["tab-1"]
        assert tab.session.state == "waiting"
        assert len(app._mod_log().lines) > 0      # 主持人综述已渲染

        await submit(pilot, "可")
        await settle(pilot)
        assert tab.session.round_num == 1
        assert len(app._log("alpha").lines) > 0


async def test_upgrade_creates_working_deep_tab(config, paths):
    """回归：旧版升级必崩且留下死 tab。"""
    def responder(agent):
        def respond(prompt):
            if "完成主持人综述" in prompt:
                return MODERATOR_OK
            return f"{agent}答"
        return respond

    pool = FakePool({a: responder(a) for a in AGENTS}, agents=AGENTS)
    app = make_app(config, paths, pool)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await submit(pilot, "微服务该拆吗")
        await settle(pilot)

        await pilot.press("ctrl+t")               # 升级 Deep
        await settle(pilot)
        assert len(app._tabs) == 2
        deep_tab = app._tabs["tab-2"]
        assert deep_tab.kind == "deep"
        assert deep_tab.session.state == "waiting"    # 旧版卡死在 running
        assert not deep_tab.ended

        await submit(pilot, "可")                  # 新 tab 可正常推进
        await settle(pilot)
        assert deep_tab.session.round_num == 1


async def test_close_tab_cancels_and_keeps_one(config, paths):
    gate = asyncio.Event()

    async def hang(prompt):
        await gate.wait()
        return "x"

    pool = FakePool({"alpha": lambda p: hang(p), "beta": lambda p: hang(p)})
    app = make_app(config, paths, pool)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+w")               # 只剩一个 tab 时拒绝关闭
        await pilot.pause()
        assert len(app._tabs) == 1

        await submit(pilot, "问题")
        await pilot.pause(0.1)
        await pilot.press("ctrl+n")
        await pilot.pause()
        # 关掉正在跑的 tab1：worker 被取消，不留悬挂
        await app._close_tab("tab-1")
        await pilot.pause(0.2)
        assert "tab-1" not in app._tabs
        assert app._active == "tab-2"
        gate.set()
        await settle(pilot)


async def test_session_end_disables_input(config, paths):
    def responder(agent):
        def respond(prompt):
            if "完成主持人综述" in prompt or "主持开场" in prompt:
                return MODERATOR_OK
            return "总结内容" if "最终总结" in prompt else f"{agent}说"
        return respond

    pool = FakePool({a: responder(a) for a in AGENTS}, agents=AGENTS)
    app = make_app(config, paths, pool, initial_mode="deep")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await submit(pilot, "话题")
        await settle(pilot)
        await submit(pilot, "止")
        await settle(pilot)

        tab = app._tabs["tab-1"]
        assert tab.ended
        assert app.query_one("#main-input", RoundtableInput).disabled
