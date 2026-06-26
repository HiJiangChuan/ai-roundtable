#!/usr/bin/env python3
"""AI Roundtable TUI — Three AI agents in parallel deliberation rounds."""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from rich.markup import escape

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

# ── Paths ──────────────────────────────────────────────────────────────────────

SESSIONS_DIR = Path.home() / ".ai-roundtable" / "sessions"
CURRENT_FILE = Path.home() / ".ai-roundtable" / "current"

# ── Agent config ───────────────────────────────────────────────────────────────

AGENTS = ["claude", "agy", "codex"]

ICONS = {"claude": "🔵", "agy": "🟢", "codex": "🟡"}
COLORS = {"claude": "blue", "agy": "green", "codex": "yellow"}

SYSTEM_PROMPTS = {
    "claude": (
        "You are the Architecture & Risk Analyst in a multi-agent deliberation. "
        "Focus on system design, trade-offs, scalability concerns, and potential risks. "
        "Be concise and structured."
    ),
    "agy": (
        "You are the Exploration & Alternatives Specialist in a multi-agent deliberation. "
        "Explore different approaches, creative alternatives, and unconventional ideas. "
        "Be comprehensive and think outside the box."
    ),
    "codex": (
        "You are the Engineering Implementation Expert in a multi-agent deliberation. "
        "Focus on concrete code, implementation details, practical solutions, and tooling. "
        "Be specific and actionable."
    ),
}

# ── Prompt building ────────────────────────────────────────────────────────────

def build_prompt(agent: str, history: list, user_message: str) -> str:
    parts = [f"[System Role]\n{SYSTEM_PROMPTS[agent]}\n"]

    for i, rnd in enumerate(history):
        parts.append(f"\n{'─'*60}")
        parts.append(f"Round {i + 1} — User: {rnd['user']}\n")
        for ag in AGENTS:
            icon = ICONS[ag]
            resp = rnd["responses"].get(ag, "(no response)")
            parts.append(f"{icon} {ag.upper()}:\n{resp}\n")

    parts.append(f"\n{'─'*60}")
    parts.append(f"New — User: {user_message}\n")
    parts.append(f"Your response as {agent.upper()} (be concise):")

    return "\n".join(parts)


# ── Agent runner ───────────────────────────────────────────────────────────────

async def run_agent(agent: str, prompt: str) -> str:
    try:
        if agent == "claude":
            cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
        elif agent == "agy":
            cmd = ["agy", "--print", prompt, "--dangerously-skip-permissions"]
        elif agent == "codex":
            cmd = ["codex", "exec", prompt]
        else:
            return f"[Error] Unknown agent: {agent}"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode().strip()
            return f"[Error] {err or 'Command failed (exit {proc.returncode})'}"

        return stdout.decode().strip() or "(empty response)"

    except FileNotFoundError:
        return f"[Error] `{agent}` CLI not found in PATH"
    except Exception as exc:
        return f"[Error] {exc}"


# ── Session helpers ────────────────────────────────────────────────────────────

def load_or_create_session() -> dict:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if CURRENT_FILE.exists():
        sid = CURRENT_FILE.read_text().strip()
        path = SESSIONS_DIR / f"{sid}.json"
        if path.exists():
            try:
                session = json.loads(path.read_text())
                # Validate expected schema; start fresh if incompatible
                if session.get("rounds") and "user" not in session["rounds"][0]:
                    raise ValueError("incompatible schema")
                return session
            except (ValueError, KeyError, TypeError):
                pass
    session = {"id": str(uuid.uuid4()), "created": datetime.now().isoformat(), "rounds": []}
    save_session(session)
    return session


def save_session(session: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (SESSIONS_DIR / f"{session['id']}.json").write_text(
        json.dumps(session, indent=2, ensure_ascii=False)
    )
    CURRENT_FILE.write_text(session["id"])


def export_session(session: dict, output: str = "") -> Path:
    sid_short = session["id"][:8]
    path = Path(output) if output else Path(f"roundtable-{sid_short}.md")
    lines = [
        f"# AI Roundtable Session\n",
        f"**Session:** `{session['id']}`  \n**Created:** {session['created']}\n",
        "---\n",
    ]
    for i, rnd in enumerate(session["rounds"]):
        lines.append(f"## Round {i + 1}\n\n**User:** {rnd['user']}\n")
        for ag in AGENTS:
            icon = ICONS[ag]
            resp = rnd["responses"].get(ag, "")
            lines.append(f"### {icon} {ag.upper()}\n\n{resp}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── TUI App ────────────────────────────────────────────────────────────────────

class RoundtableApp(App):
    """AI Roundtable — three agents, one terminal."""

    TITLE = "AI Roundtable"

    CSS = """
    Screen {
        layout: vertical;
    }

    #panels {
        height: 1fr;
    }

    .agent-panel {
        width: 1fr;
        layout: vertical;
    }

    #agy-panel {
        border-left: vkey $surface-darken-3;
        border-right: vkey $surface-darken-3;
    }

    .agent-title {
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $surface-darken-2;
        color: $text;
    }

    .agent-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        background: $surface-darken-2;
        color: $text-muted;
    }

    #input-row {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        border-top: vkey $surface-darken-3;
    }

    #round-prefix {
        width: auto;
        content-align: left middle;
        padding: 0 1 0 0;
        color: $text-muted;
    }

    #user-input {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+e", "export_md", "Export"),
        Binding("ctrl+n", "new_session", "New session"),
    ]

    def __init__(self, session: dict = None):
        super().__init__()
        self.session = session or load_or_create_session()
        self.round_num = len(self.session["rounds"])
        self.busy = False

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="panels"):
            for agent in AGENTS:
                icon = ICONS[agent]
                with Vertical(classes="agent-panel", id=f"{agent}-panel"):
                    yield Label(
                        f"{icon} {agent.upper()}",
                        classes="agent-title",
                        id=f"{agent}-title",
                    )
                    yield RichLog(
                        id=f"{agent}-log",
                        classes="agent-log",
                        wrap=True,
                        markup=True,
                        highlight=False,
                    )
        yield Static(self._status_text(), id="status-bar")
        with Horizontal(id="input-row"):
            yield Static(self._prefix_text(), id="round-prefix")
            yield Input(
                placeholder="输入问题… (Enter 发送)",
                id="user-input",
            )
        yield Footer()

    def on_mount(self) -> None:
        self._restore_history()
        self.query_one("#user-input", Input).focus()

    # ── History restore ─────────────────────────────────────────────────────────

    def _restore_history(self) -> None:
        for i, rnd in enumerate(self.session["rounds"]):
            for agent in AGENTS:
                log = self.query_one(f"#{agent}-log", RichLog)
                self._write_round_header(log, i + 1, rnd["user"])
                log.write(escape(rnd["responses"].get(agent, "(no response)")))
                log.write("")

    # ── Input handler ───────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        msg = event.value.strip()
        if not msg or self.busy:
            return
        event.input.clear()
        self.busy = True
        self._dispatch(msg)

    # ── Worker ─────────────────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _dispatch(self, user_message: str) -> None:
        round_num = self.round_num + 1

        # Show user message in all panels, set titles to loading
        for agent in AGENTS:
            log = self.query_one(f"#{agent}-log", RichLog)
            self._write_round_header(log, round_num, user_message)
            title = self.query_one(f"#{agent}-title", Label)
            title.update(f"{ICONS[agent]} {agent.upper()} [yellow]…[/yellow]")

        self.query_one("#status-bar", Static).update(
            f"[yellow]轮 {round_num} · 请求中…[/yellow]"
        )

        history = self.session["rounds"]

        async def process(agent: str) -> str:
            prompt = build_prompt(agent, history, user_message)
            response = await run_agent(agent, prompt)

            # Update panel as soon as this agent responds
            log = self.query_one(f"#{agent}-log", RichLog)
            color = COLORS[agent]
            log.write(escape(response))
            log.write("")

            title = self.query_one(f"#{agent}-title", Label)
            title.update(f"{ICONS[agent]} {agent.upper()}")
            return response

        results = await asyncio.gather(*[process(ag) for ag in AGENTS])
        responses = dict(zip(AGENTS, results))

        # Persist
        self.session["rounds"].append(
            {"round": round_num, "user": user_message, "responses": responses}
        )
        save_session(self.session)
        self.round_num = round_num
        self.busy = False

        self.query_one("#status-bar", Static).update(self._status_text())
        self.query_one("#round-prefix", Static).update(self._prefix_text())

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_export_md(self) -> None:
        path = export_session(self.session)
        self.notify(f"Exported → {path}", severity="information", timeout=4)

    def action_new_session(self) -> None:
        if CURRENT_FILE.exists():
            CURRENT_FILE.unlink()
        self.session = load_or_create_session()
        self.round_num = 0
        for agent in AGENTS:
            self.query_one(f"#{agent}-log", RichLog).clear()
        self.query_one("#status-bar", Static).update(self._status_text())
        self.query_one("#round-prefix", Static).update(self._prefix_text())
        self.notify("New session started", timeout=2)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _status_text(self) -> str:
        sid = self.session["id"][:8]
        return f"Session {sid}  ·  {self.round_num} rounds"

    def _prefix_text(self) -> str:
        return f"[轮 {self.round_num + 1}]"

    @staticmethod
    def _write_round_header(log: RichLog, round_num: int, user_message: str) -> None:
        log.write(f"[dim]{'─' * 40}[/dim]")
        log.write(f"[bold]轮 {round_num}[/bold]  [cyan]{escape(user_message)}[/cyan]")


# ── CLI entry point ────────────────────────────────────────────────────────────

def cmd_status() -> None:
    if not CURRENT_FILE.exists():
        print("No active session.")
        return
    sid = CURRENT_FILE.read_text().strip()
    path = SESSIONS_DIR / f"{sid}.json"
    if not path.exists():
        print(f"Session file missing: {path}")
        return
    session = json.loads(path.read_text())
    print(f"Session : {session['id']}")
    print(f"Created : {session['created']}")
    print(f"Rounds  : {len(session['rounds'])}")


def cmd_export(args: list) -> None:
    if not CURRENT_FILE.exists():
        print("No active session.")
        return
    sid = CURRENT_FILE.read_text().strip()
    session = json.loads((SESSIONS_DIR / f"{sid}.json").read_text())
    path = export_session(session, args[0] if args else "")
    print(f"Exported to {path}")


def main() -> None:
    argv = sys.argv[1:]

    if not argv or argv[0] in ("tui", "start"):
        RoundtableApp().run()

    elif argv[0] == "new":
        if CURRENT_FILE.exists():
            CURRENT_FILE.unlink()
        RoundtableApp().run()

    elif argv[0] == "status":
        cmd_status()

    elif argv[0] == "export":
        cmd_export(argv[1:])

    else:
        print(f"Unknown command: {argv[0]}")
        print("Usage: roundtable [tui|new|status|export [file.md]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
