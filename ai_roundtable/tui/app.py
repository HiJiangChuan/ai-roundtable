"""AI Roundtable TUI 主界面。

关键机制：
- core 层通过带 session_id 的类型化事件上报，app 按 id 路由到对应 tab——
  后台 tab 的活动只写入它自己的回放缓冲（tab 标签加 ● 提示），绝不串台。
- 每个 tab 一个 worker group，互不取消；关 tab / 退出时取消该组，
  引擎的 finally 保证子进程被杀，不留孤儿进程。
- 面板按当前 tab 会话的 agent 集合动态挂载，配色来自配置。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.markup import escape
from textual.message import Message
from textual.widgets import Footer, Header, RichLog, Static, Tab, Tabs
from textual.worker import WorkerState

from .. import __version__
from ..adapters import AgentPool
from ..config import AppPaths, available_agents, load_config
from ..core.events import (AgentDelta, AgentIdle, AgentProgress,
                           AgentResponded, AgentStarted, ErrorOccurred, Event,
                           ModeratorParsed, SessionEnded, StatusChanged,
                           TitleGenerated)
from ..core.deep import DeepSession
from ..core.prompts import PromptLoader
from ..core.quick import QuickSession
from ..core.store import SessionStore
from .history_modal import HistoryModal
from .settings_screen import SettingsScreen
from .styles import APP_CSS, agent_colors
from .widgets import FoldingMarkdown, RoundtableInput

MAX_TABS = 4


class CoreEventMessage(Message):
    def __init__(self, event: Event):
        self.event = event
        super().__init__()


@dataclass
class TabState:
    tab_id: str
    kind: str                                   # "quick" | "deep"
    session: object                             # QuickSession | DeepSession
    title: str = "新对话"
    replay: List[Event] = field(default_factory=list)
    last_input: str = ""
    busy: bool = False
    ended: bool = False
    unseen: bool = False


class RoundtableApp(App):
    TITLE = "AI Roundtable"
    CSS = APP_CSS
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("escape", "request_quit", "退出"),
        Binding("ctrl+q", "force_quit", show=False),
        Binding("/", "focus_input", show=False),
        Binding("ctrl+r", "compare", "互评"),
        Binding("ctrl+y", "copy_panel", "查看/复制"),
        Binding("ctrl+n", "new_tab", "新建"),
        Binding("ctrl+w", "close_tab", "关闭"),
        Binding("ctrl+o", "history", "历史"),
        Binding("ctrl+t", "toggle_mode", "Quick⇄Deep"),
        Binding("ctrl+l", "toggle_layout", "横竖"),
        Binding("ctrl+p", "show_settings", "设置"),
        Binding("ctrl+1", "switch_tab_n('1')", show=False),
        Binding("ctrl+2", "switch_tab_n('2')", show=False),
        Binding("ctrl+3", "switch_tab_n('3')", show=False),
        Binding("ctrl+4", "switch_tab_n('4')", show=False),
    ]

    def __init__(self, *, config: dict, paths: AppPaths, agents: List[str],
                 pool, store: SessionStore, prompt_loader: PromptLoader,
                 initial_mode: str = "quick",
                 startup_notes: Optional[List[str]] = None):
        super().__init__()
        self.config = config
        self._paths = paths
        self._agents = list(agents)
        self._pool = pool
        self._store = store
        self._prompts = prompt_loader
        self._initial_mode = initial_mode
        self._startup_notes = startup_notes or []

        self._tabs: Dict[str, TabState] = {}
        self._active: str = ""
        self._tab_counter: int = 0
        self._panel_agents: List[str] = []

        self._stream: Dict[tuple, str] = {}      # (session_id, agent) → 累积流
        self._paste_buffers: Dict[int, str] = {}
        self._paste_count = 0
        self._image_buffers: Dict[int, object] = {}
        self._image_count = 0

    # ── 布局 ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Tabs(id="session-tabs")
        yield Vertical(id="guest-panels", classes="horizontal")
        with Vertical(id="moderator-wrap"):
            yield Static("🎙 主持人", id="moderator-title")
            yield RichLog(id="moderator-log", wrap=True, highlight=False,
                          markup=True, min_width=1)
        with Horizontal(id="input-row"):
            yield Static("", id="mode-label")
            yield RoundtableInput(id="main-input")
            yield Static(f"v{__version__}", id="version-label")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#moderator-log", RichLog).can_focus = True
        await self._create_tab(kind=self._initial_mode)
        self.query_one("#main-input", RoundtableInput).focus()
        for note in self._startup_notes:
            self.notify(note, timeout=5)
        if not self._agents:
            self.notify("没有可用的 AI CLI（claude/agy/codex 均未安装或已禁用）",
                        severity="error", timeout=10)

    async def _ensure_panels(self, agents: List[str]) -> None:
        """按 agent 集合重建嘉宾面板（集合未变则跳过）。"""
        if self._panel_agents == list(agents):
            return
        panels = self.query_one("#guest-panels", Vertical)
        await panels.remove_children()
        wraps = []
        for i, agent in enumerate(agents):
            border, title_color = agent_colors(self.config, agent, i)
            icon = self._icon(agent)
            title = Static(f"{icon} {agent.upper()}", id=f"title-{agent}",
                           classes="agent-title")
            title.styles.color = title_color
            log = RichLog(id=f"log-{agent}", classes="guest-log", wrap=True,
                          highlight=False, markup=True, min_width=1)
            log.can_focus = True
            wrap = Vertical(
                title, log,
                Static("", id=f"stream-{agent}", classes="stream-preview"),
                id=f"wrap-{agent}", classes="agent-wrap",
            )
            wrap.styles.border_left = ("thick", border)
            wraps.append(wrap)
        if wraps:
            await panels.mount(*wraps)
        self._panel_agents = list(agents)

    def _icon(self, agent: str) -> str:
        return ((self.config.get("ais") or {}).get(agent) or {}).get("icon", "⚪")

    # ── Tab 管理 ─────────────────────────────────────────────────────────────

    def _make_session(self, tab_id: str, kind: str):
        cls = QuickSession if kind == "quick" else DeepSession
        return cls(tab_id, self._agents, self._pool, self._prompts,
                   self._store, self.config, self._emit)

    async def _create_tab(self, kind: str = "quick",
                          title: str = "新对话") -> str:
        if len(self._tabs) >= MAX_TABS:
            self.notify(f"最多同时开 {MAX_TABS} 个 Tab",
                        severity="warning", timeout=3)
            return ""
        self._tab_counter += 1
        tab_id = f"tab-{self._tab_counter}"
        tab = TabState(tab_id=tab_id, kind=kind,
                       session=self._make_session(tab_id, kind),
                       title=title[:15])
        self._tabs[tab_id] = tab
        tabs = self.query_one("#session-tabs", Tabs)
        tabs.add_tab(Tab(self._tab_label(tab), id=tab_id))
        await self._switch_to_tab(tab_id)
        return tab_id

    async def _switch_to_tab(self, tab_id: str) -> None:
        tab = self._tabs.get(tab_id)
        if tab is None:
            return
        self._active = tab_id
        tab.unseen = False
        self._refresh_tab_labels()

        await self._ensure_panels(tab.session.agents)
        for agent in tab.session.agents:
            self._log(agent).clear()
            self._set_agent_title(agent)
            self._hide_preview(agent)
        mod = self._mod_log()
        mod.clear()
        self.query_one("#moderator-title", Static).update("🎙 主持人")

        for ev in tab.replay:
            self._render_event(ev, replay=True)

        # 恢复进行中的流式预览
        for agent in tab.session.agents:
            buf = self._stream.get((tab_id, agent))
            if buf:
                self._show_preview(agent, escape(buf[-600:]))

        self._apply_mode_ui()
        try:
            tabs = self.query_one("#session-tabs", Tabs)
            if tabs.active != tab_id:
                tabs.active = tab_id
        except NoMatches:
            pass

    async def _close_tab(self, tab_id: str) -> None:
        if len(self._tabs) <= 1:
            self.notify("至少保留一个 Tab", severity="warning", timeout=2)
            return
        tab = self._tabs.get(tab_id)
        if tab is None:
            return
        self.workers.cancel_group(self, tab_id)
        close = getattr(tab.session, "close", None)
        if close:
            close()
        for agent in list(tab.session.agents):
            self._stream.pop((tab_id, agent), None)

        ids = list(self._tabs.keys())
        idx = ids.index(tab_id)
        neighbour = ids[idx + 1] if idx + 1 < len(ids) else ids[idx - 1]
        self.query_one("#session-tabs", Tabs).remove_tab(tab_id)
        del self._tabs[tab_id]
        self._refresh_tab_labels()
        await self._switch_to_tab(neighbour)

    def _tab_label(self, tab: TabState) -> str:
        ids = list(self._tabs.keys())
        num = ids.index(tab.tab_id) + 1 if tab.tab_id in ids else len(ids) + 1
        dot = " ●" if tab.unseen else ""
        return f"{num}.{tab.title[:15]}{dot}"

    def _refresh_tab_labels(self) -> None:
        tabs = self.query_one("#session-tabs", Tabs)
        for tab in self._tabs.values():
            try:
                widget = tabs.query_one(f"#{tab.tab_id}", Tab)
                widget.label = self._tab_label(tab)
            except NoMatches:
                pass

    async def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab and event.tab.id and event.tab.id != self._active:
            await self._switch_to_tab(event.tab.id)

    # ── 事件路由 ─────────────────────────────────────────────────────────────

    def _emit(self, event: Event) -> None:
        self.post_message(CoreEventMessage(event))

    def on_core_event_message(self, message: CoreEventMessage) -> None:
        ev = message.event
        tab = self._tabs.get(ev.session_id)
        if tab is None:
            return

        # 与 UI 无关的状态先记录（无论前后台）
        if isinstance(ev, (AgentResponded, ModeratorParsed, SessionEnded)):
            tab.replay.append(ev)
        if isinstance(ev, AgentDelta):
            key = (ev.session_id, ev.agent)
            self._stream[key] = (self._stream.get(key, "") + ev.text)[-4000:]
        if isinstance(ev, AgentResponded):
            self._stream.pop((ev.session_id, ev.agent), None)
        if isinstance(ev, StatusChanged):
            tab.busy = ev.state == "running"
            if ev.state == "ended":
                tab.ended = True
        if isinstance(ev, TitleGenerated) and ev.title:
            if tab.title == "新对话":
                tab.title = ev.title[:15]
                self._refresh_tab_labels()

        if ev.session_id == self._active:
            self._render_event(ev)
        else:
            if isinstance(ev, (AgentResponded, ModeratorParsed,
                               SessionEnded, ErrorOccurred)):
                tab.unseen = True
                self._refresh_tab_labels()

    # ── 事件渲染（仅作用于当前可见面板）──────────────────────────────────────

    def _render_event(self, ev: Event, replay: bool = False) -> None:
        if isinstance(ev, AgentStarted):
            if replay:
                return
            if ev.role == "moderator":
                self.query_one("#moderator-title", Static).update(
                    f"🎙 {ev.agent.upper()} 主持  [dim]轮 {ev.round}[/dim]")
            else:
                self._set_agent_title(ev.agent, "⟳")

        elif isinstance(ev, AgentIdle):
            if not replay:
                self._set_agent_title(ev.agent, f"⏳ {int(ev.elapsed)}s")

        elif isinstance(ev, AgentProgress):
            if not replay:
                self._show_preview(ev.agent,
                                   f"[dim]{escape(ev.line[:120])}[/dim]")

        elif isinstance(ev, AgentDelta):
            if not replay:
                buf = self._stream.get((ev.session_id, ev.agent), "")
                self._show_preview(ev.agent, escape(buf[-600:]))

        elif isinstance(ev, AgentResponded):
            self._render_response(ev, replay)

        elif isinstance(ev, ModeratorParsed):
            self._render_moderator(ev)

        elif isinstance(ev, StatusChanged):
            if replay:
                return
            self._apply_mode_ui()
            if ev.message:
                self.notify(ev.message, timeout=3)

        elif isinstance(ev, SessionEnded):
            for agent in self._panel_agents:
                log = self._log(agent)
                log.write("[bold yellow]── 总结 ──[/bold yellow]")
                log.write(FoldingMarkdown(ev.summary))
                log.write("")
            self.query_one("#moderator-title", Static).update("🎙 会话结束")
            if not replay:
                self._apply_mode_ui()

        elif isinstance(ev, ErrorOccurred):
            if not replay:
                self.notify(ev.message, severity="error", timeout=5)

    def _render_response(self, ev: AgentResponded, replay: bool) -> None:
        if ev.role == "moderator":
            return
        try:
            log = self._log(ev.agent)
        except NoMatches:
            return          # 历史回放里可能出现已被禁用的 agent
        if not replay:
            self._hide_preview(ev.agent)
            self._set_agent_title(ev.agent)

        dividers = {
            "quick": "[dim]── Quick Round ──[/dim]",
            "compare": "[dim]── 互评 ──[/dim]",
            "history": "[dim]── 历史 ──[/dim]",
            "direct": f"[dim]── @直问: {escape(ev.extra[:60])} ──[/dim]",
        }
        divider = dividers.get(ev.role, f"[dim]── 轮 {ev.round} ──[/dim]")
        log.write(divider)
        log.write(FoldingMarkdown(ev.content))
        log.write("")

    def _render_moderator(self, ev: ModeratorParsed) -> None:
        self.query_one("#moderator-title", Static).update(
            f"🎙 {ev.moderator.upper()} 主持  [dim]轮 {ev.round}[/dim]")
        mod = self._mod_log()
        mod.clear()
        parsed = ev.sections
        if "矛盾点" in parsed:
            mod.write(f"[bold yellow]矛盾点[/bold yellow]  {escape(parsed['矛盾点'])}")
        if "下一问" in parsed:
            mod.write(f"[bold cyan]下一问[/bold cyan]  {escape(parsed['下一问'])}")
        if parsed.get("行动分配"):
            compact = "  ".join(l.strip() for l in
                                parsed["行动分配"].split("\n") if l.strip())
            mod.write(f"[bold green]行动[/bold green]  {escape(compact)}")
        if parsed.get("本轮摘要"):
            mod.write(f"[dim]{escape(parsed['本轮摘要'])}[/dim]")

    # ── 小部件访问 ────────────────────────────────────────────────────────────

    def _log(self, agent: str) -> RichLog:
        return self.query_one(f"#log-{agent}", RichLog)

    def _mod_log(self) -> RichLog:
        return self.query_one("#moderator-log", RichLog)

    def _set_agent_title(self, agent: str, suffix: str = "") -> None:
        try:
            title = self.query_one(f"#title-{agent}", Static)
        except NoMatches:
            return
        title.update(f"{self._icon(agent)} {agent.upper()} {suffix}".strip())

    def _show_preview(self, agent: str, content: str) -> None:
        try:
            w = self.query_one(f"#stream-{agent}", Static)
        except NoMatches:
            return
        w.add_class("--active")
        w.update(content)

    def _hide_preview(self, agent: str) -> None:
        try:
            w = self.query_one(f"#stream-{agent}", Static)
        except NoMatches:
            return
        w.remove_class("--active")
        w.update("")

    def _apply_mode_ui(self) -> None:
        tab = self._tabs.get(self._active)
        if tab is None:
            return
        label = self.query_one("#mode-label", Static)
        inp = self.query_one("#main-input", RoundtableInput)
        mod_wrap = self.query_one("#moderator-wrap")
        ids = list(self._tabs.keys())
        tab_info = f"Tab {ids.index(tab.tab_id) + 1}/{len(ids)}"

        if tab.kind == "quick":
            mod_wrap.display = False
            inp.placeholder = "输入问题…  /compare 互评  Ctrl+T 升级 Deep"
        else:
            mod_wrap.display = True
            state = getattr(tab.session, "state", "idle")
            if state == "idle":
                inp.placeholder = "输入讨论话题开始 Deep Round…"
            else:
                inp.placeholder = "可 · 止 · 深入此节 · @agent 问题 · 其他文本注入插话"

        if tab.ended:
            label.update("[dim]结束[/dim]")
            inp.disabled = True
            inp.placeholder = "会话已结束  Ctrl+N 新建"
        elif tab.busy:
            label.update("[dim yellow]⟳[/dim yellow]")
            inp.disabled = True
        else:
            if tab.kind == "quick":
                label.update(f"[dim]Quick Round · {tab_info} ›[/dim]")
            else:
                rnd = getattr(tab.session, "round_num", 0)
                label.update(f"[dim]Deep Round 轮{rnd + 1} · {tab_info} ›[/dim]")
            inp.disabled = False
            inp.focus()

    # ── 输入 ─────────────────────────────────────────────────────────────────

    def get_last_input(self) -> str:
        tab = self._tabs.get(self._active)
        return tab.last_input if tab else ""

    def register_paste(self, text: str) -> str:
        self._paste_count += 1
        self._paste_buffers[self._paste_count] = text
        lines = len(text.splitlines())
        return f"[Pasted text #{self._paste_count} +{lines - 1} lines]"

    def handle_image_paste(self, img, inp: RoundtableInput) -> None:
        self._image_count += 1
        filename = (f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    f"_{self._image_count}.png")
        path = self._store.attachments_dir / filename
        img.save(path, "PNG")
        size = path.stat().st_size
        size_str = (f"{size // 1024} KB" if size < 1024 * 1024
                    else f"{size // (1024 * 1024)} MB")
        self._image_buffers[self._image_count] = path
        inp.insert_text_at_cursor(
            f"[Image #{self._image_count}] {filename} "
            f"({img.width}×{img.height}, {size_str})")

    def _expand_tokens(self, text: str) -> str:
        def _text(m):
            return self._paste_buffers.get(int(m.group(1)), m.group(0))
        text = re.sub(r"\[Pasted text #(\d+) \+\d+ lines\]", _text, text)

        def _image(m):
            path = self._image_buffers.get(int(m.group(1)))
            return f"\n[附件图片: {path}]\n" if path else m.group(0)
        return re.sub(r"\[Image #(\d+)\][^\n]*", _image, text)

    async def on_input_submitted(self, event) -> None:
        value = self._expand_tokens(event.value.strip())
        if not value:
            return
        self.query_one("#main-input", RoundtableInput).value = ""
        self._paste_buffers.clear()
        self._image_buffers.clear()

        tab = self._tabs.get(self._active)
        if tab is None or tab.ended:
            return
        if tab.busy:
            self.notify("当前 Tab 正在进行中…", timeout=2)
            return
        tab.last_input = value

        if tab.kind == "quick":
            if value == "/compare":
                self.action_compare()
            else:
                self._spawn(tab, tab.session.ask(value))
        else:
            self._spawn(tab, tab.session.handle(value))

    # ── Worker 管理 ──────────────────────────────────────────────────────────

    def _spawn(self, tab: TabState, coro) -> None:
        tab.busy = True
        if tab.tab_id == self._active:
            self._apply_mode_ui()
        self.run_worker(coro, group=tab.tab_id, exclusive=False,
                        exit_on_error=False)

    def on_worker_state_changed(self, event) -> None:
        group = getattr(event.worker, "group", "")
        tab = self._tabs.get(group)
        if tab is None:
            return
        if event.state == WorkerState.ERROR:
            self.notify(f"任务异常: {event.worker.error}",
                        severity="error", timeout=5)
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR,
                           WorkerState.CANCELLED):
            if not any(w.group == group and w.is_running
                       for w in self.workers):
                tab.busy = False
                if group == self._active:
                    self._apply_mode_ui()

    # ── Actions ──────────────────────────────────────────────────────────────

    async def action_toggle_mode(self) -> None:
        tab = self._tabs.get(self._active)
        if tab is None:
            return
        if tab.kind == "quick":
            entries = getattr(tab.session, "entries", [])
            if not entries:
                self.notify("请先提问再升级到 Deep Round",
                            severity="warning", timeout=3)
                return
            last = tab.session.last_entry()
            topic = last.get("question", "Deep Round")
            new_id = await self._create_tab(kind="deep", title=topic)
            if new_id:
                new_tab = self._tabs[new_id]
                self._spawn(new_tab,
                            new_tab.session.start_from_quick(topic, last))
        else:
            await self._create_tab(kind="quick")

    def action_compare(self) -> None:
        tab = self._tabs.get(self._active)
        if tab is None or tab.kind != "quick":
            self.notify("互评仅在 Quick Round 模式下可用",
                        severity="warning", timeout=3)
            return
        if tab.busy:
            self.notify("当前 Tab 正在进行中…", timeout=2)
            return
        if not getattr(tab.session, "entries", []):
            self.notify("请先提问，再发起互评", severity="warning", timeout=3)
            return
        self._spawn(tab, tab.session.compare())

    async def action_new_tab(self) -> None:
        await self._create_tab(kind="quick")

    async def action_close_tab(self) -> None:
        await self._close_tab(self._active)

    def action_history(self) -> None:
        self.push_screen(HistoryModal(self._store.list_sessions()),
                         self._on_history_selected)

    def _on_history_selected(self, result) -> None:
        if not result:
            return
        if result.get("type") == "deep":
            self.notify(f"Deep Round 仅供查阅：{result.get('file')}", timeout=4)
            return
        self.call_later(self._open_history_quick, result)

    async def _open_history_quick(self, meta: dict) -> None:
        try:
            rec, entries = self._store.load_quick_record(meta, n=3)
        except Exception as e:
            self.notify(f"历史加载失败: {e}", severity="error", timeout=5)
            return
        title = meta.get("title", "历史")

        tab = self._tabs.get(self._active)
        reuse = (tab is not None and tab.kind == "quick"
                 and not tab.replay
                 and not getattr(tab.session, "entries", []))
        if not reuse:
            new_id = await self._create_tab(kind="quick", title=title)
            if not new_id:
                return
            tab = self._tabs[new_id]

        tab.title = title[:15]
        tab.session.preload(rec, entries, title=title)
        for entry in entries:
            for agent, content in entry.get("responses", {}).items():
                ev = AgentResponded(tab.tab_id, agent=agent, content=content,
                                    role="history")
                tab.replay.append(ev)
                if tab.tab_id == self._active:
                    self._render_event(ev, replay=True)
        self._refresh_tab_labels()

    def action_show_settings(self) -> None:
        self.push_screen(
            SettingsScreen(self.config, self._paths, self._prompts),
            self._on_settings_closed)

    def _on_settings_closed(self, result) -> None:
        if result != "saved":
            return
        try:
            self.config = load_config(self._paths)
            self._agents = available_agents(self.config)
            registry = getattr(self._pool, "registry", None)
            self._pool = AgentPool(self.config, registry=registry,
                                   log_path=self._paths.cli_log)
            self.notify("配置已重载；AI 变更将应用于新建的 Tab", timeout=4)
        except Exception as e:
            self.notify(f"重载配置失败: {e}", severity="warning", timeout=4)

    async def action_switch_tab_n(self, n: str) -> None:
        ids = list(self._tabs.keys())
        idx = int(n) - 1
        if idx < len(ids):
            await self._switch_to_tab(ids[idx])
        else:
            self.notify(f"没有第 {n} 个标签页", severity="warning", timeout=1)

    async def action_toggle_layout(self) -> None:
        panels = self.query_one("#guest-panels")
        panels.toggle_class("horizontal")
        self.notify("横向" if panels.has_class("horizontal") else "竖向",
                    timeout=1)
        self.call_later(self._switch_to_tab, self._active)

    def action_copy_panel(self) -> None:
        import os
        import sys
        import termios
        import tty
        focused = self.screen.focused
        if not isinstance(focused, RichLog) or not focused.id:
            self.notify("请先点击某个 AI 面板", severity="warning", timeout=2)
            return
        agent = focused.id.replace("log-", "")
        tab = self._tabs.get(self._active)
        if tab is None or agent not in tab.session.agents:
            self.notify("请点击 AI 回答面板", severity="warning", timeout=2)
            return
        parts = tab.session.responses_for(agent)
        if not parts:
            self.notify("暂无内容", timeout=2)
            return
        text = ("\n\n" + "─" * 60 + "\n\n").join(parts)

        with self.suspend():
            os.system("clear")
            print(text)
            print("\n" + "─" * 40)
            print("按任意键返回")
            try:
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    sys.stdin.read(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except (termios.error, OSError):
                pass

    def action_focus_input(self) -> None:
        self.query_one("#main-input", RoundtableInput).focus()

    def action_request_quit(self) -> None:
        if any(t.busy for t in self._tabs.values()):
            self.notify("有任务进行中；再按 Ctrl+Q 强制退出", timeout=3)
            return
        self.action_force_quit()

    def action_force_quit(self) -> None:
        self._cleanup()
        self.exit()

    def _cleanup(self) -> None:
        for tab in self._tabs.values():
            self.workers.cancel_group(self, tab.tab_id)
            close = getattr(tab.session, "close", None)
            if close:
                close()
        kill_all = getattr(self._pool, "kill_all", None)
        if kill_all:
            kill_all()

    def on_unmount(self) -> None:
        self._cleanup()
