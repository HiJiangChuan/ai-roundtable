# AI Roundtable

**Put Claude, Antigravity (agy), and Codex around the same table.**
**让 Claude、Antigravity（agy）和 Codex 同坐一桌。**

A terminal UI that runs multiple AI assistants side-by-side and lets them debate any topic in real time — in parallel, with no switching between windows.

一个终端界面（TUI），可以并排运行多个 AI 助手，让它们就任何话题实时展开辩论——并行进行，无需在窗口间切换。

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

## 环境要求

You need **at least one** of the following AI CLIs installed and authenticated:

你需要安装并登录以下 AI CLI 中的**至少一个**：

| CLI | Install | Auth |
|-----|---------|------|
| [Claude Code](https://claude.ai/code) | `npm install -g @anthropic-ai/claude-code` | `claude login` |
| [Antigravity CLI (agy)](https://antigravity.ai) | See agy docs | Browser OAuth on first run |
| [Codex CLI](https://github.com/openai/codex) | `npm install -g @openai/codex` | Set `OPENAI_API_KEY` |
| [Kimi CLI](https://github.com/MoonshotAI/kimi-cli) | `uv tool install kimi-cli` | Run `kimi`, then `/login` |

| CLI | 安装 | 认证 |
|-----|------|------|
| [Claude Code](https://claude.ai/code) | `npm install -g @anthropic-ai/claude-code` | `claude login` |
| [Antigravity CLI (agy)](https://antigravity.ai) | 参见 agy 文档 | 首次运行时浏览器 OAuth 授权 |
| [Codex CLI](https://github.com/openai/codex) | `npm install -g @openai/codex` | 设置 `OPENAI_API_KEY` |
| [Kimi CLI](https://github.com/MoonshotAI/kimi-cli) | `uv tool install kimi-cli` | 运行 `kimi`，然后执行 `/login` |

AI Roundtable works with any subset — 1, 2, or all of them. Any missing CLI is skipped automatically (you'll see a notice on startup; disable it in Settings to hide the notice).

AI Roundtable 支持任意子集组合——1 个、2 个或全部启用。缺失的 CLI 会被自动跳过（启动时会有提示，可在设置中关闭该提示）。

---

## Installation

## 安装

```bash
pip install ai-roundtable
```

Then launch from anywhere:

然后在任意位置启动：

```bash
ai-roundtable
```

### From source

### 从源码安装

```bash
git clone https://github.com/HiJiangChuan/ai-roundtable
cd ai-roundtable
python3 -m venv .venv && .venv/bin/pip install -e .
ai-roundtable          # 或 bin/roundtable，或 python -m ai_roundtable
```

---

## Two Modes

## 两种模式

### Quick Round (default)

### 快速轮（默认模式）

All active AIs answer your question **in parallel**. Results appear as they stream in.

所有启用的 AI **并行**回答你的问题，结果流式实时显示。

Best for: quick comparisons, getting multiple perspectives fast, gut-checking an idea.

适用场景：快速对比、快速获取多方视角、快速验证一个想法。

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

**快速轮命令：**

| Input | Action |
|-------|--------|
| Any text | Ask all AIs in parallel |
| `/compare` or `Ctrl+R` | Each AI critiques the others' last answers |
| `Ctrl+T` | Upgrade this question to a Deep Round session (new tab) |

| 输入 | 动作 |
|------|------|
| 任意文本 | 并行向所有 AI 提问 |
| `/compare` 或 `Ctrl+R` | 各 AI 互相点评对方上一次的回答 |
| `Ctrl+T` | 将当前问题升级为深度轮会话（新开标签页） |

---

### Deep Round (`ai-roundtable --deep`)

### 深度轮（`ai-roundtable --deep`）

A structured multi-round debate with a rotating moderator.

一种带有轮值主持人的结构化多轮辩论。

Each round: all AIs speak → moderator (rotating) analyzes contradictions, assigns action types, and drives the next question.

每一轮：所有 AI 发言 → 主持人（轮值）分析分歧、分配行动类型，并推动下一个问题。

**Action types:** Take a position / Rebut / Supplement / Probe / Challenge premise / Synthesize

**行动类型：** 表态 / 反驳 / 补充 / 追问 / 质疑前提 / 综合总结

Best for: complex decisions, architecture debates, exploring a problem space thoroughly.

适用场景：复杂决策、架构辩论、深入探索一个问题空间。

**Deep Round commands:**

**深度轮命令：**

| Input | Action |
|-------|--------|
| Topic text | Start the session (Round 0 opening) |
| `可` | Proceed to next round |
| `止` | End session and generate summary |
| `深入此节` | Stay on current round, dig one level deeper |
| `@claude your question` | Direct question to a specific AI only |
| Any other text | Injected into context as your interjection |

| 输入 | 动作 |
|------|------|
| 话题文本 | 开始会话（第 0 轮开场） |
| `可` | 进入下一轮 |
| `止` | 结束会话并生成总结 |
| `深入此节` | 停留在当前轮，向下深挖一层 |
| `@claude 你的问题` | 仅向指定的 AI 提问 |
| 其他任意文本 | 作为你的插话内容注入上下文 |

With 1 AI enabled, Deep Round runs **solo mode**: the AI invents multiple personas and debates itself.

只启用 1 个 AI 时，深度轮会进入**单人模式**：该 AI 会创造多个角色并与自己辩论。

---

## Keyboard Shortcuts

## 键盘快捷键

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

| 快捷键 | 动作 |
|--------|------|
| `Esc` | 退出（如有任务运行中，会提示改用 `Ctrl+Q`） |
| `Ctrl+Q` | 强制退出（终止所有子进程） |
| `/` | 聚焦输入框 |
| `Ctrl+T` | 快速轮 → 升级为深度轮 / 深度轮 → 新建快速轮标签页 |
| `Ctrl+L` | 切换布局（垂直 ↔ 水平面板） |
| `Ctrl+R` | 互评 —— AI 互相点评 |
| `Ctrl+Y` | 全屏查看面板内容（需先点击某个面板） |
| `Ctrl+N` | 新建标签页 |
| `Ctrl+W` | 关闭当前标签页（取消其运行中的任务） |
| `Ctrl+O` | 打开会话历史 |
| `Ctrl+P` | 设置（AI 开关 / prompt / 存储 / 参数） |
| `Ctrl+V` | 将图片粘贴到问题中 |
| `Ctrl+A` | 全选输入框中的文本 |
| `↑` | 恢复上一次提交的输入内容 |
| `Ctrl+1`–`4` | 切换到标签页 1–4 |

Tabs run **independently in parallel** — ask in tab 1, switch to tab 2 and ask again; a `●` marks tabs with unread answers.

标签页之间**相互独立并行运行**——在标签页 1 提问后，可切换到标签页 2 继续提问；`●` 标记表示该标签页有未读回答。

---

## Configuration

## 配置

On first launch, a config file is created at `~/.config/ai-roundtable/config.yml`. It is deep-merged over the packaged defaults, so options added by new versions reach existing installs automatically.

首次启动时，会在 `~/.config/ai-roundtable/config.yml` 创建配置文件。该文件会与内置默认配置进行深度合并，因此新版本新增的选项会自动同步到已有安装。

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

每个 CLI 的调用方式（参数、流式协议、通过 stdin 传入 prompt）由内置适配器处理——你只需要配置 `cmd` 和可选的额外 `flags`。在 `ais:` 下添加一个未知名称，会使用通用适配器，通过 `prompt_flag` / `subcommand` 字段进行配置。

> **Permissions note:** by default no CLI gets `--dangerously-skip-permissions`. Discussion prompts don't need tool access; add it to `flags` yourself if you want agents to run tools.

> **权限说明：** 默认情况下不会给任何 CLI 添加 `--dangerously-skip-permissions`。讨论类 prompt 不需要工具访问权限；如果你希望 AI 能运行工具，请自行在 `flags` 中添加。

### Disabling an AI

### 禁用某个 AI

Toggle it in Settings (`Ctrl+P`), or set `enabled: false` in the config. AI Roundtable adapts automatically — 2 AIs run pair discussions, 1 AI runs solo roundtable mode.

在设置中（`Ctrl+P`）切换开关，或在配置文件中设置 `enabled: false`。AI Roundtable 会自动适配——2 个 AI 进行双方讨论，1 个 AI 进入单人圆桌模式。

---

## Session History

## 会话历史

The source of truth is JSON under `~/.local/share/ai-roundtable/sessions/`. Every session is **also** exported as Obsidian-ready Markdown (YAML frontmatter + callout blocks):

数据源以 JSON 格式存储在 `~/.local/share/ai-roundtable/sessions/` 下，**同时**每次会话也会导出为可直接用于 Obsidian 的 Markdown（YAML frontmatter + callout 块）：

- **With Obsidian**: `<vault>/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`
- **Without Obsidian**: `~/Documents/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`

- **配置了 Obsidian**：`<vault>/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`
- **未配置 Obsidian**：`~/Documents/ai-roundtable/<Mode>/YYYY-MM-DD/NNN-topic.md`

`Ctrl+O` lists past sessions; Quick Round sessions can be reopened and continued (including sessions created by pre-rewrite versions).

`Ctrl+O` 可列出历史会话；快速轮会话可以重新打开并继续（包括重写前旧版本创建的会话）。

---

## Debugging

## 调试

CLI call logs are written to `~/.local/state/ai-roundtable/cli.log` (rotated at 1 MB):

CLI 调用日志会写入 `~/.local/state/ai-roundtable/cli.log`（达到 1 MB 自动轮转）：

```
[15:35:21] claude  OK        8.6s  211 chars
[15:35:35] agy     OK       22.5s  240 chars
[15:35:38] codex   OK       25.2s  220 chars
```

---

## Project Structure

## 项目结构

```
ai-roundtable/
├── ai_roundtable/
│   ├── main.py              # Entry point: dependency assembly
│   ├── config.py            # Paths (XDG), config load/merge
│   ├── adapters/             # One adapter per CLI + subprocess engine
│   │   ├── engine.py        #   lifecycle: stdin feed, idle notify, kill-safety
│   │   ├── claude.py        #   stream-json protocol
│   │   ├── codex.py         #   exec --json protocol
│   │   ├── agy.py           #   plain-text print mode
│   │   ├── kimi.py          #   print --output-format stream-json
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

```
ai-roundtable/
├── ai_roundtable/
│   ├── main.py              # 入口文件：依赖组装
│   ├── config.py            # 路径解析（XDG）、配置加载与合并
│   ├── adapters/             # 每个 CLI 对应一个适配器 + 子进程引擎
│   │   ├── engine.py        #   生命周期管理：stdin 输入、空闲提示、安全终止
│   │   ├── claude.py        #   stream-json 协议
│   │   ├── codex.py         #   exec --json 协议
│   │   ├── agy.py           #   纯文本 print 模式
│   │   ├── kimi.py          #   print --output-format stream-json
│   │   └── generic.py       #   配置驱动的通用适配器（未知 CLI）
│   ├── core/
│   │   ├── events.py        # 类型化事件（按 session_id 路由）
│   │   ├── quick.py         # 快速轮会话
│   │   ├── deep.py          # 深度轮状态机
│   │   ├── context.py       # 三层上下文压缩
│   │   ├── store.py         # JSON 数据源 + Markdown 导出
│   │   ├── legacy.py        # 重写前旧版会话的只读加载器
│   │   ├── prompts.py       # 模板加载器与渲染约定
│   │   └── parsing.py       # 主持人输出解析
│   ├── tui/                 # Textual 界面（应用 / 设置 / 历史弹窗）
│   └── prompts/             # 默认 prompt 模板
├── tests/                   # pytest 测试套件（单元测试 + FakePool 集成测试 + TUI pilot 测试）
└── pyproject.toml           # 版本号唯一来源
```

Run tests: `.venv/bin/python -m pytest tests/`

运行测试：`.venv/bin/python -m pytest tests/`

---

## License

## 许可证

MIT
