# AI Roundtable

**Put Claude, Antigravity (agy), and Codex around the same table.**

A terminal UI that runs multiple AI assistants side-by-side and lets them debate any topic in real time — in parallel, with no switching between windows.

```
🔵 CLAUDE                     🟢 AGY                        🟡 CODEX
──────────────────────────    ──────────────────────────    ──────────────────────────
── Quick Round ──             ── Quick Round ──             ── Quick Round ──

The core moat for LLMs is    Data flywheels matter more    Engineering execution is
reasoning capability. A       than model quality — the      underrated. The teams that
model that thinks better      companies accumulating the     ship fastest learn fastest,
will always outperform one    best proprietary datasets      regardless of which model
that has more data but less   will dominate long-term.      they use.
coherent output.
```

---

## Requirements

You need **at least one** of the following AI CLIs installed and authenticated:

| CLI | Install | Auth |
|-----|---------|------|
| [Claude Code](https://claude.ai/code) | `npm install -g @anthropic-ai/claude-code` | `claude login` |
| [Antigravity CLI (agy)](https://antigravity.ai) | See agy docs | Browser OAuth on first run |
| [Codex CLI](https://github.com/openai/codex) | `npm install -g @openai/codex` | Set `OPENAI_API_KEY` |

AI Roundtable works with 1, 2, or all 3. Any missing CLI is skipped automatically (you'll see a notice on startup; disable it in Settings to hide the notice).

---

## Installation

```bash
pip install ai-roundtable
```

Then launch from anywhere:

```bash
ai-roundtable
```

### From source

```bash
git clone https://github.com/HiJiangChuan/ai-roundtable
cd ai-roundtable
python3 -m venv .venv && .venv/bin/pip install -e .
ai-roundtable          # 或 bin/roundtable，或 python -m ai_roundtable
```

---

## Two Modes

### Quick Round (default)

All active AIs answer your question **in parallel**. Results appear as they stream in.

Best for: quick comparisons, getting multiple perspectives fast, gut-checking an idea.

```
You: What's the biggest risk in microservices architecture?

🔵 CLAUDE  →  Distributed systems complexity: when a service call
               fails, tracing the root cause across 12 services...

🟢 AGY     →  Operational overhead is underestimated. Teams often
               migrate to microservices without the tooling to...

🟡 CODEX   →  Data consistency. Once you split the database, every
               cross-service transaction becomes a distributed...
```

**Quick Round commands:**

| Input | Action |
|-------|--------|
| Any text | Ask all AIs in parallel |
| `/compare` or `Ctrl+R` | Each AI critiques the others' last answers |
| `Ctrl+T` | Upgrade this question to a Deep Round session (new tab) |

---

### Deep Round (`ai-roundtable --deep`)

A structured multi-round debate with a rotating moderator.

Each round: all AIs speak → moderator (rotating) analyzes contradictions, assigns action types, and drives the next question.

**Action types:** Take a position / Rebut / Supplement / Probe / Challenge premise / Synthesize

Best for: complex decisions, architecture debates, exploring a problem space thoroughly.

**Deep Round commands:**

| Input | Action |
|-------|--------|
| Topic text | Start the session (Round 0 opening) |
| `可` | Proceed to next round |
| `止` | End session and generate summary |
| `深入此节` | Stay on current round, dig one level deeper |
| `@claude your question` | Direct question to a specific AI only |
| Any other text | Injected into context as your interjection |

With 1 AI enabled, Deep Round runs **solo mode**: the AI invents multiple personas and debates itself.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Esc` | Quit (asks for `Ctrl+Q` if tasks are running) |
| `Ctrl+Q` | Force quit (kills all child processes) |
| `/` | Focus input box |
| `Ctrl+T` | Quick Round → upgrade to Deep / Deep → new Quick tab |
| `Ctrl+L` | Toggle layout (vertical ↔ horizontal panels) |
| `Ctrl+R` | Peer review — AIs critique each other |
| `Ctrl+Y` | View panel content full-screen (click a panel first) |
| `Ctrl+N` | New tab |
| `Ctrl+W` | Close current tab (cancels its running tasks) |
| `Ctrl+O` | Open session history |
| `Ctrl+P` | Settings (AI toggles / prompts / storage / params) |
| `Ctrl+V` | Paste image into question |
| `Ctrl+A` | Select all text in input box |
| `↑` | Restore last submitted input |
| `Ctrl+1`–`4` | Switch to tab 1–4 |

Tabs run **independently in parallel** — ask in tab 1, switch to tab 2 and ask again; a `●` marks tabs with unread answers.

---

## Configuration

On first launch, a config file is created at `~/.config/ai-roundtable/config.yml`. It is deep-merged over the packaged defaults, so options added by new versions reach existing installs automatically.

```yaml
ais:
  claude:
    cmd: "claude"        # 可执行名或绝对路径
    icon: "🔵"
    color: "blue"        # 面板配色：blue/green/yellow/red/purple/cyan/orange
    callout: "note"      # Obsidian callout 类型
    enabled: true
    # flags: [...]       # 追加到命令行的自定义参数（默认为空）

quick:
  context_entries: 5     # 追问时携带最近几条问答
  answer_snippet: 500    # 上下文中每条历史回答保留的最大字数

deep:
  full_rounds_kept: 3       # 完整保留最近几轮
  compress_summary_max: 80  # 每轮压缩摘要最大字数

limits:
  idle_notify_seconds: 25      # 无输出提示（只提示，不杀进程）
  safety_timeout_seconds: 900  # 绝对兜底超时

history:
  obsidian_vault: ""     # Obsidian vault 路径；留空存 ~/Documents/ai-roundtable/
```

How each CLI is invoked (arguments, streaming protocol, prompt via stdin) is handled by built-in adapters — you only configure `cmd` and optional extra `flags`. Adding an unknown name under `ais:` uses a generic adapter with `prompt_flag` / `subcommand` keys.

> **Permissions note:** by default no CLI gets `--dangerously-skip-permissions`. Discussion prompts don't need tool access; add it to `flags` yourself if you want agents to run tools.

### Disabling an AI

Toggle it in Settings (`Ctrl+P`), or set `enabled: false` in the config. AI Roundtable adapts automatically — 2 AIs run pair discussions, 1 AI runs solo roundtable mode.

---

## Session History

The source of truth is JSON under `~/.local/share/ai-roundtable/sessions/`. Every session is **also** exported as Obsidian-ready Markdown (YAML frontmatter + callout blocks):

- **With Obsidian**: `<vault>/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`
- **Without Obsidian**: `~/Documents/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`

`Ctrl+O` lists past sessions; Quick Round sessions can be reopened and continued (including sessions created by pre-rewrite versions).

---

## Debugging

CLI call logs are written to `~/.local/state/ai-roundtable/cli.log` (rotated at 1 MB):

```
[15:35:21] claude  OK        8.6s  211 chars
[15:35:35] agy     OK       22.5s  240 chars
[15:35:38] codex   OK       25.2s  220 chars
```

---

## Project Structure

```
ai-roundtable/
├── ai_roundtable/
│   ├── main.py              # Entry point: dependency assembly
│   ├── config.py            # Paths (XDG), config load/merge
│   ├── adapters/            # One adapter per CLI + subprocess engine
│   │   ├── engine.py        #   lifecycle: stdin feed, idle notify, kill-safety
│   │   ├── claude.py        #   stream-json protocol
│   │   ├── codex.py         #   exec --json protocol
│   │   ├── agy.py           #   plain-text print mode
│   │   └── generic.py       #   config-driven unknown CLIs
│   ├── core/
│   │   ├── events.py        # Typed events (session_id-routed)
│   │   ├── quick.py         # Quick Round session
│   │   ├── deep.py          # Deep Round state machine
│   │   ├── context.py       # 3-layer context compression
│   │   ├── store.py         # JSON source of truth + Markdown export
│   │   ├── legacy.py        # Read-only loader for pre-rewrite sessions
│   │   ├── prompts.py       # Template loader + render contracts
│   │   └── parsing.py       # Moderator output parsing
│   ├── tui/                 # Textual UI (app / settings / history modal)
│   └── prompts/             # Default prompt templates
├── tests/                   # pytest suite (unit + FakePool integration + TUI pilot)
└── pyproject.toml           # single source of version
```

Run tests: `.venv/bin/python -m pytest tests/`

---

## License

MIT
