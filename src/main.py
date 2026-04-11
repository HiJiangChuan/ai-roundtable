"""入口：解析参数，加载配置，启动 TUI"""
import shutil
import sys
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from tui import RoundtableApp
from prompt_loader import PromptLoader

# ── 路径解析 ──────────────────────────────────────────────────────────────────
# 支持两种运行方式：
#   1. 源码运行：python src/main.py  → config/prompts 在项目根目录
#   2. pip 安装：ai-roundtable       → config 在 ~/.config/ai-roundtable/

_PKG_DIR  = Path(__file__).parent          # src/ 或安装后的 ai_roundtable/
_SRC_ROOT = _PKG_DIR.parent               # 项目根目录（仅源码模式有意义）
_USER_CFG_DIR = Path.home() / '.config' / 'ai-roundtable'


def _get_prompts_dir() -> Path:
    """Prompts 目录：优先包内，其次项目根。"""
    pkg_prompts = _PKG_DIR / 'prompts'
    if pkg_prompts.exists():
        return pkg_prompts
    return _SRC_ROOT / 'prompts'


def _get_config_path() -> Path:
    """
    Config 路径查找顺序（开发与生产一致）：
      1. ~/.config/ai-roundtable/config.yml  （用户目录，开发和生产均从此读取）
      2. 首次运行时从包内 default_config.yml 自动复制到用户目录
    项目根目录的 config.yml 仅作为模板参考，不在运行时读取。
    """
    user_cfg = _USER_CFG_DIR / 'config.yml'
    if user_cfg.exists():
        return user_cfg

    # 首次安装/运行：从包内默认配置复制到用户目录
    default_cfg = _PKG_DIR / 'default_config.yml'
    src_cfg     = _SRC_ROOT / 'config.yml'
    template    = default_cfg if default_cfg.exists() else src_cfg if src_cfg.exists() else None
    if template:
        _USER_CFG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(template, user_cfg)
        print(f"已创建配置文件：{user_cfg}")
        return user_cfg

    print("错误：找不到配置文件", file=sys.stderr)
    sys.exit(1)


def load_config() -> dict:
    config_path = _get_config_path()
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def check_prompts(prompts_dir: Path) -> None:
    loader = PromptLoader(prompts_dir)
    missing = loader.check_all()
    if missing:
        print("错误：以下 prompt 文件缺失：", file=sys.stderr)
        for name in missing:
            print(f"  - prompts/{name}.md", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description='AI Roundtable')
    parser.add_argument('--deep', action='store_true', help='直接进入深度讨论模式')
    args = parser.parse_args()

    prompts_dir = _get_prompts_dir()
    check_prompts(prompts_dir)
    config = load_config()

    initial_mode = "deep" if args.deep else "quick"
    app = RoundtableApp(prompts_dir.parent, config, initial_mode=initial_mode)
    app.run()


if __name__ == "__main__":
    main()
