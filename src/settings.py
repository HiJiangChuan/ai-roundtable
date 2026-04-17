"""
Settings screen for AI Roundtable — Ctrl+,
Tabs: AI配置 / Prompts / 存储 / 深度交流
"""
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Input, Label, Select, Static, TabbedContent, TabPane, TextArea
)

sys.path.insert(0, str(Path(__file__).parent))
from prompt_loader import REQUIRED_PROMPTS

_PKG_DIR  = Path(__file__).parent
_SRC_ROOT = _PKG_DIR.parent

def _pkg_prompts_source() -> Path:
    """Return the package/src prompts dir (for restoring defaults)."""
    pkg = _PKG_DIR / 'prompts'
    if pkg.exists():
        return pkg
    return _SRC_ROOT / 'prompts'



class SettingsScreen(ModalScreen):
    """Full settings screen (Ctrl+,)."""

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("ctrl+comma", "dismiss", show=False),
    ]

    CSS = """
    SettingsScreen {
        align: center middle;
        background: #000000 65%;
    }

    #settings-container {
        width: 90;
        height: 40;
        background: #0d1117;
        border: solid #30363d;
    }

    #settings-title {
        height: 1;
        background: #161b22;
        color: #58a6ff;
        padding: 0 2;
        border-bottom: solid #21262d;
    }

    TabbedContent {
        height: 1fr;
    }

    TabbedContent ContentSwitcher {
        height: 1fr;
    }

    TabPane {
        padding: 1 2;
        height: 1fr;
        overflow-y: auto;
        scrollbar-size: 1 1;
        scrollbar-color: #21262d;
        scrollbar-background: transparent;
    }

    /* ── AI 配置 tab ── */

    .ai-agents-row {
        height: auto;
        padding: 2 1;
        align: left middle;
    }

    .ai-chip {
        min-width: 16;
        height: 3;
        margin: 0 1 0 0;
        background: #161b22;
        border: solid #30363d;
        color: #6e7681;
    }

    .ai-chip:focus {
        border: solid #388bfd;
    }

    .ai-chip-on {
        background: #0d1f38;
        color: #e6edf3;
        border: solid #1f6feb;
    }

    .ai-chip-missing {
        color: #3d444d;
        border: dashed #21262d;
    }

    /* ── Prompts tab ── */

    #prompt-select-row {
        height: 3;
        align: left middle;
        margin-bottom: 1;
    }

    #prompt-select {
        width: 40;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
    }

    #prompt-select:focus {
        border: solid #388bfd;
    }

    #prompt-textarea {
        height: 18;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
    }

    #prompt-textarea:focus {
        border: solid #388bfd;
    }

    #prompt-btn-row {
        height: 3;
        align: left middle;
        margin-top: 1;
    }

    /* ── 存储 tab ── */

    .storage-row {
        height: 3;
        align: left middle;
        margin-bottom: 1;
    }

    .storage-label {
        width: 18;
        color: #6e7681;
        height: 1;
        content-align: left middle;
    }

    .storage-input {
        width: 1fr;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
        height: 1;
        padding: 0 1;
    }

    .storage-input:focus {
        border: solid #388bfd;
        background: #0d1f38;
    }

    #storage-resolved {
        height: 1;
        color: #6e7681;
        padding: 0 0 0 18;
        margin-bottom: 1;
    }

    .storage-note {
        height: 1;
        color: #3d444d;
        padding: 0 0 0 18;
    }

    /* ── 深度交流 tab ── */

    .deep-row {
        height: 3;
        align: left middle;
        margin-bottom: 1;
    }

    .deep-label {
        width: 28;
        color: #6e7681;
        height: 1;
        content-align: left middle;
    }

    .deep-input {
        width: 20;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
        height: 1;
        padding: 0 1;
    }

    .deep-input:focus {
        border: solid #388bfd;
        background: #0d1f38;
    }

    /* ── bottom bar ── */

    #settings-bottom {
        height: 3;
        align: right middle;
        border-top: solid #21262d;
        padding: 0 2;
    }

    #btn-save {
        background: #1f6feb;
        color: #e6edf3;
        border: none;
        margin-left: 1;
    }

    #btn-save:hover {
        background: #388bfd;
    }

    #btn-cancel {
        background: #21262d;
        color: #8b949e;
        border: none;
        margin-left: 1;
    }

    #btn-cancel:hover {
        background: #30363d;
        color: #e6edf3;
    }

    #btn-prompt-save {
        background: #238636;
        color: #e6edf3;
        border: none;
        margin-right: 1;
    }

    #btn-prompt-save:hover {
        background: #2ea043;
    }

    #btn-prompt-restore {
        background: #21262d;
        color: #8b949e;
        border: none;
    }

    #btn-prompt-restore:hover {
        background: #30363d;
        color: #e6edf3;
    }
    """

    def __init__(self, config: Dict[str, Any], user_cfg_path: Path, prompts_dir: Path):
        super().__init__()
        self._config = config
        self._user_cfg_path = user_cfg_path
        self._prompts_dir = prompts_dir
        # Current prompt being edited
        self._current_prompt: str = REQUIRED_PROMPTS[0] if REQUIRED_PROMPTS else ""

    # ── compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-container"):
            yield Static("设置  (Esc 关闭)", id="settings-title")

            with TabbedContent("AI 配置", "Prompts", "存储", "深度交流",
                               id="settings-tabs"):
                # ── Tab 1: AI 配置 ──────────────────────────────────────
                with TabPane("AI 配置", id="tab-ai"):
                    yield from self._compose_ai_tab()

                # ── Tab 2: Prompts ──────────────────────────────────────
                with TabPane("Prompts", id="tab-prompts"):
                    yield from self._compose_prompts_tab()

                # ── Tab 3: 存储 ─────────────────────────────────────────
                with TabPane("存储", id="tab-storage"):
                    yield from self._compose_storage_tab()

                # ── Tab 4: 深度交流 ─────────────────────────────────────
                with TabPane("深度交流", id="tab-deep"):
                    yield from self._compose_deep_tab()

            with Horizontal(id="settings-bottom"):
                yield Button("保存", id="btn-save", variant="primary")
                yield Button("取消", id="btn-cancel")

    def _compose_ai_tab(self) -> ComposeResult:
        ais = self._config.get('ais', {})
        with Horizontal(classes="ai-agents-row"):
            for agent_name, agent_cfg in ais.items():
                installed = bool(shutil.which(agent_cfg.get('cmd', agent_name)))
                enabled   = agent_cfg.get('enabled', True)
                icon      = agent_cfg.get('icon', '')
                label = f"{icon} {agent_name.upper()}"
                if not installed:
                    label += "  ✗"
                classes = "ai-chip"
                if enabled and installed:
                    classes += " ai-chip-on"
                elif not installed:
                    classes += " ai-chip-missing"
                yield Button(label, id=f"ai-chip-{agent_name}", classes=classes)

    def _compose_prompts_tab(self) -> ComposeResult:
        options = [(name, name) for name in REQUIRED_PROMPTS]
        default = REQUIRED_PROMPTS[0] if REQUIRED_PROMPTS else Select.BLANK

        initial_content = self._load_prompt_content(default if isinstance(default, str) else "")

        with Horizontal(id="prompt-select-row"):
            yield Label("Prompt：", classes="storage-label")
            yield Select(options, value=default, id="prompt-select", allow_blank=False)

        yield TextArea(initial_content, id="prompt-textarea", language=None)

        with Horizontal(id="prompt-btn-row"):
            yield Button("保存此 Prompt", id="btn-prompt-save")
            yield Button("恢复默认", id="btn-prompt-restore")

    def _compose_storage_tab(self) -> ComposeResult:
        vault = self._config.get('history', {}).get('obsidian_vault', '')
        resolved = self._resolve_vault(vault)

        with Horizontal(classes="storage-row"):
            yield Label("Obsidian Vault", classes="storage-label")
            yield Input(value=vault, placeholder="留空则存至 ~/Documents/ai-roundtable/",
                        classes="storage-input", id="storage-vault")

        yield Static(resolved, id="storage-resolved")
        yield Static("留空则存至 ~/Documents/ai-roundtable/", classes="storage-note")

    def _compose_deep_tab(self) -> ComposeResult:
        deep = self._config.get('deep', {})
        full_rounds = str(deep.get('full_rounds_kept', 3))
        compress_max = str(deep.get('compress_summary_max', 80))
        timeout = str(deep.get('timeout_seconds', 60))

        with Horizontal(classes="deep-row"):
            yield Label("full_rounds_kept", classes="deep-label")
            yield Input(value=full_rounds, placeholder="3",
                        classes="deep-input", id="deep-full-rounds")

        with Horizontal(classes="deep-row"):
            yield Label("compress_summary_max", classes="deep-label")
            yield Input(value=compress_max, placeholder="80",
                        classes="deep-input", id="deep-compress-max")

        with Horizontal(classes="deep-row"):
            yield Label("timeout_seconds", classes="deep-label")
            yield Input(value=timeout, placeholder="60",
                        classes="deep-input", id="deep-timeout")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _load_prompt_content(self, name: str) -> str:
        if not name:
            return ""
        path = self._prompts_dir / f"{name}.md"
        if path.exists():
            return path.read_text(encoding='utf-8')
        return f"# {name}\n\n(文件不存在: {path})"

    def _resolve_vault(self, vault: str) -> str:
        if not vault or not vault.strip():
            return str(Path.home() / 'Documents' / 'ai-roundtable')
        return str(Path(vault).expanduser())

    # ── event handlers ───────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        focused = self.focused
        if event.key in ("up", "down"):
            if isinstance(focused, TextArea):
                return
            self.focus_next() if event.key == "down" else self.focus_previous()
            event.stop()
        elif event.key in ("left", "right"):
            if isinstance(focused, (Input, TextArea)):
                return
            self.focus_next() if event.key == "right" else self.focus_previous()
            event.stop()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "prompt-select":
            name = event.value
            if name and name != Select.BLANK:
                self._current_prompt = str(name)
                content = self._load_prompt_content(self._current_prompt)
                self.query_one("#prompt-textarea", TextArea).load_text(content)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "storage-vault":
            resolved = self._resolve_vault(event.value)
            self.query_one("#storage-resolved", Static).update(resolved)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id and btn_id.startswith("ai-chip-"):
            agent_name = btn_id[len("ai-chip-"):]
            ais = self._config.get('ais', {})
            if agent_name in ais:
                installed = bool(shutil.which(ais[agent_name].get('cmd', agent_name)))
                if installed:
                    enabled = not ais[agent_name].get('enabled', True)
                    ais[agent_name]['enabled'] = enabled
                    btn = event.button
                    if enabled:
                        btn.add_class("ai-chip-on")
                    else:
                        btn.remove_class("ai-chip-on")
            return

        if btn_id == "btn-cancel":
            self.dismiss(None)

        elif btn_id == "btn-save":
            self._save_all()
            self.dismiss("saved")

        elif btn_id == "btn-prompt-save":
            self._save_current_prompt()

        elif btn_id == "btn-prompt-restore":
            self._restore_default_prompt()

    def _save_current_prompt(self) -> None:
        name = self._current_prompt
        if not name:
            self.app.notify("请先选择一个 Prompt", severity="warning", timeout=3)
            return
        content = self.query_one("#prompt-textarea", TextArea).text
        dest = self._prompts_dir / f"{name}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding='utf-8')
        self.app.notify(f"已保存 {name}.md", timeout=3)

    def _restore_default_prompt(self) -> None:
        name = self._current_prompt
        if not name:
            self.app.notify("请先选择一个 Prompt", severity="warning", timeout=3)
            return
        source_dir = _pkg_prompts_source()
        src = source_dir / f"{name}.md"
        if not src.exists():
            self.app.notify(f"找不到默认文件: {src}", severity="error", timeout=4)
            return
        dest = self._prompts_dir / f"{name}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        content = dest.read_text(encoding='utf-8')
        self.query_one("#prompt-textarea", TextArea).load_text(content)
        self.app.notify(f"已恢复 {name}.md 默认内容", timeout=3)

    def _save_all(self) -> None:
        """Collect all widget values, update config dict, write to YAML."""
        config = self._config

        # AI 启用状态已在 on_button_pressed 中实时写入 self._config

        # ── 存储 ──
        vault_val = self.query_one("#storage-vault", Input).value.strip()
        config.setdefault('history', {})['obsidian_vault'] = vault_val

        # ── 深度交流 ──
        deep = config.setdefault('deep', {})
        try:
            deep['full_rounds_kept'] = int(
                self.query_one("#deep-full-rounds", Input).value.strip())
        except (ValueError, TypeError):
            pass
        try:
            deep['compress_summary_max'] = int(
                self.query_one("#deep-compress-max", Input).value.strip())
        except (ValueError, TypeError):
            pass
        try:
            deep['timeout_seconds'] = int(
                self.query_one("#deep-timeout", Input).value.strip())
        except (ValueError, TypeError):
            pass

        # ── Write YAML ──
        try:
            self._user_cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._user_cfg_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False,
                          sort_keys=False)
            self.app.notify("设置已保存", timeout=3)
        except Exception as e:
            self.app.notify(f"保存失败: {e}", severity="error", timeout=5)
