# CLAUDE.md — AI Roundtable 项目协作规则

## 版本号规则

单一来源：`pyproject.toml` 的 `version` 字段（`Major.Minor.Build`）。

- **Build**：每次 git push 前自动 +1，由 Claude 负责
- **Minor / Major**：由用户决定何时升级
- 运行时通过 `ai_roundtable.__version__` 读取；配置文件不再存版本号
- push 到 main 即触发 CI 发布 PyPI（版本号已存在则跳过）

## 项目结构

- `ai_roundtable/adapters/` — 每个 AI CLI 一个适配器 + 子进程引擎（生命周期/流式解析）
- `ai_roundtable/core/` — 域层：事件、Quick/Deep 会话、上下文压缩、持久化（JSON 真相源 + MD 导出）
- `ai_roundtable/tui/` — Textual 界面（事件按 session_id 路由，per-tab worker group）
- `ai_roundtable/prompts/` — Prompt 模板（唯一一份；用户副本在 ~/.config/ai-roundtable/prompts/）
- `ai_roundtable/default_config.yml` — 默认配置（与用户配置深合并）
- `tests/` — pytest 套件

## 开发约定

- 测试：`.venv/bin/python -m pytest tests/`，改动 prompt 模板或 render_* 函数必须让
  `tests/test_prompts.py` 的契约测试通过（模板变量与调用点脱节会直接红）
- 所有对 AI CLI 的调用必须经过 `AgentPool` / 引擎，不得绕过（进程生命周期保证在引擎里）
- core 层与 UI 只通过 `core/events.py` 的类型化事件通信，事件必须带 session_id
- 会话数据以 JSON 为准（`~/.local/share/ai-roundtable/sessions/`），Markdown 只写不读
