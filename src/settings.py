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
    Button, Input, Label, OptionList, Select, Static, Switch, TabbedContent, TabPane, TextArea
)

sys.path.insert(0, str(Path(__file__).parent))
from prompt_loader import REQUIRED_PROMPTS

_PKG_DIR  = Path(__file__).parent
_SRC_ROOT = _PKG_DIR.parent

KNOWN_MODELS: dict = {
    "claude": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ],
    "gemini": [
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "codex": [
        "o4-mini",
        "o3",
        "o3-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
    ],
}


class ModelPickerScreen(ModalScreen):
    """按 Enter 弹出的模型快速选择浮层。"""

    BINDINGS = [Binding("escape", "dismiss", show=False)]

    CSS = """
    ModelPickerScreen {
        align: center middle;
        background: #000000 55%;
    }
    #model-picker {
        width: 40;
        height: auto;
        background: #161b22;
        border: solid #30363d;
    }
    #picker-title {
        height: 1;
        background: #21262d;
        color: #58a6ff;
        padding: 0 2;
        border-bottom: solid #30363d;
    }
    #model-list {
        background: #161b22;
        border: none;
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, agent: str, models: list):
        super().__init__()
        self._agent  = agent
        self._models = models

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker"):
            yield Static(f"{self._agent.upper()}  · 选择模型  (Esc 取消)",
                         id="picker-title")
            yield OptionList(*self._models, id="model-list")

    def on_mount(self) -> None:
        self.query_one("#model-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))


def _pkg_prompts_source() -> Path:
    """Return the package/src prompts dir (for restoring defaults)."""
    pkg = _PKG_DIR / 'prompts'
    if pkg.exists():
        return pkg
    return _SRC_ROOT / 'prompts'


def _extract_model(flags: list) -> str:
    """Extract value after --model in a flags list."""
    try:
        idx = flags.index('--model')
        return flags[idx + 1]
    except (ValueError, IndexError):
        return ""


def _set_model(flags: list, model: str) -> list:
    """Set or update the --model value in a flags list."""
    flags = list(flags)
    try:
        idx = flags.index('--model')
        if model:
            flags[idx + 1] = model
        else:
            # Remove --model and its value
            del flags[idx:idx + 2]
    except (ValueError, IndexError):
        if model:
            flags.extend(['--model', model])
    return flags


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

    .ai-table {
        height: auto;
        padding: 0 1;
    }

    .ai-table-header {
        height: 1;
        border-bottom: solid #21262d;
        margin-bottom: 0;
    }

    .ai-th {
        color: #3d444d;
        height: 1;
        content-align: left middle;
    }

    .ai-th-agent  { width: 16; }
    .ai-th-status { width: 5; }
    .ai-th-enabled { width: 10; }
    .ai-th-model  { width: 1fr; margin-right: 1; }
    .ai-th-timeout { width: 10; }

    .ai-row {
        height: 3;
        align: left middle;
    }

    .ai-col-agent {
        width: 16;
        color: #e6edf3;
        height: 1;
        content-align: left middle;
    }

    .ai-col-status {
        width: 5;
        height: 1;
        content-align: left middle;
    }

    .ai-col-switch {
        width: 10;
    }

    .ai-col-model {
        width: 1fr;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
        margin-right: 1;
    }

    .ai-col-model:focus {
        border: solid #388bfd;
        background: #0d1f38;
    }

    .ai-col-model.-read-only {
        color: #8b949e;
    }

    .ai-col-model.-read-only:focus {
        color: #e6edf3;
        border: solid #388bfd;
        background: #0d1f38;
    }

    .ai-col-timeout {
        width: 10;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
    }

    .ai-col-timeout:focus {
        border: solid #388bfd;
        background: #0d1f38;
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
        with Vertical(classes="ai-table"):
            with Horizontal(classes="ai-table-header"):
                yield Static("Agent",   classes="ai-th ai-th-agent")
                yield Static("状态",    classes="ai-th ai-th-status")
                yield Static("启用",    classes="ai-th ai-th-enabled")
                yield Static("Model",   classes="ai-th ai-th-model")
                yield Static("Timeout", classes="ai-th ai-th-timeout")
            for agent_name, agent_cfg in ais.items():
                installed = bool(shutil.which(agent_cfg.get('cmd', agent_name)))
                enabled   = agent_cfg.get('enabled', True)
                model     = _extract_model(agent_cfg.get('flags', []))
                timeout   = str(agent_cfg.get('timeout', 60))
                icon      = agent_cfg.get('icon', '')
                status    = "✅" if installed else "❌"
                with Horizontal(classes="ai-row"):
                    yield Static(f"{icon} {agent_name.upper()}", classes="ai-col-agent")
                    yield Static(status, classes="ai-col-status", id=f"ai-status-{agent_name}")
                    yield Switch(value=enabled, id=f"ai-enabled-{agent_name}", classes="ai-col-switch")
                    yield Input(value=model, placeholder="↵ 选择",
                                read_only=True,
                                classes="ai-col-model", id=f"ai-model-{agent_name}")
                    yield Input(value=timeout, placeholder="60",
                                classes="ai-col-timeout", id=f"ai-timeout-{agent_name}")

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
            is_editable_text = isinstance(focused, (Input, TextArea)) and not getattr(focused, 'read_only', False)
            if is_editable_text:
                return
            self.focus_next() if event.key == "right" else self.focus_previous()
            event.stop()
        elif event.key == "enter":
            if isinstance(focused, Input) and focused.id and focused.id.startswith("ai-model-"):
                agent_name = focused.id[len("ai-model-"):]
                models = KNOWN_MODELS.get(agent_name, [])
                if models:
                    inp = focused
                    def _apply(model) -> None:
                        if model:
                            inp.value = model
                    self.app.push_screen(ModelPickerScreen(agent_name, models), _apply)
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

        # ── AI 配置 ──
        ais = config.get('ais', {})
        for agent_name in ais:
            try:
                enabled = self.query_one(f"#ai-enabled-{agent_name}", Switch).value
                model_val = self.query_one(f"#ai-model-{agent_name}", Input).value.strip()
                timeout_val = self.query_one(f"#ai-timeout-{agent_name}", Input).value.strip()
            except Exception:
                continue

            ais[agent_name]['enabled'] = enabled

            flags = list(ais[agent_name].get('flags', []))
            ais[agent_name]['flags'] = _set_model(flags, model_val)

            try:
                ais[agent_name]['timeout'] = int(timeout_val)
            except (ValueError, TypeError):
                pass

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
