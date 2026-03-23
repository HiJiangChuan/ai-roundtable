# AI Roundtable

让 Claude、Gemini、Codex 围坐一桌，就任意议题展开真正的多轮辩论。

## 效果

```
🔵 CLAUDE                        🟢 GEMINI                        🟡 CODEX
─────────────────────────────    ─────────────────────────────    ──────────────────────────
── 快问 ──                        ── 快问 ──                        ── 快问 ──
大模型的核心竞争力在于推理能力，     我认为数据飞轮才是护城河所在，      工程落地能力被严重低估……
```

## 两种模式

### 快问（默认）
三个 AI **并行**回答同一个问题，适合快速对比不同视角。

- `/compare` — 让三个 AI 互评彼此的回答
- `^t` — 将当前问题升级为深度讨论

### 深度讨论
主持人轮换制（Gemini → Codex → Claude → …），每轮结束后主持人分析矛盾点、分配行动类型，推动讨论深入。

**行动类型**：陈述立场 / 反驳 / 补充 / 追问 / 挑战前提 / 综合

**轮次指令**：
| 输入 | 作用 |
|------|------|
| `可` | 开始下一轮 |
| `止` | 结束会话并生成总结 |
| `深入此节` | 不推进轮次，围绕当前矛盾点再挖一层 |
| `@claude 你的看法？` | 单独问某个 AI |

## 安装

**前置条件**：已安装并登录 `claude`、`gemini`、`codex` CLI。

```bash
git clone https://github.com/yourname/ai-roundtable
cd ai-roundtable
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x bin/roundtable
```

## 使用

```bash
./bin/roundtable          # 快问模式启动
./bin/roundtable --deep   # 直接进入深度讨论
```

**快捷键**：

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+T` | 切换模式 |
| `Ctrl+Y` | 复制当前面板内容（先点击面板） |
| `Ctrl+E` | 导出会话为 Markdown |
| `Ctrl+N` | 新建会话 |
| `Ctrl+Q` | 退出 |

## 配置

`config.yml` 可调整：

```yaml
ais:
  claude:
    cmd: "claude"
    flags: ["--dangerously-skip-permissions"]

deep:
  moderator_rotation: ["gemini", "codex", "claude"]  # 主持人轮换顺序
  speaking_order: ["claude", "codex", "gemini"]       # 嘉宾发言顺序
  full_rounds_kept: 3                                  # 保留完整的最近 N 轮
  timeout_seconds: 30                                  # 每个 AI 的超时时间

history:
  save_dir: "~/.ai-roundtable/history"   # 会话记录保存位置
```

## 会话记录

每次会话自动保存到 `~/.ai-roundtable/history/`，JSON + Markdown 各一份，也可按 `Ctrl+E` 随时导出。

## 项目结构

```
ai-roundtable/
├── bin/roundtable        # 启动脚本
├── config.yml            # 配置文件
├── prompts/              # Prompt 模板
│   ├── opening.md        # 开场（第0轮）
│   ├── guest.md          # 嘉宾发言（深度模式）
│   ├── guest_quick.md    # 嘉宾发言（快问模式）
│   ├── moderator.md      # 主持人综述
│   ├── compare.md        # 互评
│   └── compress.md       # 上下文压缩
├── src/
│   ├── main.py           # 入口
│   ├── tui.py            # 终端界面
│   ├── orchestrator.py   # 深度讨论状态机
│   ├── quick.py          # 快问模式
│   ├── cli_caller.py     # AI CLI 调用
│   ├── context_manager.py# 上下文压缩管理
│   ├── history.py        # 会话历史
│   └── prompt_loader.py  # Prompt 加载渲染
└── requirements.txt
```
