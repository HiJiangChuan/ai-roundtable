"""全局 CSS 与 agent 配色。

agent 面板的颜色不再写死在 CSS 选择器里（旧版 .claude/.agy/.codex），
而是按配置的 color 字段在挂载面板时以内联样式设置——新增 agent 自动获得配色。
"""

# color 名 → (边框色, 标题色)
AGENT_PALETTE = {
    "blue":   ("#1f6feb", "#79c0ff"),
    "green":  ("#238636", "#56d364"),
    "yellow": ("#9e6a03", "#e3b341"),
    "red":    ("#da3633", "#ff7b72"),
    "purple": ("#8957e5", "#d2a8ff"),
    "cyan":   ("#1b7c83", "#76e3ea"),
    "orange": ("#bd561d", "#ffa657"),
}
PALETTE_CYCLE = list(AGENT_PALETTE.values())


def agent_colors(config: dict, agent: str, index: int) -> tuple:
    name = ((config.get("ais") or {}).get(agent) or {}).get("color", "")
    if name in AGENT_PALETTE:
        return AGENT_PALETTE[name]
    return PALETTE_CYCLE[index % len(PALETTE_CYCLE)]


APP_CSS = """
Screen {
    background: #0d1117;
    color: #e6edf3;
    overflow-y: hidden;
    overflow-x: hidden;
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

/* ── tabs ─────────────────────────────────────────────────────── */

Tabs {
    height: 2;
    background: #0d1117;
    border-bottom: solid #21262d;
    padding: 0 1;
}

Tab {
    color: #3d444d;
    padding: 0 2;
}

Tab.-active {
    color: #e6edf3;
}

Tab:hover {
    color: #8b949e;
}

/* ── guest panels ─────────────────────────────────────────────── */

#guest-panels {
    height: 1fr;
    padding: 1 2 0 2;
    layout: vertical;
}

.agent-wrap {
    height: 1fr;
    margin-bottom: 1;
    border-left: thick #30363d;
}

.agent-title {
    height: 1;
    padding: 0 1;
    color: #3d444d;
    background: #0d1117;
}

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

.stream-preview {
    height: auto;
    padding: 0 1;
    color: #6e7681;
    display: none;
}

.stream-preview.--active {
    display: block;
    height: 1fr;
}

/* ── horizontal layout ────────────────────────────────────────── */

#guest-panels.horizontal {
    layout: horizontal;
}

#guest-panels.horizontal .agent-wrap {
    width: 1fr;
    height: 1fr;
    margin-bottom: 0;
    margin-right: 1;
}

#guest-panels.horizontal .agent-wrap:last-of-type {
    margin-right: 0;
}

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
