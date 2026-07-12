"""路径解析与配置加载。

配置：~/.config/ai-roundtable/config.yml，与包内 default_config.yml 深合并（用户值优先），
     新版本新增的配置项因此能自动到达老用户。
Prompts：~/.config/ai-roundtable/prompts/ 优先，单个文件缺失时回退包内默认（不再整体报错退出）。
数据：会话 JSON 存 ~/.local/share/ai-roundtable/sessions/（真相源），
     Markdown 存 Obsidian vault（仅导出视图）；日志存 ~/.local/state/ai-roundtable/。
"""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

PKG_DIR = Path(__file__).parent
PKG_PROMPTS_DIR = PKG_DIR / "prompts"
PKG_DEFAULT_CONFIG = PKG_DIR / "default_config.yml"


def _xdg(env: str, fallback: str) -> Path:
    value = os.environ.get(env, "").strip()
    return Path(value) if value else Path.home() / fallback


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    prompts_dir: Path
    sessions_dir: Path
    state_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yml"

    @property
    def cli_log(self) -> Path:
        return self.state_dir / "cli.log"


def default_paths() -> AppPaths:
    config_dir = _xdg("XDG_CONFIG_HOME", ".config") / "ai-roundtable"
    data_dir = _xdg("XDG_DATA_HOME", ".local/share") / "ai-roundtable"
    state_dir = _xdg("XDG_STATE_HOME", ".local/state") / "ai-roundtable"
    return AppPaths(
        config_dir=config_dir,
        prompts_dir=config_dir / "prompts",
        sessions_dir=data_dir / "sessions",
        state_dir=state_dir,
    )


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并：override 的值优先；嵌套 dict 逐键合并，其余类型整体替换。"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_user_files(paths: AppPaths) -> List[str]:
    """首次运行时创建用户配置与 prompts 副本。返回提示消息列表。"""
    messages = []
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    if not paths.config_file.exists():
        shutil.copy(PKG_DEFAULT_CONFIG, paths.config_file)
        messages.append(f"已创建配置文件：{paths.config_file}")

    if not paths.prompts_dir.exists():
        paths.prompts_dir.mkdir(parents=True, exist_ok=True)
        for f in PKG_PROMPTS_DIR.glob("*.md"):
            shutil.copy(f, paths.prompts_dir / f.name)
        messages.append(f"已创建 prompts 目录：{paths.prompts_dir}")

    return messages


def load_config(paths: AppPaths) -> Dict[str, Any]:
    """加载配置：包内默认 ← 用户配置 深合并。用户文件缺失/损坏时退回默认。"""
    with open(PKG_DEFAULT_CONFIG, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    try:
        with open(paths.config_file, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        user = {}
    if not isinstance(user, dict):
        user = {}
    config = deep_merge(defaults, user)
    config.pop("version", None)  # 历史遗留字段：版本号已移至 pyproject
    return config


def save_config(config: Dict[str, Any], paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    cleaned = {k: v for k, v in config.items() if k != "version"}
    with open(paths.config_file, "w", encoding="utf-8") as f:
        yaml.dump(cleaned, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)


def enabled_agents(config: Dict[str, Any]) -> List[str]:
    """配置里启用的 agent（不管 CLI 是否安装）。顺序即发言顺序。"""
    return [name for name, cfg in config.get("ais", {}).items()
            if (cfg or {}).get("enabled", True)]


def available_agents(config: Dict[str, Any]) -> List[str]:
    """启用且 CLI 实际可执行的 agent。"""
    result = []
    for name in enabled_agents(config):
        cmd = (config["ais"][name] or {}).get("cmd", name)
        if shutil.which(cmd):
            result.append(name)
    return result
