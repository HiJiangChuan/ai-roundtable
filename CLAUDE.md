# CLAUDE.md — AI Roundtable 项目协作规则

## 版本号规则

格式：`Major.Minor.Build`，存储在 `config.yml` 的 `version` 字段。

- **Build**：每次 git push 前自动 +1，由 Claude 负责
- **Minor / Major**：由用户决定何时升级

## 项目结构

- `src/tui.py` — TUI 主界面（Textual）
- `src/quick.py` — Rapid Fire 模式逻辑
- `src/orchestrator.py` — Deep Dive 模式编排
- `config.yml` — 配置文件，含版本号
- `prompts/` — Prompt 模板
