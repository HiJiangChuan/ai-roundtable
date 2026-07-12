"""设置页（Ctrl+P）：AI 配置 / Prompts / 存储 / 参数。

在配置深拷贝上编辑：「保存」写盘并让 app 重载，「取消」不留任何痕迹
（旧版的 chip 点击会直接改运行时配置，取消无法回滚）。
"""
import copy
import shutil
from pathlib import Path
from typing import Any, Dict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (Button, Input, Label, Select, Static,
                             TabbedContent, TabPane, TextArea)

from ..config import AppPaths, save_config
from ..core.prompts import REQUIRED_PROMPTS, PromptLoader


class SettingsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
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
    .ai-note {
        height: 1;
        color: #3d444d;
        padding: 0 1;
    }

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

    .form-row {
        height: 3;
        align: left middle;
        margin-bottom: 1;
    }
    .form-label {
        width: 28;
        color: #6e7681;
        height: 1;
        content-align: left middle;
    }
    .form-input {
        width: 1fr;
        background: #161b22;
        color: #e6edf3;
        border: solid #30363d;
        height: 1;
        padding: 0 1;
    }
    .form-input.narrow {
        width: 20;
    }
    .form-input:focus {
        border: solid #388bfd;
        background: #0d1f38;
    }
    #storage-resolved {
        height: 1;
        color: #6e7681;
        padding: 0 0 0 28;
        margin-bottom: 1;
    }
    .form-note {
        height: 1;
        color: #3d444d;
        padding: 0 0 0 28;
    }

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

    def __init__(self, config: Dict[str, Any], paths: AppPaths,
                 prompt_loader: PromptLoader):
        super().__init__()
        self._config = copy.deepcopy(config)
        self._paths = paths
        self._loader = prompt_loader
        self._current_prompt = REQUIRED_PROMPTS[0]

    # ── compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-container"):
            yield Static("设置  (Esc 关闭)", id="settings-title")
            with TabbedContent(id="settings-tabs"):
                with TabPane("AI 配置", id="tab-ai"):
                    yield from self._compose_ai_tab()
                with TabPane("Prompts", id="tab-prompts"):
                    yield from self._compose_prompts_tab()
                with TabPane("存储", id="tab-storage"):
                    yield from self._compose_storage_tab()
                with TabPane("参数", id="tab-params"):
                    yield from self._compose_params_tab()
            with Horizontal(id="settings-bottom"):
                yield Button("保存", id="btn-save", variant="primary")
                yield Button("取消", id="btn-cancel")

    def _compose_ai_tab(self) -> ComposeResult:
        with Horizontal(classes="ai-agents-row"):
            for name, cfg in (self._config.get("ais") or {}).items():
                cfg = cfg or {}
                yield Button(self._chip_label(name, cfg),
                             id=f"ai-chip-{name}",
                             classes=self._chip_classes(name, cfg))
        yield Static("点击切换启用；✗ 表示 CLI 未安装（也可禁用以隐藏面板）",
                     classes="ai-note")
        yield Static("保存后的 AI 变更应用于新建的 Tab，进行中的会话保持原参与者",
                     classes="ai-note")

    @staticmethod
    def _installed(name: str, cfg: dict) -> bool:
        return bool(shutil.which(cfg.get("cmd", name)))

    def _chip_label(self, name: str, cfg: dict) -> str:
        label = f"{cfg.get('icon', '')} {name.upper()}".strip()
        if not self._installed(name, cfg):
            label += "  ✗"
        return label

    def _chip_classes(self, name: str, cfg: dict) -> str:
        classes = "ai-chip"
        if cfg.get("enabled", True):
            classes += " ai-chip-on"
        if not self._installed(name, cfg):
            classes += " ai-chip-missing"
        return classes

    def _compose_prompts_tab(self) -> ComposeResult:
        options = [(name, name) for name in REQUIRED_PROMPTS]
        with Horizontal(id="prompt-select-row"):
            yield Label("Prompt：", classes="form-label")
            yield Select(options, value=self._current_prompt,
                         id="prompt-select", allow_blank=False)
        yield TextArea(self._load_prompt(self._current_prompt),
                       id="prompt-textarea", language=None)
        with Horizontal(id="prompt-btn-row"):
            yield Button("保存此 Prompt", id="btn-prompt-save")
            yield Button("恢复默认", id="btn-prompt-restore")

    def _compose_storage_tab(self) -> ComposeResult:
        vault = (self._config.get("history") or {}).get("obsidian_vault", "")
        with Horizontal(classes="form-row"):
            yield Label("Obsidian Vault", classes="form-label")
            yield Input(value=vault,
                        placeholder="留空则存至 ~/Documents/ai-roundtable/",
                        classes="form-input", id="storage-vault")
        yield Static(self._resolve_vault(vault), id="storage-resolved")
        yield Static("会话 Markdown 的存放位置；重启后生效",
                     classes="form-note")

    def _compose_params_tab(self) -> ComposeResult:
        deep = self._config.get("deep") or {}
        limits = self._config.get("limits") or {}
        fields = [
            ("full_rounds_kept", "完整保留轮数",
             str(deep.get("full_rounds_kept", 3))),
            ("compress-max", "压缩摘要最大字数",
             str(deep.get("compress_summary_max", 80))),
            ("idle-notify", "无输出提示秒数",
             str(limits.get("idle_notify_seconds", 25))),
            ("safety-timeout", "兜底超时秒数",
             str(limits.get("safety_timeout_seconds", 900))),
        ]
        for field_id, label, value in fields:
            with Horizontal(classes="form-row"):
                yield Label(label, classes="form-label")
                yield Input(value=value, classes="form-input narrow",
                            id=f"param-{field_id}")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _load_prompt(self, name: str) -> str:
        path = self._loader.path_for(name)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"# {name}\n\n(文件不存在: {path})"

    @staticmethod
    def _resolve_vault(vault: str) -> str:
        if not vault or not vault.strip():
            return str(Path.home() / "Documents" / "ai-roundtable")
        return str(Path(vault).expanduser())

    # ── events ───────────────────────────────────────────────────────────────

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
        if event.select.id == "prompt-select" and event.value != Select.BLANK:
            self._current_prompt = str(event.value)
            self.query_one("#prompt-textarea", TextArea).load_text(
                self._load_prompt(self._current_prompt))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "storage-vault":
            self.query_one("#storage-resolved", Static).update(
                self._resolve_vault(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("ai-chip-"):
            name = btn_id[len("ai-chip-"):]
            ais = self._config.get("ais") or {}
            if name in ais:
                cfg = ais[name] or {}
                cfg["enabled"] = not cfg.get("enabled", True)
                ais[name] = cfg
                event.button.set_classes(self._chip_classes(name, cfg))
        elif btn_id == "btn-cancel":
            self.dismiss(None)
        elif btn_id == "btn-save":
            self._save_all()
        elif btn_id == "btn-prompt-save":
            self._save_current_prompt()
        elif btn_id == "btn-prompt-restore":
            self._restore_default_prompt()

    # ── actions ──────────────────────────────────────────────────────────────

    def _save_current_prompt(self) -> None:
        content = self.query_one("#prompt-textarea", TextArea).text
        dest = self._paths.prompts_dir / f"{self._current_prompt}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self._loader.invalidate(self._current_prompt)
        self.app.notify(f"已保存 {self._current_prompt}.md", timeout=3)

    def _restore_default_prompt(self) -> None:
        src = self._loader.fallback_dir / f"{self._current_prompt}.md"
        if not src.exists():
            self.app.notify(f"找不到默认文件: {src}", severity="error", timeout=4)
            return
        content = src.read_text(encoding="utf-8")
        dest = self._paths.prompts_dir / f"{self._current_prompt}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self._loader.invalidate(self._current_prompt)
        self.query_one("#prompt-textarea", TextArea).load_text(content)
        self.app.notify(f"已恢复 {self._current_prompt}.md 默认内容", timeout=3)

    def _int_field(self, widget_id: str, target: dict, key: str) -> None:
        try:
            target[key] = int(self.query_one(widget_id, Input).value.strip())
        except (ValueError, TypeError):
            pass

    def _save_all(self) -> None:
        config = self._config
        vault = self.query_one("#storage-vault", Input).value.strip()
        config.setdefault("history", {})["obsidian_vault"] = vault

        deep = config.setdefault("deep", {})
        self._int_field("#param-full_rounds_kept", deep, "full_rounds_kept")
        self._int_field("#param-compress-max", deep, "compress_summary_max")
        limits = config.setdefault("limits", {})
        self._int_field("#param-idle-notify", limits, "idle_notify_seconds")
        self._int_field("#param-safety-timeout", limits, "safety_timeout_seconds")

        try:
            save_config(config, self._paths)
        except OSError as e:
            self.app.notify(f"保存失败: {e}", severity="error", timeout=5)
            return
        self.app.notify("设置已保存", timeout=3)
        self.dismiss("saved")
