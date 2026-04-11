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
from rich.markdown import Markdown, CodeBlock as _CodeBlock
from rich.text import Text as _Text


class _FoldingCodeBlock(_CodeBlock):
    """Code block that folds long lines mid-token instead of clipping them."""
    def __rich_console__(self, console, options):
        code = str(self.text).rstrip()
        yield _Text(" ", style="on #161b22")  # top padding
        for line in (code.split('\n') if code else ['']):
            yield _Text(" " + line, style="on #161b22", overflow="fold", no_wrap=False)
        yield _Text(" ", style="on #161b22")  # bottom padding


class _FoldingMarkdown(Markdown):
    elements = {**Markdown.elements, "fence": _FoldingCodeBlock, "code_block": _FoldingCodeBlock}

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
    last_input: str = ""                         # ↑ 键恢复上一条输入


# ── History Modal ─────────────────────────────────────────────────────────────

class HistoryModal(ModalScreen):
    """Ctrl+O session history picker — two-column: quick (left) / deep (right)."""

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
        width: 90;
        height: auto;
        max-height: 36;
        background: #161b22;
        border: solid #30363d;
        padding: 1 2;
    }
    #modal-title {
        height: 1;
        color: #58a6ff;
        margin-bottom: 1;
    }
    #modal-columns {
        height: auto;
        max-height: 28;
    }
    .col-panel {
        width: 1fr;
        height: auto;
        max-height: 28;
        padding: 0 1;
    }
    .col-panel-left {
        border-right: solid #30363d;
        padding-right: 2;
    }
    .col-header {
        height: 1;
        color: #58a6ff;
        margin-bottom: 0;
    }
    .col-header.--active {
        color: #e6edf3;
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
    .col-empty {
        color: #3d444d;
        height: 1;
        padding: 0 1;
    }
    .col-more {
        color: #3d444d;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, sessions: list):
        super().__init__()
        self._quick = [s for s in sessions if s['type'] == 'rapid-fire']
        self._deep  = [s for s in sessions if s['type'] == 'deep-dive']
        # col: 0=quick, 1=deep; row: index within column
        self._col = 0 if self._quick else (1 if self._deep else 0)
        self._rows = [0, 0]   # cursor row per column

    def _col_list(self, col: int) -> list:
        return self._quick if col == 0 else self._deep

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static("历史对话   ↑↓ 选择   ←→ 切换   Enter 打开   Esc 关闭",
                         id="modal-title")
            with Horizontal(id="modal-columns"):
                with Vertical(classes="col-panel col-panel-left"):
                    hdr_cls = "col-header --active" if self._col == 0 else "col-header"
                    yield Static("⚡ Rapid Fire", id="col-hdr-0", classes=hdr_cls)
                    if self._quick:
                        for i, s in enumerate(self._quick[:15]):
                            hi = (self._col == 0 and i == 0)
                            cls = "session-item --highlight" if hi else "session-item"
                            yield Static(self._fmt(s, 0, i), id=f"q-{i}", classes=cls)
                        if len(self._quick) > 15:
                            yield Static(f"…还有 {len(self._quick) - 15} 条", classes="col-more")
                    else:
                        yield Static("暂无记录", classes="col-empty")

                with Vertical(classes="col-panel"):
                    hdr_cls = "col-header --active" if self._col == 1 else "col-header"
                    yield Static("🔬 Deep Dive", id="col-hdr-1", classes=hdr_cls)
                    if self._deep:
                        for i, s in enumerate(self._deep[:15]):
                            hi = (self._col == 1 and i == 0)
                            cls = "session-item --highlight" if hi else "session-item"
                            yield Static(self._fmt(s, 1, i), id=f"d-{i}", classes=cls)
                        if len(self._deep) > 15:
                            yield Static(f"…还有 {len(self._deep) - 15} 条", classes="col-more")
                    else:
                        yield Static("暂无记录", classes="col-empty")

    def _fmt(self, s: dict, col: int, idx: int) -> str:
        unit = "条" if col == 0 else "轮"
        cnt  = s.get('entries', 0)
        date = s['date'][5:]   # MM-DD
        return f"{date}  {s['title'][:26]}  ({cnt}{unit})"

    def _item_id(self, col: int, row: int) -> str:
        return f"q-{row}" if col == 0 else f"d-{row}"

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key in ("up", "down"):
            lst = self._col_list(self._col)
            if not lst:
                return
            n   = min(len(lst), 15)
            old = self._rows[self._col]
            new = (old + (-1 if key == "up" else 1)) % n
            self._rows[self._col] = new
            self.query_one(f"#{self._item_id(self._col, old)}", Static).set_classes("session-item")
            self.query_one(f"#{self._item_id(self._col, new)}", Static).set_classes("session-item --highlight")
        elif key in ("left", "right"):
            target = 1 if key == "right" else 0
            if target == self._col:
                return
            # Unhighlight current
            lst_old = self._col_list(self._col)
            if lst_old:
                row_old = self._rows[self._col]
                self.query_one(f"#{self._item_id(self._col, row_old)}", Static).set_classes("session-item")
            # Update header styles
            self.query_one(f"#col-hdr-{self._col}", Static).set_classes("col-header")
            self._col = target
            self.query_one(f"#col-hdr-{self._col}", Static).set_classes("col-header --active")
            # Highlight new column's current row
            lst_new = self._col_list(self._col)
            if lst_new:
                row_new = self._rows[self._col]
                self.query_one(f"#{self._item_id(self._col, row_new)}", Static).set_classes("session-item --highlight")

    def action_select(self) -> None:
        lst = self._col_list(self._col)
        if lst:
            self.dismiss(lst[self._rows[self._col]])
        else:
            self.dismiss(None)


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_TABS   = 4


def _active_agents(config: dict) -> List[str]:
    return [k for k, v in config.get('ais', {}).items() if v.get('enabled', True)]


def _agent_icon(config: dict, agent: str) -> str:
    return config.get('ais', {}).get(agent, {}).get('icon', '⚪')


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: #0d1117;
    color: #e6edf3;
    overflow-y: hidden;
    overflow-x: hidden;
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

.stream-preview {
    height: auto;
    padding: 0 1;
    color: #6e7681;
    display: none;
}

.stream-preview.--active {
    display: block;
    height: 1fr;
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

    def _on_key(self, event: events.Key) -> None:
        """↑ 键恢复上一条发送的输入；Ctrl+⌫ 清空输入框。"""
        # Ctrl+A 全选
        if event.key == "ctrl+a":
            event.stop()
            event.prevent_default()
            self.select_all()
            return

        if event.key != "up":
            return
        app = self.app
        if not hasattr(app, '_sessions') or not app._active_tab:
            return
        session = app._sessions.get(app._active_tab)
        if not session or not session.last_input:
            return
        event.stop()
        event.prevent_default()
        self.value = session.last_input
        self.cursor_position = len(self.value)

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
        Binding("escape", "quit",            "退出"),
        Binding("/",      "focus_input",    show=False),
        Binding("ctrl+r", "compare",        "互评"),
        Binding("ctrl+y", "copy_panel",     "查看/复制"),
        Binding("ctrl+n", "new_tab",        "新建"),
        Binding("ctrl+w", "close_tab",      "关闭"),
        Binding("ctrl+o", "history",        "历史"),
        Binding("ctrl+t", "toggle_mode",    "切换模式"),
        Binding("ctrl+l", "toggle_layout",  "横竖"),
        Binding("ctrl+1", "switch_tab_n('1')", show=False),
        Binding("ctrl+2", "switch_tab_n('2')", show=False),
        Binding("ctrl+3", "switch_tab_n('3')", show=False),
        Binding("ctrl+4", "switch_tab_n('4')", show=False),
    ]

    def __init__(self, project_root: Path, config: Dict[str, Any],
                 initial_mode: str = "quick", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project_root = project_root
        self.config       = config

        self._agents        = _active_agents(config)
        prompts_dir         = project_root / "prompts"
        self._prompt_loader = PromptLoader(prompts_dir)
        timeout             = config.get("deep", {}).get("timeout_seconds", 60)
        self._cli_caller    = CliCaller(config, timeout=timeout)
        self._history       = History(config, project_root=project_root)

        # Tab state
        self._sessions:     Dict[str, TabSession] = {}
        self._active_tab:   str = ""
        self._tab_counter:  int = 0

        self._cb_queue:      asyncio.Queue = None
        self._paste_buffers: dict = {}
        self._paste_count:   int = 0
        self._image_buffers: dict = {}
        self._image_count:   int = 0
        self._stream_buffers: Dict[str, str] = {}

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Tabs(id="session-tabs")

        with Vertical(id="guest-panels", classes="horizontal"):
            for agent in self._agents:
                icon = _agent_icon(self.config, agent)
                with Vertical(id=f"wrap-{agent}", classes=f"agent-wrap {agent}"):
                    yield Static(f"{icon} {agent.upper()}",
                                 id=f"title-{agent}", classes="agent-title")
                    yield RichLog(id=f"log-{agent}", classes="guest-log",
                                  wrap=True, highlight=False, markup=True, min_width=1)
                    yield Static("", id=f"stream-{agent}", classes="stream-preview")

        with Vertical(id="moderator-wrap"):
            yield Static("🎙 主持人", id="moderator-title")
            yield RichLog(id="moderator-log", wrap=True, highlight=False, markup=True, min_width=1)

        with Horizontal(id="input-row"):
            yield Static("", id="mode-label")
            yield RoundtableInput(id="main-input")
            yield Static(f"v{self.config.get('version', '0.1.0')}", id="version-label")

        yield Footer()

    def on_mount(self) -> None:
        self._cb_queue = asyncio.Queue()
        self.set_interval(0.05, self._process_cb_queue)

        for agent in self._agents:
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

        # quick_file is None for fresh tabs — created lazily on first message
        qm = QuickMode(self.config, self._cli_caller, self._prompt_loader,
                       history=self._history,
                       quick_file=quick_file,
                       active_agents=self._agents) if mode == "quick" else None

        orch = Orchestrator(self.project_root, self.config,
                            history=self._history,
                            active_agents=self._agents) if mode == "deep" else None

        session = TabSession(
            tab_id       = tab_id,
            mode         = mode,
            title        = title,
            quick_mode   = qm,
            orchestrator = orch,
            quick_file   = quick_file,
        )

        # Preload last entries for historical sessions
        if preload_entries and qm:
            for entry in preload_entries:
                qm.history_local.append(entry)
                session.log_entries.append(("history_entry", entry))

        self._sessions[tab_id] = session

        tabs = self.query_one("#session-tabs", Tabs)
        num = len(self._sessions)
        tabs.add_tab(Tab(f"{num}.{title[:15]}", id=tab_id))
        self._switch_to_tab(tab_id)

        return tab_id

    def _switch_to_tab(self, tab_id: str) -> None:
        if tab_id not in self._sessions:
            return

        self._active_tab = tab_id
        session = self._sessions[tab_id]

        # Clear panels
        for agent in self._agents:
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
        neighbour = ids[idx + 1] if idx + 1 < len(ids) else ids[idx - 1]

        tabs.remove_tab(tab_id)
        del self._sessions[tab_id]
        self._renumber_tabs()
        self._switch_to_tab(neighbour)

    def _renumber_tabs(self) -> None:
        """Refresh all tab labels to keep 1-based numbering consistent."""
        tabs = self.query_one("#session-tabs", Tabs)
        for i, (tid, session) in enumerate(self._sessions.items(), start=1):
            try:
                tab = tabs.query_one(f"#{tid}", Tab)
                tab.label = f"{i}.{session.title[:15]}"
            except Exception:
                pass

    def _rename_quick_file(self, title: str, quick_file=None) -> None:
        """Rename 001.md → 001-title.md and update session references."""
        # Find the session that owns this file
        target_session = None
        for session in self._sessions.values():
            if session.quick_file and session.quick_file == quick_file:
                target_session = session
                break
        if target_session is None:
            return
        old_path = target_session.quick_file
        # Guard: only rename plain numbered files (e.g. 001.md)
        if not old_path.stem.isdigit():
            return
        new_path = old_path.parent / f"{old_path.stem}-{title}.md"
        try:
            old_path.rename(new_path)
            target_session.quick_file = new_path
            if target_session.quick_mode:
                target_session.quick_mode.quick_file = new_path
        except Exception:
            pass

    def _update_active_tab_title(self, title: str) -> None:
        session = self._sessions.get(self._active_tab)
        if not session or session.title != "新对话":
            return
        session.title = title[:15]
        try:
            ids = list(self._sessions.keys())
            num = ids.index(self._active_tab) + 1
            tabs = self.query_one("#session-tabs", Tabs)
            tab  = tabs.query_one(f"#{self._active_tab}", Tab)
            tab.label = f"{num}.{title[:15]}"
        except Exception:
            pass

    # ── Event replay ──────────────────────────────────────────────────────────

    def _store_event(self, event_type: str, kwargs: dict) -> None:
        session = self._sessions.get(self._active_tab)
        if session and event_type in (
            "agent_response", "moderator_output", "side_response",
        ):
            session.log_entries.append((event_type, dict(kwargs)))

    def _replay(self, evt: Tuple) -> None:
        event_type, kwargs = evt
        if event_type == "history_entry":
            entry = kwargs  # {question, responses}
            for agent, content in entry.get('responses', {}).items():
                log = self._log(agent)
                log.write("[dim]── 历史 ──[/dim]")
                log.write(_FoldingMarkdown(content))
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
        base  = f"{_agent_icon(self.config, agent)} {agent.upper()}"
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

        elif event_type == "agent_idle":
            if _replay:
                return
            agent   = kwargs.get("agent", "")
            elapsed = int(kwargs.get("elapsed", 0))
            self._set_agent_title(agent, f"⏳ {elapsed}s")

        elif event_type == "agent_stderr":
            if _replay:
                return
            agent = kwargs.get("agent", "")
            line  = kwargs.get("line", "")
            # Filter out known CLI startup banners that are noise, not errors
            _noise = ("yolo mode", "tool calls will be automatically approved",
                      "dangerously skip", "all tool calls")
            if any(n in line.lower() for n in _noise):
                return
            if agent in self._agents:
                w = self.query_one(f"#stream-{agent}", Static)
                w.add_class("--active")
                w.update(f"[dim]{escape(line[:120])}[/dim]")

        elif event_type == "agent_chunk":
            if _replay:
                return
            agent = kwargs.get("agent", "")
            chunk = kwargs.get("chunk", "")
            self._stream_buffers[agent] = self._stream_buffers.get(agent, "") + chunk
            w = self.query_one(f"#stream-{agent}", Static)
            w.add_class("--active")
            w.update(self._stream_buffers[agent][-600:])

        elif event_type == "agent_response":
            agent   = kwargs.get("agent", "")
            content = kwargs.get("content", "")
            role    = kwargs.get("role", "guest")
            rnd     = kwargs.get("round", 0)

            if role == "moderator":
                return

            # Clear stream preview
            if not _replay and agent in self._agents:
                w = self.query_one(f"#stream-{agent}", Static)
                w.remove_class("--active")
                w.update("")
                self._stream_buffers.pop(agent, None)

            log = self._log(agent)
            self._set_agent_title(agent)

            if role == "quick":
                divider = "[dim]── Rapid Fire ──[/dim]"
            elif role == "compare":
                divider = "[dim]── 互评 ──[/dim]"
            else:
                divider = f"[dim]── 轮 {rnd} ──[/dim]"

            log.write(divider)
            log.write(_FoldingMarkdown(content))
            log.write("")


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
            log.write(_FoldingMarkdown(content))
            log.write("")

        elif event_type == "quick_file_ready":
            if not _replay:
                quick_file = kwargs.get("quick_file")
                for session in self._sessions.values():
                    if session.quick_mode and session.quick_mode.quick_file == quick_file:
                        session.quick_file = quick_file
                        break

        elif event_type == "session_title":
            if not _replay:
                title = kwargs.get("title", "")
                quick_file = kwargs.get("quick_file")
                if title:
                    self._update_active_tab_title(title)
                    self._rename_quick_file(title, quick_file)

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
            for agent in self._agents:
                log = self._log(agent)
                log.write("[bold yellow]── 总结 ──[/bold yellow]")
                log.write(_FoldingMarkdown(summary))
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

        # 记录上一条输入（内存中，退出即清除）
        session.last_input = value

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

        if s_type == 'rapid-fire' and fpath:
            entries   = self._history.load_last_entries(Path(fpath), n=3)
            cur       = self._sessions.get(self._active_tab)
            cur_empty = cur and cur.mode == "quick" and not cur.log_entries

            if cur_empty:
                # Reuse current empty tab — no new tab needed
                cur.title      = title[:15]
                cur.quick_file = Path(fpath)
                if cur.quick_mode:
                    cur.quick_mode.quick_file = Path(fpath)
                    for entry in entries:
                        cur.quick_mode.history_local.append(entry)
                        cur.log_entries.append(("history_entry", entry))
                self._renumber_tabs()
                for entry in entries:
                    self._replay(("history_entry", entry))
            else:
                self._create_tab(mode="quick", title=title,
                                 preload_entries=entries, quick_file=Path(fpath))
        elif s_type == 'deep-dive':
            self.notify(f"Deep Dive 仅供查阅：{fpath}", timeout=4)

    def action_switch_tab_n(self, n: str) -> None:
        ids = list(self._sessions.keys())
        idx = int(n) - 1
        if idx < len(ids):
            self._switch_to_tab(ids[idx])
        else:
            self.notify(f"没有第 {n} 个标签页", severity="warning", timeout=1)

    def action_toggle_layout(self) -> None:
        panels = self.query_one("#guest-panels")
        panels.toggle_class("horizontal")
        label = "横向" if "horizontal" in panels.classes else "竖向"
        self.notify(label, timeout=1)
        # Re-render content at new panel width
        self.call_after_refresh(self._switch_to_tab, self._active_tab)

    def action_copy_panel(self) -> None:
        import os
        focused = self.screen.focused
        if not isinstance(focused, RichLog) or not focused.id:
            self.notify("请先点击某个 AI 面板", severity="warning", timeout=2)
            return
        agent = focused.id.replace("log-", "")
        if agent not in self._agents:
            self.notify("请点击 AI 回答面板", severity="warning", timeout=2)
            return

        session = self._sessions.get(self._active_tab)
        parts = []
        if session and session.quick_mode:
            for entry in session.quick_mode.history_local:
                r = entry.get('responses', {}).get(agent, '')
                if r:
                    parts.append(r)
        elif session and session.orchestrator:
            for rnd in session.orchestrator.context_manager.full_rounds:
                r = rnd.get('speeches', {}).get(agent, '')
                if r:
                    parts.append(r)

        if not parts:
            self.notify("暂无内容", timeout=2)
            return

        text = ("\n\n" + "─" * 60 + "\n\n").join(parts)

        def _show():
            import sys, tty, termios
            os.system('clear')
            print(text)
            print("\n" + "─" * 40)
            print("Esc 返回")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

        with self.suspend():
            _show()

    def action_focus_input(self) -> None:
        self.query_one("#main-input", RoundtableInput).focus()

    def action_quit(self) -> None:
        self.exit()

    def action_help_quit(self) -> None:
        self.notify("Press [b]esc[/b] to quit the app", title="Do you want to quit?")

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
