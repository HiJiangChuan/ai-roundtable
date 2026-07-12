# Prompts Directory

AI Roundtable 的 prompt 模板。首次运行时复制到 `~/.config/ai-roundtable/prompts/`，
用户目录的版本优先生效；单个文件缺失时自动回退包内默认。

变量写作 `{{variable_name}}`，运行时替换。**每个模板的变量集合与
`ai_roundtable/core/prompts.py` 里的 render_* 函数一一对应**，两侧改动必须同步
（`tests/test_prompts.py` 的契约测试会校验）。

## 模板与变量

### guest_quick.md — Quick Round 提问
`agent_name` / `question` / `context_history`

### compare.md — 互评
`agent_name` / `question` / `others_answers`

### opening.md — Deep Round 开场（第0轮主持人）
`moderator_name` / `topic` / `guests_list` / `guests_action_format`

### guest.md — Deep Round 嘉宾发言
`agent_name` / `context` / `round_num` / `moderator_question` /
`action_type` / `action_instruction` / `prior_speeches`

### moderator.md — 主持人综述
`moderator_name` / `context` / `round_num` / `round_speeches` /
`guests_list` / `guests_action_format`

### solo_roundtable.md — 单 AI 圆桌（一人分饰所有角色）
`topic` / `context` / `round_num` / `moderator_question`

### compress.md — 历史轮压缩
`round_content`
