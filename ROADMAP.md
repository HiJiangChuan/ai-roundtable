# Roadmap

## 已完成（2026-07 重写）

- [x] 历史记录：Quick/Deep 全量落盘，MD 实时追加，会话自动命名
- [x] Obsidian 支持：frontmatter、callout 格式、vault 路径配置
- [x] TUI 历史列表（Ctrl+O），Quick 会话可续聊（含旧版格式）
- [x] 多 Tab 并行会话（互不干扰、后台未读提示）
- [x] JSON 真相源 + Markdown 导出的持久化架构
- [x] 设置页（Ctrl+P）：AI 开关 / Prompt 编辑 / 存储 / 参数
- [x] 子进程生命周期治理（关 tab/退出必杀，无孤儿进程）

## 下一步候选

- [ ] 会话续接：利用 `claude --resume` / `codex exec resume` 复用各 CLI 的原生会话，
      免去每轮全量重发上下文（大幅降低 token 消耗与延迟）
- [ ] Codex 真·token 级流式（app-server JSON-RPC 模式）
- [ ] Deep Round 历史会话重新打开继续讨论（当前仅 Quick 支持续聊）
- [ ] 每 agent 可配置 model / 推理档位
- [ ] 每月索引文件（`2026-03 目录.md`，wikilink 到当月会话）
