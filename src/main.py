"""入口：解析参数，加载配置，启动 TUI"""
import sys
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from tui import RoundtableApp
from prompt_loader import PromptLoader


def load_config(project_root: Path) -> dict:
    config_path = project_root / 'config.yml'
    if not config_path.exists():
        print(f"错误：配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def check_prompts(project_root: Path) -> None:
    loader = PromptLoader(project_root / 'prompts')
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

    project_root = Path(__file__).parent.parent
    check_prompts(project_root)
    config = load_config(project_root)

    initial_mode = "deep" if args.deep else "quick"
    app = RoundtableApp(project_root, config, initial_mode=initial_mode)
    app.run()


if __name__ == "__main__":
    main()
