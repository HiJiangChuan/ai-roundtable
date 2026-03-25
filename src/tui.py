"""
AI Roundtable TUI — dual-mode terminal interface.
快问（Quick）：默认，三个 AI 并行答题
深度讨论（Deep）：主持人轮换 / 行动类型系统
"""
import asyncio
import sys
from pathlib import Path
from typing import Dict, Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual.markup import escape
from rich.markdown import Markdown

sys.path.insert(0, str(Path(__file__).parent))
from orchestrator import Orchestrator
from prompt_loader import PromptLoader
from cli_caller import CliCaller
from quick import QuickMode


class RoundtableInput(Input):
    """Input that shows a placeholder token for multi-line pastes."""

    def _on_paste(self, event: events.Paste) -> None:
        text = event.text
        lines = text.splitlines()
        if len(lines) <= 1:
            self.insert_text_at_cursor(text)
        else:
            app = self.app
            app._paste_count += 1
            app._paste_buffers[app._paste_count] = text
            token = f"[Pasted text #{app._paste_count} +{len(lines) - 1} lines]"
            self.insert_text_at_cursor(token)
        event.text = ""  # 父类 _on_paste 也会执行，置空后它不会插入任何内容
        event.stop()


AGENTS = ["claude", "gemini", "codex"]

AGENT_ICON = {"claude": "🔵", "gemini": "🟢", "codex": "🟡"}

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

/* ── guest panels ─────────────────────────────────────────────── */

#guest-panels {
    height: 1fr;
    padding: 1 2 0 2;
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


# ── App ───────────────────────────────────────────────────────────────────────

class RoundtableApp(App):
    TITLE = "AI Roundtable"
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit",        "退出",     priority=True),
        Binding("ctrl+r", "compare",     "互评"),
        Binding("ctrl+y", "copy_panel",  "复制面板"),
        Binding("ctrl+e", "export_md",   "导出MD"),
        Binding("ctrl+n", "new_session", "新建"),
        Binding("ctrl+t", "toggle_mode", "切换模式"),
    ]

    def __init__(self, project_root: Path, config: Dict[str, Any],
                 initial_mode: str = "quick", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project_root = project_root
        self.config = config
        self._mode = initial_mode

        prompts_dir = project_root / "prompts"
        self._prompt_loader = PromptLoader(prompts_dir)
        timeout = config.get("deep", {}).get("timeout_seconds", 30)
        self._cli_caller = CliCaller(config, timeout=timeout)

        self.orchestrator = Orchestrator(project_root, config)
        self.quick_mode = QuickMode(config, self._cli_caller, self._prompt_loader)
        self._cb_queue: asyncio.Queue = None
        self._paste_buffers: dict = {}
        self._paste_count = 0

    # ── layout ────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="guest-panels"):
            for agent in AGENTS:
                with Vertical(id=f"wrap-{agent}", classes=f"agent-wrap {agent}"):
                    yield Static(
                        f"{AGENT_ICON[agent]} {agent.upper()}",
                        id=f"title-{agent}",
                        classes="agent-title",
                    )
                    yield RichLog(
                        id=f"log-{agent}",
                        classes="guest-log",
                        wrap=True, highlight=False, markup=True,
                    )

        with Vertical(id="moderator-wrap"):
            yield Static("🎙 主持人", id="moderator-title")
            yield RichLog(
                id="moderator-log",
                wrap=True, highlight=False, markup=True,
            )

        with Horizontal(id="input-row"):
            yield Static("", id="mode-label")
            yield RoundtableInput(id="main-input")
            yield Static(
                f"v{self.config.get('version', '0.1.0')}",
                id="version-label",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._cb_queue = asyncio.Queue()
        self.set_interval(0.05, self._process_cb_queue)

        for agent in AGENTS:
            self.query_one(f"#log-{agent}", RichLog).can_focus = True
        self.query_one("#moderator-log", RichLog).can_focus = True

        self._apply_mode_ui()
        self.query_one("#main-input", RoundtableInput).focus()

    # ── helpers ───────────────────────────────────────────────────

    def _log(self, agent: str) -> RichLog:
        return self.query_one(f"#log-{agent}", RichLog)

    def _mod_log(self) -> RichLog:
        return self.query_one("#moderator-log", RichLog)

    def _set_agent_title(self, agent: str, suffix: str = "") -> None:
        title = self.query_one(f"#title-{agent}", Static)
        base = f"{AGENT_ICON[agent]} {agent.upper()}"
        title.update(f"{base} {suffix}".strip())

    def _apply_mode_ui(self) -> None:
        mod_wrap = self.query_one("#moderator-wrap")
        label = self.query_one("#mode-label", Static)
        inp = self.query_one("#main-input", RoundtableInput)

        if self._mode == "quick":
            mod_wrap.display = False
            label.update("[dim]快问 ›[/dim]")
            inp.placeholder = "输入问题…  /compare 互评  ^t 升级深度讨论"
        else:
            mod_wrap.display = True
            rnd = self.orchestrator.round_num
            label.update(f"[dim]深度 轮{rnd + 1} ›[/dim]")
            inp.placeholder = "可 · 止 · 深入此节 · @claude …"

        inp.disabled = False

    def _set_busy(self, busy: bool) -> None:
        inp = self.query_one("#main-input", RoundtableInput)
        label = self.query_one("#mode-label", Static)
        if busy:
            inp.disabled = True
            label.update("[dim yellow]⟳[/dim yellow]")
        else:
            inp.disabled = False
            self._apply_mode_ui()
            inp.focus()

    # ── callback queue ────────────────────────────────────────────

    def _callback(self, event_type: str, **kwargs) -> None:
        if self._cb_queue is not None:
            self._cb_queue.put_nowait((event_type, kwargs))

    async def _process_cb_queue(self) -> None:
        try:
            while True:
                event_type, kwargs = self._cb_queue.get_nowait()
                try:
                    self._handle_event(event_type, **kwargs)
                except Exception:
                    pass
        except asyncio.QueueEmpty:
            pass

    def _handle_event(self, event_type: str, **kwargs) -> None:
        if event_type == "agent_start":
            agent = kwargs.get("agent", "")
            role  = kwargs.get("role", "guest")
            rnd   = kwargs.get("round", 0)
            if role == "moderator":
                self.query_one("#moderator-title", Static).update(
                    f"🎙 {agent.upper()} 主持  [dim]轮 {rnd}[/dim]"
                )
            else:
                self._set_agent_title(agent, "⟳")

        elif event_type == "agent_response":
            agent   = kwargs.get("agent", "")
            content = kwargs.get("content", "")
            role    = kwargs.get("role", "guest")
            rnd     = kwargs.get("round", 0)

            if role == "moderator":
                return  # content shown via moderator_output

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

        elif event_type == "moderator_output":
            moderator = kwargs.get("moderator", "")
            rnd       = kwargs.get("round", 0)
            parsed    = kwargs.get("parsed", {})

            self.query_one("#moderator-title", Static).update(
                f"🎙 {moderator.upper()} 主持  [dim]轮 {rnd}[/dim]"
            )
            mod = self._mod_log()
            mod.clear()

            lines = []
            if "矛盾点" in parsed:
                lines.append(f"[bold yellow]矛盾点[/bold yellow]  {escape(parsed['矛盾点'])}")
            if "下一问" in parsed:
                lines.append(f"[bold cyan]下一问[/bold cyan]  {escape(parsed['下一问'])}")
            if "行动分配" in parsed:
                compact = "  ".join(
                    l.strip() for l in parsed["行动分配"].split("\n") if l.strip()
                )
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
            message = kwargs.get("message", "")
            state   = kwargs.get("state", "")

            if state == "running":
                self._set_busy(True)
            elif state in ("waiting", "quick"):
                self._set_busy(False)
                if self._mode == "deep":
                    rnd = self.orchestrator.round_num
                    self.query_one("#mode-label", Static).update(
                        f"[dim]深度 轮{rnd + 1} ›[/dim]"
                    )
            elif state == "ended":
                inp = self.query_one("#main-input", RoundtableInput)
                inp.disabled = True
                inp.placeholder = "会话已结束  Ctrl+N 新建"
                self.query_one("#mode-label", Static).update("[dim]结束[/dim]")

            if message:
                self.notify(message, timeout=3)

        elif event_type == "session_end":
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
            self.notify(kwargs.get("message", "未知错误"), severity="error", timeout=5)

    # ── input ─────────────────────────────────────────────────────

    def _expand_paste_tokens(self, text: str) -> str:
        import re
        def _replace(m):
            return self._paste_buffers.get(int(m.group(1)), m.group(0))
        return re.sub(r'\[Pasted text #(\d+) \+\d+ lines\]', _replace, text)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = self._expand_paste_tokens(event.value.strip())
        if not value:
            return
        self.query_one("#main-input", RoundtableInput).value = ""
        self._paste_buffers.clear()

        if self._mode == "quick":
            if value == "/compare":
                self._run_compare()
            else:
                self._run_quick(value)
        else:
            state = self.orchestrator.state
            if state == "idle":
                self._run_start(value)
            elif state == "waiting":
                self._run_command(value)
            elif state == "ended":
                self.notify("会话已结束，按 Ctrl+N 新建", timeout=3)

    # ── actions ───────────────────────────────────────────────────

    async def action_toggle_mode(self) -> None:
        if self._mode == "quick":
            if not self.quick_mode.history:
                self.notify("请先提问再升级到深度讨论", severity="warning", timeout=3)
                return
            last = self.quick_mode.get_context_for_deep()
            self._mode = "deep"
            self._apply_mode_ui()
            self._run_upgrade_to_deep(last.get("question", ""), last)
        else:
            self._mode = "quick"
            self._apply_mode_ui()
            self.notify("已切换到快问模式", timeout=2)

    def action_compare(self) -> None:
        if self._mode != "quick":
            self.notify("互评仅在 Rapid Fire 模式下可用", severity="warning", timeout=3)
            return
        if not self.quick_mode.history:
            self.notify("请先提问，再发起互评", severity="warning", timeout=3)
            return
        self._run_compare()

    def action_export_md(self) -> None:
        sid = self.orchestrator._session_id
        if not sid:
            self.notify("没有进行中的会话", severity="warning", timeout=3)
            return
        try:
            path = self.orchestrator.history.export_md(sid)
            self.notify(f"已导出 → {path}", timeout=4)
        except Exception as e:
            self.notify(f"导出失败: {e}", severity="error", timeout=5)

    def action_new_session(self) -> None:
        if self._mode == "deep" and self.orchestrator.state not in ("idle", "ended"):
            self.notify("再按一次 Ctrl+N 确认新建（当前会话将丢失）", severity="warning", timeout=4)
            return

        for agent in AGENTS:
            self._log(agent).clear()
            self.query_one(f"#title-{agent}", Static).update(
                f"{AGENT_ICON[agent]} {agent.upper()}"
            )

        self._mod_log().clear()
        self.query_one("#moderator-title", Static).update("🎙 主持人")

        self._mode = "quick"
        self.orchestrator = Orchestrator(self.project_root, self.config)
        self.quick_mode.reset()

        self._apply_mode_ui()
        self.query_one("#main-input", RoundtableInput).value = ""
        self.query_one("#main-input", RoundtableInput).focus()

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

    # ── workers ───────────────────────────────────────────────────

    @work(exclusive=True)
    async def _run_quick(self, question: str) -> None:
        self._callback("status", message="", state="running")
        try:
            await self.quick_mode.run_question(question, self._callback)
        except Exception as e:
            self._callback("error", message=f"快问失败: {e}")
        finally:
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_compare(self) -> None:
        self._callback("status", message="", state="running")
        try:
            await self.quick_mode.run_compare(self._callback)
        except Exception as e:
            self._callback("error", message=f"互评失败: {e}")
        finally:
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_upgrade_to_deep(self, topic: str, quick_context: dict) -> None:
        try:
            await self.orchestrator.init_from_quick(topic, quick_context, self._callback)
        except Exception as e:
            self._callback("error", message=f"升级失败: {e}")
            self._mode = "quick"
            self._apply_mode_ui()

    @work(exclusive=True)
    async def _run_start(self, topic: str) -> None:
        try:
            await self.orchestrator.start_session(topic, self._callback)
        except Exception as e:
            self._callback("error", message=f"开场失败: {e}")
            self.orchestrator._state = "idle"
            self._callback("status", message="", state="quick")

    @work(exclusive=True)
    async def _run_command(self, value: str) -> None:
        try:
            await self.orchestrator.handle_command(value, self._callback)
        except Exception as e:
            self._callback("error", message=f"执行失败: {e}")
            self.orchestrator._state = "waiting"
            self._callback("status", message="", state="waiting")
