"""
AI Roundtable TUI — dual-mode terminal interface with tab sessions.
快问（Quick）：默认，三个 AI 并行答题
深度讨论（Deep）：主持人轮换 / 行动类型系统
"""
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static, Tabs, Tab
from textual.markup import escape
from textual.screen import ModalScreen
from rich.markdown import Markdown

sys.path.insert(0, str(Path(__file__).parent))
from orchestrator import Orchestrator
from prompt_loader import PromptLoader
from cli_caller import CliCaller
from quick import QuickMode
from history import History


# ── Tab Session ───────────────────────────────────────────────────────────────

@dataclass
class TabSession:
    tab_id: str
    mode: str                                    # "quick" | "deep"
    title: str = "新对话"
    quick_mode: Optional[QuickMode] = None
    orchestrator: Optional[Orchestrator] = None
    log_entries: List[Tuple] = field(default_factory=list)  # for replay on switch
    quick_file: Optional[Path] = None            # quick sessions only


# ── History Modal ─────────────────────────────────────────────────────────────

class HistoryModal(ModalScreen):
    """Ctrl+O session history picker."""

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("enter",  "select",  show=False),
    ]

    CSS = """
    HistoryModal {
        align: center middle;
        background: #000000 60%;
    }
    #modal-container {
        width: 60;
        height: auto;
        max-height: 30;
        background: #161b22;
        border: solid #30363d;
        padding: 1 2;
    }
    #modal-title {
        height: 1;
        color: #58a6ff;
        margin-bottom: 1;
    }
    .session-item {
        height: 1;
        color: #8b949e;
        padding: 0 1;
    }
    .session-item.--highlight {
        background: #1f6feb;
        color: #e6edf3;
    }
    #modal-empty {
        color: #3d444d;
        height: 1;
    }
    """

    def __init__(self, sessions: list):
        super().__init__()
        self._sessions = sessions
        self._cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static("历史对话  ↑↓ 选择  Enter 打开  Esc 关闭", id="modal-title")
            if not self._sessions:
                yield Static("暂无历史记录", id="modal-empty")
            else:
                for i, s in enumerate(self._sessions[:20]):
                    tag  = "Q" if s['type'] == 'quick' else "D"
                    cnt  = s.get('entries', 0)
                    label = f"[{tag}] {s['date']}  {s['title'][:24]}  ({cnt}条)"
                    cls  = "session-item --highlight" if i == 0 else "session-item"
                    yield Static(label, id=f"si-{i}", classes=cls)

    def on_key(self, event: events.Key) -> None:
        if not self._sessions:
            return
        n = min(len(self._sessions), 20)
        if event.key == "up":
            self._move(-1, n)
        elif event.key == "down":
            self._move(1, n)

    def _move(self, delta: int, n: int) -> None:
        old = self._cursor
        self._cursor = (self._cursor + delta) % n
        # Update highlight
        old_w = self.query_one(f"#si-{old}", Static)
        new_w = self.query_one(f"#si-{self._cursor}", Static)
        old_w.set_classes("session-item")
        new_w.set_classes("session-item --highlight")

    def action_select(self) -> None:
        if self._sessions:
            self.dismiss(self._sessions[self._cursor])
        else:
            self.dismiss(None)


# ── Constants ─────────────────────────────────────────────────────────────────

AGENTS     = ["claude", "gemini", "codex"]
AGENT_ICON = {"claude": "🔵", "gemini": "🟢", "codex": "🟡"}
MAX_TABS   = 4


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: #0d1117;
    color: #e6edf3;
}

Header {
    background: #0d1117;
    color: #58a6ff;
    height: 1;
}

Footer {
    background: #0d1117;
    color: #3d444d;
    height: 1;
}

/* ── tabs ─────────────────────────────────────────────────────── */

Tabs {
    height: 2;
    background: #0d1117;
    border-bottom: solid #21262d;
    padding: 0 1;
}

Tab {
    color: #3d444d;
    padding: 0 2;
}

Tab.-active {
    color: #e6edf3;
}

Tab:hover {
    color: #8b949e;
}

/* ── guest panels ─────────────────────────────────────────────── */

#guest-panels {
    height: 1fr;
    padding: 1 2 0 2;
    layout: vertical;
}

.agent-wrap {
    height: 1fr;
    margin-bottom: 1;
    border-left: thick #30363d;
}

.agent-wrap.claude { border-left: thick #1f6feb; }
.agent-wrap.gemini { border-left: thick #238636; }
.agent-wrap.codex  { border-left: thick #9e6a03; }

.agent-title {
    height: 1;
    padding: 0 1;
    color: #3d444d;
    background: #0d1117;
}

.agent-wrap.claude .agent-title { color: #79c0ff; }
.agent-wrap.gemini .agent-title { color: #56d364; }
.agent-wrap.codex  .agent-title { color: #e3b341; }

.guest-log {
    height: 1fr;
    border: none;
    padding: 0 1;
    scrollbar-size: 1 1;
    scrollbar-color: #21262d;
    scrollbar-color-hover: #388bfd;
    scrollbar-background: transparent;
}

.guest-log:focus {
    background: #0d1f38;
}

.agent-wrap.claude .guest-log:focus { background: #0a1628; }
.agent-wrap.gemini .guest-log:focus { background: #081a0e; }
.agent-wrap.codex  .guest-log:focus { background: #1a1200; }

/* ── horizontal layout ────────────────────────────────────────── */

#guest-panels.horizontal {
    layout: horizontal;
}

#guest-panels.horizontal .agent-wrap {
    width: 1fr;
    height: 1fr;
    margin-bottom: 0;
    margin-right: 1;
}

#guest-panels.horizontal .agent-wrap:last-of-type {
    margin-right: 0;
}

/* ── moderator panel ──────────────────────────────────────────── */

#moderator-wrap {
    height: 9;
    margin: 0 2 0 2;
    border-left: thick #d4a847;
}

#moderator-title {
    height: 1;
    padding: 0 1;
    color: #d4a847;
    background: #0d1117;
}

#moderator-log {
    height: 1fr;
    border: none;
    padding: 0 1;
    scrollbar-size: 1 1;
    scrollbar-color: #21262d;
    scrollbar-background: transparent;
}

#moderator-log:focus {
    background: #1a1200;
}

/* ── input ────────────────────────────────────────────────────── */

#input-row {
    height: 3;
    padding: 0 3;
    align: left middle;
    border-top: solid #21262d;
}

#mode-label {
    color: #3d444d;
    width: auto;
    height: 1;
    content-align: left middle;
}

#main-input {
    width: 1fr;
    background: transparent;
    color: #e6edf3;
    border: none;
    padding: 0 1;
    height: 1;
}

#main-input:focus {
    border: none;
    background: transparent;
}

#version-label {
    width: auto;
    height: 1;
    content-align: right middle;
    color: #1c2128;
    padding: 0 0 0 1;
}
"""


# ── Input widget ──────────────────────────────────────────────────────────────

class RoundtableInput(Input):
    BINDINGS = [
        Binding("ctrl+v", "paste", show=False),
    ]

    def action_paste(self) -> None:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is not None:
                self.app._handle_image_paste(img, self)
                return
        except ImportError:
            self.app.notify("图片粘贴需要 Pillow：pip install Pillow",
                            severity="warning", timeout=5)
        except Exception as e:
            self.app.notify(f"图片读取失败: {e}", severity="error", timeout=5)
        super().action_paste()

    def _on_paste(self, event: events.Paste) -> None:
        text  = event.text
        lines = text.splitlines()
        if len(lines) <= 1:
            self.insert_text_at_cursor(text)
        else:
            app = self.app
            app._paste_count += 1
            app._paste_buffers[app._paste_count] = text
            token = f"[Pasted text #{app._paste_count} +{len(lines) - 1} lines]"
            self.insert_text_at_cursor(token)
        event.text = ""
        event.stop()


# ── App ───────────────────────────────────────────────────────────────────────

class RoundtableApp(App):
    TITLE = "AI Roundtable"
    CSS   = CSS
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit",           "退出",     priority=True),
        Binding("ctrl+r", "compare",        "互评"),
        Binding("ctrl+y", "copy_panel",     "复制面板"),
        Binding("ctrl+n", "new_tab",        "新建"),
        Binding("ctrl+w", "close_tab",      "关闭"),
        Binding("ctrl+o", "history",        "历史"),
        Binding("ctrl+t", "toggle_mode",    "切换模式"),
        Binding("ctrl+l", "toggle_layout",  "横竖"),
    ]

    def __init__(self, project_root: Path, config: Dict[str, Any],
                 initial_mode: str = "quick", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project_root = project_root
        self.config       = config

        prompts_dir         = project_root / "prompts"
        self._prompt_loader = PromptLoader(prompts_dir)
        timeout             = config.get("deep", {}).get("timeout_seconds", 60)
        self._cli_caller    = CliCaller(config, timeout=timeout)
        self._history       = History(config, project_root=project_root)

        # Tab state
        self._sessions:     Dict[str, TabSession] = {}
        self._active_tab:   str = ""
        self._tab_counter:  int = 0

        self._cb_queue:     asyncio.Queue = None
        self._paste_buffers: dict = {}
        self._paste_count:  int = 0
        self._image_buffers: dict = {}
        self._image_count:  int = 0

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Tabs(id="session-tabs")

        with Vertical(id="guest-panels"):
            for agent in AGENTS:
                with Vertical(id=f"wrap-{agent}", classes=f"agent-wrap {agent}"):
                    yield Static(f"{AGENT_ICON[agent]} {agent.upper()}",
                                 id=f"title-{agent}", classes="agent-title")
                    yield RichLog(id=f"log-{agent}", classes="guest-log",
                                  wrap=True, highlight=False, markup=True)

        with Vertical(id="moderator-wrap"):
            yield Static("🎙 主持人", id="moderator-title")
            yield RichLog(id="moderator-log", wrap=True, highlight=False, markup=True)

        with Horizontal(id="input-row"):
            yield Static("", id="mode-label")
            yield RoundtableInput(id="main-input")
            yield Static(f"v{self.config.get('version', '0.1.0')}", id="version-label")

        yield Footer()

    def on_mount(self) -> None:
        self._cb_queue = asyncio.Queue()
        self.set_interval(0.05, self._process_cb_queue)

        for agent in AGENTS:
            self.query_one(f"#log-{agent}", RichLog).can_focus = True
        self.query_one("#moderator-log", RichLog).can_focus = True

        # Create first tab
        self._create_tab(mode="quick")
        self.query_one("#main-input", RoundtableInput).focus()

    # ── Tab management ────────────────────────────────────────────────────────

    def _create_tab(self, mode: str = "quick", title: str = "新对话",
                    preload_entries: Optional[List] = None,
                    quick_file: Optional[Path] = None) -> str:
        """Create a new tab session. Returns tab_id."""
        if len(self._sessions) >= MAX_TABS:
            self.notify(f"最多同时开 {MAX_TABS} 个 Tab", severity="warning", timeout=3)
            return ""

        self._tab_counter += 1
        tab_id = f"tab-{self._tab_counter}"

        # Create file for quick sessions
        if mode == "quick" and quick_file is None:
            _, quick_file = self._history.new_quick_session()

        qm = QuickMode(self.config, self._cli_caller, self._prompt_loader,
                       history=self._history,
                       quick_file=quick_file) if mode == "quick" else None

        orch = Orchestrator(self.project_root, self.config,
                            history=self._history) if mode == "deep" else None

        session = TabSession(
            tab_id    = tab_id,
            mode      = mode,
            title     = title,
            quick_mode= qm,
            orchestrator = orch,
            quick_file= quick_file,
        )

        # Preload last entries for historical sessions
        if preload_entries and qm:
            for entry in preload_entries:
                qm.history_local.append(entry)
                session.log_entries.append(("history_entry", entry))

        self._sessions[tab_id] = session

        tabs = self.query_one("#session-tabs", Tabs)
        tabs.add_tab(Tab(title[:15], id=tab_id))
        self._switch_to_tab(tab_id)

        return tab_id

    def _switch_to_tab(self, tab_id: str) -> None:
        if tab_id not in self._sessions:
            return

        self._active_tab = tab_id
        session = self._sessions[tab_id]

        # Clear panels
        for agent in AGENTS:
            self._log(agent).clear()
            self._set_agent_title(agent)
        self._mod_log().clear()
        self.query_one("#moderator-title", Static).update("🎙 主持人")

        # Replay stored log entries
        for evt in session.log_entries:
            self._replay(evt)

        self._mode = session.mode
        self._apply_mode_ui()

        # Sync Tabs widget selection
        try:
            tabs = self.query_one("#session-tabs", Tabs)
            if tabs.active != tab_id:
                tabs.active = tab_id
        except Exception:
            pass

    def _close_tab(self, tab_id: str) -> None:
        if len(self._sessions) <= 1:
            self.notify("至少保留一个 Tab", severity="warning", timeout=2)
            return

        tabs = self.query_one("#session-tabs", Tabs)
        # Find neighbour to switch to
        ids = list(self._sessions.keys())
        idx = ids.index(tab_id)
        neighbour = ids[idx - 1] if idx > 0 else ids[1]

        tabs.remove_tab(tab_id)
        del self._sessions[tab_id]
        self._switch_to_tab(neighbour)

    def _update_active_tab_title(self, title: str) -> None:
        session = self._sessions.get(self._active_tab)
        if not session or session.title != "新对话":
            return
        session.title = title[:15]
        try:
            tabs = self.query_one("#session-tabs", Tabs)
            tab  = tabs.query_one(f"#tab-{self._active_tab.split('-')[1]}", Tab)
            tab.label = title[:15]
        except Exception:
            pass

    # ── Event replay ──────────────────────────────────────────────────────────

    def _store_event(self, event_type: str, kwargs: dict) -> None:
        session = self._sessions.get(self._active_tab)
        if session and event_type in ("agent_response", "moderator_output", "side_response"):
            session.log_entries.append((event_type, dict(kwargs)))

    def _replay(self, evt: Tuple) -> None:
        event_type, kwargs = evt
        if event_type == "history_entry":
            entry = kwargs  # {question, responses}
            for agent, content in entry.get('responses', {}).items():
                log = self._log(agent)
                log.write("[dim]── 历史 ──[/dim]")
                log.write(Markdown(content))
                log.write("")
            return
        # Replay normal events silently (no notifications/status changes)
        self._handle_event(event_type, _replay=True, **kwargs)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, agent: str) -> RichLog:
        return self.query_one(f"#log-{agent}", RichLog)

    def _mod_log(self) -> RichLog:
        return self.query_one("#moderator-log", RichLog)

    def _set_agent_title(self, agent: str, suffix: str = "") -> None:
        title = self.query_one(f"#title-{agent}", Static)
        base  = f"{AGENT_ICON[agent]} {agent.upper()}"
        title.update(f"{base} {suffix}".strip())

    def _apply_mode_ui(self) -> None:
        mod_wrap = self.query_one("#moderator-wrap")
        label    = self.query_one("#mode-label", Static)
        inp      = self.query_one("#main-input", RoundtableInput)

        tab_info = f"Tab {list(self._sessions.keys()).index(self._active_tab) + 1}/{len(self._sessions)}"

        if self._mode == "quick":
            mod_wrap.display = False
            label.update(f"[dim]Rapid Fire · {tab_info} ›[/dim]")
            inp.placeholder = "输入问题…  /compare 互评"
            self.bind("ctrl+t", "toggle_mode", description="升级 Deep Dive")
        else:
            mod_wrap.display = True
            session = self._sessions.get(self._active_tab)
            rnd = session.orchestrator.round_num if session and session.orchestrator else 0
            label.update(f"[dim]Deep Dive 轮{rnd + 1} · {tab_info} ›[/dim]")
            inp.placeholder = "可 · 止 · 深入此节 · @claude …"
            self.bind("ctrl+t", "toggle_mode", description="切换至 Rapid Fire")

        inp.disabled = False

    def _set_busy(self, busy: bool) -> None:
        inp   = self.query_one("#main-input", RoundtableInput)
        label = self.query_one("#mode-label", Static)
        if busy:
            inp.disabled = True
            label.update("[dim yellow]⟳[/dim yellow]")
        else:
            inp.disabled = False
            self._apply_mode_ui()
            inp.focus()

    @property
    def _mode(self) -> str:
        session = self._sessions.get(self._active_tab)
        return session.mode if session else "quick"

    @_mode.setter
    def _mode(self, value: str) -> None:
        session = self._sessions.get(self._active_tab)
        if session:
            session.mode = value

    @property
    def quick_mode(self) -> Optional[QuickMode]:
        session = self._sessions.get(self._active_tab)
        return session.quick_mode if session else None

    @property
    def orchestrator(self) -> Optional[Orchestrator]:
        session = self._sessions.get(self._active_tab)
        return session.orchestrator if session else None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _callback(self, event_type: str, **kwargs) -> None:
        if self._cb_queue is not None:
            self._cb_queue.put_nowait((event_type, kwargs))

    async def _process_cb_queue(self) -> None:
        try:
            while True:
                event_type, kwargs = self._cb_queue.get_nowait()
                self._store_event(event_type, kwargs)
                try:
                    self._handle_event(event_type, **kwargs)
                except Exception:
                    pass
        except asyncio.QueueEmpty:
            pass

    def _handle_event(self, event_type: str, _replay: bool = False, **kwargs) -> None:
        if event_type == "agent_start":
            if _replay:
                return
            agent = kwargs.get("agent", "")
            role  = kwargs.get("role", "guest")
            rnd   = kwargs.get("round", 0)
            if role == "moderator":
                self.query_one("#moderator-title", Static).update(
                    f"🎙 {agent.upper()} 主持  [dim]轮 {rnd}[/dim]")
            else:
                self._set_agent_title(agent, "⟳")

        elif event_type == "agent_response":
            agent   = kwargs.get("agent", "")
            content = kwargs.get("content", "")
            role    = kwargs.get("role", "guest")
            rnd     = kwargs.get("round", 0)

            if role == "moderator":
                return

            log = self._log(agent)
            self._set_agent_title(agent)

            if role == "quick":
                divider = "[dim]── 快问 ──[/dim]"
            elif role == "compare":
                divider = "[dim]── 互评 ──[/dim]"
            else:
                divider = f"[dim]── 轮 {rnd} ──[/dim]"

            log.write(divider)
            log.write(Markdown(content))
            log.write("")

            # Update tab title from first question
            if role == "quick" and not _replay:
                session = self._sessions.get(self._active_tab)
                if session and session.quick_mode and session.title == "新对话":
                    if session.quick_mode.history_local:
                        first_q = session.quick_mode.history_local[-1].get('question', '')
                        if first_q:
                            self._update_active_tab_title(first_q)

        elif event_type == "moderator_output":
            moderator = kwargs.get("moderator", "")
            rnd       = kwargs.get("round", 0)
            parsed    = kwargs.get("parsed", {})

            self.query_one("#moderator-title", Static).update(
                f"🎙 {moderator.upper()} 主持  [dim]轮 {rnd}[/dim]")
            mod = self._mod_log()
            mod.clear()

            lines = []
            if "矛盾点" in parsed:
                lines.append(f"[bold yellow]矛盾点[/bold yellow]  {escape(parsed['矛盾点'])}")
            if "下一问" in parsed:
                lines.append(f"[bold cyan]下一问[/bold cyan]  {escape(parsed['下一问'])}")
            if "行动分配" in parsed:
                compact = "  ".join(l.strip() for l in parsed["行动分配"].split("\n") if l.strip())
                lines.append(f"[bold green]行动[/bold green]  {escape(compact)}")
            if "本轮摘要" in parsed:
                lines.append(f"[dim]{escape(parsed['本轮摘要'])}[/dim]")
            for line in lines:
                mod.write(line)

        elif event_type == "side_response":
            agent    = kwargs.get("agent", "")
            content  = kwargs.get("content", "")
            question = kwargs.get("question", "")
            log = self._log(agent)
            log.write(f"[dim]── @直问: {escape(question[:60])} ──[/dim]")
            log.write(Markdown(content))
            log.write("")

        elif event_type == "status":
            if _replay:
                return
            message = kwargs.get("message", "")
            state   = kwargs.get("state", "")

            if state == "running":
                self._set_busy(True)
            elif state in ("waiting", "quick"):
                self._set_busy(False)
                if self._mode == "deep":
                    session = self._sessions.get(self._active_tab)
                    rnd = session.orchestrator.round_num if session and session.orchestrator else 0
                    self.query_one("#mode-label", Static).update(
                        f"[dim]深度 轮{rnd + 1} ›[/dim]")
            elif state == "ended":
                inp = self.query_one("#main-input", RoundtableInput)
                inp.disabled = True
                inp.placeholder = "会话已结束  Ctrl+N 新建"
                self.query_one("#mode-label", Static).update("[dim]结束[/dim]")

            if message and not _replay:
                self.notify(message, timeout=3)

        elif event_type == "session_end":
            if _replay:
                return
            summary = kwargs.get("summary", "")
            for agent in AGENTS:
                log = self._log(agent)
                log.write("[bold yellow]── 总结 ──[/bold yellow]")
                log.write(Markdown(summary))
            self.query_one("#moderator-title", Static).update("🎙 会话结束")
            inp = self.query_one("#main-input", RoundtableInput)
            inp.disabled = True
            inp.placeholder = "Ctrl+N 新建"

        elif event_type == "error":
            if not _replay:
                self.notify(kwargs.get("message", "未知错误"), severity="error", timeout=5)

    # ── Tabs events ───────────────────────────────────────────────────────────

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab and event.tab.id != self._active_tab:
            self._switch_to_tab(event.tab.id)

    # ── Input ─────────────────────────────────────────────────────────────────

    def _handle_image_paste(self, img, inp: "RoundtableInput") -> None:
        from datetime import datetime
        images_dir = self._history.attachments_dir
        self._image_count += 1
        filename = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._image_count}.png"
        path     = images_dir / filename
        img.save(path, "PNG")
        size_bytes = path.stat().st_size
        size_str   = f"{size_bytes // 1024} KB" if size_bytes < 1024 * 1024 else f"{size_bytes // (1024*1024)} MB"
        token = f"[Image #{self._image_count}] {filename} ({img.width}×{img.height}, {size_str})"
        self._image_buffers[self._image_count] = path
        inp.insert_text_at_cursor(token)

    def _expand_paste_tokens(self, text: str) -> str:
        import re

        def _replace_text(m):
            return self._paste_buffers.get(int(m.group(1)), m.group(0))
        text = re.sub(r'\[Pasted text #(\d+) \+\d+ lines\]', _replace_text, text)

        def _replace_image(m):
            path = self._image_buffers.get(int(m.group(1)))
            return f"\n[附件图片: {path}]\n" if path else m.group(0)
        text = re.sub(r'\[Image #(\d+)\][^\n]*', _replace_image, text)
        return text

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = self._expand_paste_tokens(event.value.strip())
        if not value:
            return
        self.query_one("#main-input", RoundtableInput).value = ""
        self._paste_buffers.clear()
        self._image_buffers.clear()

        session = self._sessions.get(self._active_tab)
        if not session:
            return

        if session.mode == "quick":
            if value == "/compare":
                self._run_compare()
            else:
                self._run_quick(value)
        else:
            orch = session.orchestrator
            if not orch:
                return
            if orch.state == "idle":
                self._run_start(value)
            elif orch.state == "waiting":
                self._run_command(value)
            elif orch.state == "ended":
                self.notify("会话已结束，按 Ctrl+N 新建", timeout=3)

    # ── Actions ───────────────────────────────────────────────────────────────

    async def action_toggle_mode(self) -> None:
        session = self._sessions.get(self._active_tab)
        if not session:
            return

        if session.mode == "quick":
            if not session.quick_mode or not session.quick_mode.history_local:
                self.notify("请先提问再升级到深度讨论", severity="warning", timeout=3)
                return
            last = session.quick_mode.get_context_for_deep()
            # Force new Deep tab
            new_id = self._create_tab(mode="deep",
                                      title=last.get("question", "深度讨论")[:15])
            if new_id:
                new_session = self._sessions[new_id]
                self._run_upgrade_to_deep(last.get("question", ""), last,
                                          new_session.orchestrator)
        else:
            # Switch back to quick: just create a new quick tab
            self._create_tab(mode="quick")

    def action_compare(self) -> None:
        session = self._sessions.get(self._active_tab)
        if not session or session.mode != "quick":
            self.notify("互评仅在 Rapid Fire 模式下可用", severity="warning", timeout=3)
            return
        if not session.quick_mode or not session.quick_mode.history_local:
            self.notify("请先提问，再发起互评", severity="warning", timeout=3)
            return
        self._run_compare()

    def action_new_tab(self) -> None:
        self._create_tab(mode="quick")

    def action_close_tab(self) -> None:
        self._close_tab(self._active_tab)

    def action_history(self) -> None:
        sessions = self._history.get_sessions_for_modal()
        self.push_screen(HistoryModal(sessions), self._on_history_selected)

    def _on_history_selected(self, result) -> None:
        if not result:
            return
        s_type = result.get('type')
        title  = result.get('title', '历史')
        fpath  = result.get('file')

        if s_type == 'quick' and fpath:
            entries = self._history.load_last_entries(Path(fpath), n=3)
            self._create_tab(mode="quick", title=title,
                             preload_entries=entries, quick_file=Path(fpath))
        elif s_type == 'deep':
            self.notify(f"深度讨论仅供查阅：{fpath}", timeout=4)

    def action_toggle_layout(self) -> None:
        panels = self.query_one("#guest-panels")
        panels.toggle_class("horizontal")
        label = "横向" if "horizontal" in panels.classes else "竖向"
        self.notify(label, timeout=1)

    def action_copy_panel(self) -> None:
        focused = self.screen.focused
        if not isinstance(focused, RichLog):
            self.notify("点击某个面板后再按 Ctrl+Y", severity="warning", timeout=2)
            return
        text = "\n".join(
            "".join(seg.text for seg in strip)
            for strip in focused.lines
        ).strip()
        if not text:
            self.notify("面板内容为空", timeout=2)
            return
        copied = False
        try:
            import pyperclip
            pyperclip.copy(text)
            copied = True
        except Exception:
            pass
        if not copied:
            try:
                self.copy_to_clipboard(text)
                copied = True
            except Exception:
                pass
        if copied:
            self.notify(f"已复制 {len(text)} 个字符", timeout=2)
            self.query_one("#main-input", RoundtableInput).focus()
        else:
            self.notify("复制失败，请检查 pyperclip 安装", severity="error", timeout=3)

    def action_quit(self) -> None:
        self.exit()

    # ── Workers ───────────────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _run_quick(self, question: str) -> None:
        self._callback("status", message="", state="running")
        session = self._sessions.get(self._active_tab)
        if not session or not session.quick_mode:
            return
        try:
            await session.quick_mode.run_question(question, self._callback)
        except Exception as e:
            self._callback("error", message=f"快问失败: {e}")
        finally:
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_compare(self) -> None:
        self._callback("status", message="", state="running")
        session = self._sessions.get(self._active_tab)
        if not session or not session.quick_mode:
            return
        try:
            await session.quick_mode.run_compare(self._callback)
        except Exception as e:
            self._callback("error", message=f"互评失败: {e}")
        finally:
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_upgrade_to_deep(self, topic: str, quick_context: dict,
                                   orch: Orchestrator) -> None:
        try:
            await orch.init_from_quick(topic, quick_context, self._callback)
        except Exception as e:
            self._callback("error", message=f"升级失败: {e}")

    @work(exclusive=True)
    async def _run_start(self, topic: str) -> None:
        session = self._sessions.get(self._active_tab)
        if not session or not session.orchestrator:
            return
        try:
            await session.orchestrator.start_session(topic, self._callback)
        except Exception as e:
            self._callback("error", message=f"开场失败: {e}")
            session.orchestrator._state = "idle"
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_command(self, value: str) -> None:
        session = self._sessions.get(self._active_tab)
        if not session or not session.orchestrator:
            return
        try:
            await session.orchestrator.handle_command(value, self._callback)
        except Exception as e:
            self._callback("error", message=f"执行失败: {e}")
            session.orchestrator._state = "waiting"
            self._callback("status", message="", state="waiting")
