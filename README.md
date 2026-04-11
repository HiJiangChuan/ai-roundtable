# AI Roundtable

**Put Claude, Gemini, and Codex around the same table.**

A terminal UI that runs multiple AI assistants side-by-side and lets them debate any topic in real time — in parallel, with no switching between windows.

```
🔵 CLAUDE                     🟢 GEMINI                     🟡 CODEX
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
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` | `gemini auth` |
| [Codex CLI](https://github.com/openai/codex) | `npm install -g @openai/codex` | Set `OPENAI_API_KEY` |

AI Roundtable works with 1, 2, or all 3. Any missing CLI is simply skipped.

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
ai-roundtable
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

🟢 GEMINI  →  Operational overhead is underestimated. Teams often
               migrate to microservices without the tooling to...

🟡 CODEX   →  Data consistency. Once you split the database, every
               cross-service transaction becomes a distributed...
```

**Quick Round commands:**

| Input | Action |
|-------|--------|
| Any text | Ask all AIs in parallel |
| `Ctrl+R` | Each AI critiques the others' last answers |
| `Ctrl+T` | Upgrade this question to a Deep Round session |

---

### Deep Round (`ai-roundtable --deep`)

A structured multi-round debate with a rotating moderator.

Each round: all AIs speak → moderator (rotating: Gemini → Codex → Claude → …) analyzes contradictions, assigns action types, and drives the next question.

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

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Esc` | Quit |
| `/` | Focus input box |
| `Ctrl+T` | Toggle mode (Quick Round ↔ Deep Round) |
| `Ctrl+L` | Toggle layout (vertical ↔ horizontal panels) |
| `Ctrl+R` | Peer review — AIs critique each other |
| `Ctrl+Y` | View panel content full-screen (click a panel first) |
| `Ctrl+N` | New tab |
| `Ctrl+W` | Close current tab |
| `Ctrl+O` | Open session history |
| `Ctrl+V` | Paste image into question |
| `Ctrl+A` | Select all text in input box |
| `↑` | Restore last submitted input |
| `Ctrl+1`–`4` | Switch to tab 1–4 |

---

## Configuration

On first launch, a config file is created at `~/.config/ai-roundtable/config.yml`.

```yaml
ais:
  claude:
    cmd: "claude"
    prompt_flag: "-p"
    flags: ["--dangerously-skip-permissions"]
    timeout: 600   # Claude deep thinking can take up to 10 min
    # enabled: false  ← uncomment to disable this AI

  gemini:
    cmd: "gemini"
    prompt_flag: "-p"
    flags: ["--yolo"]
    timeout: 300

  codex:
    cmd: "codex"
    subcommand: "exec"
    flags: []
    timeout: 300

deep:
  full_rounds_kept: 3      # Full rounds kept in context window
  compress_summary_max: 80  # Max chars per compressed round summary
  timeout_seconds: 60       # Per-AI timeout for Deep Round rounds

history:
  obsidian_vault: ""        # Path to your Obsidian vault, e.g. ~/notes
                            # Leave empty to save to ~/Documents/ai-roundtable/
```

### Disabling an AI

If you don't have Codex installed, add `enabled: false`:

```yaml
ais:
  codex:
    enabled: false
```

AI Roundtable adapts automatically — with 2 AIs it runs pair discussions, with 1 AI it uses a solo roundtable mode where the AI invents multiple personas and debates itself.

---

## Session History

Every session is automatically saved as Markdown. Files are written to:

- **With Obsidian**: `<vault>/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`
- **Without Obsidian**: `~/Documents/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`

Where `<Mode>` is `Quick Round` or `Deep Round`.

Each file includes YAML frontmatter (date, type, tags) and is formatted with Obsidian callout blocks, ready to view in your vault immediately.

---

## Debugging

CLI call logs are written to `~/.ai-roundtable/cli.log`:

```
[15:35:21] claude  OK        8.6s  211 chars (stream)
[15:35:35] gemini  OK       22.5s  240 chars (stream)
[15:35:38] codex   OK       25.2s  220 chars (stream)
```

---

## Project Structure

```
ai-roundtable/
├── src/
│   ├── main.py             # Entry point, config/path resolution
│   ├── tui.py              # Terminal UI (Textual)
│   ├── quick.py            # Quick Round mode logic
│   ├── orchestrator.py     # Deep Round state machine
│   ├── cli_caller.py       # AI CLI subprocess runner + streaming
│   ├── context_manager.py  # 3-layer context compression
│   ├── history.py          # Session persistence (Markdown + Obsidian)
│   ├── prompt_loader.py    # Prompt template loader
│   └── prompts/
│       ├── guest_quick.md       # Quick Round prompt
│       ├── compare.md           # Peer review prompt
│       ├── guest.md             # Deep Round guest prompt
│       ├── opening.md           # Session opening (Round 0)
│       ├── moderator.md         # Moderator synthesis prompt
│       ├── compress.md          # Context compression prompt
│       └── solo_roundtable.md  # Single-AI roundtable prompt
├── config.yml              # Default config (source mode)
├── pyproject.toml
└── requirements.txt
```

---

## License

MIT
