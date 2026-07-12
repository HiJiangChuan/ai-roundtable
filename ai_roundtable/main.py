"""入口：装配依赖并启动 TUI。"""
import argparse
import sys

from .adapters import AgentPool
from .config import (available_agents, default_paths, enabled_agents,
                     ensure_user_files, load_config)
from .core.prompts import PromptLoader
from .core.store import SessionStore
from .tui.app import RoundtableApp


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Roundtable")
    parser.add_argument("--deep", action="store_true",
                        help="直接进入 Deep Round 模式")
    args = parser.parse_args()

    paths = default_paths()
    notes = ensure_user_files(paths)
    config = load_config(paths)

    prompt_loader = PromptLoader(paths.prompts_dir)
    missing = prompt_loader.check_all()
    if missing:      # 用户目录与包内都缺失才可能触发（安装损坏）
        print("错误：以下 prompt 模板缺失：", file=sys.stderr)
        for name in missing:
            print(f"  - {name}.md", file=sys.stderr)
        sys.exit(1)

    agents = available_agents(config)
    skipped = [a for a in enabled_agents(config) if a not in agents]
    if skipped:
        notes.append(f"已跳过未安装的 CLI：{', '.join(skipped)}"
                     f"（可在设置 Ctrl+P 中禁用）")

    pool = AgentPool(config, log_path=paths.cli_log)
    store = SessionStore(config, paths.sessions_dir)

    app = RoundtableApp(
        config=config,
        paths=paths,
        agents=agents,
        pool=pool,
        store=store,
        prompt_loader=prompt_loader,
        initial_mode="deep" if args.deep else "quick",
        startup_notes=notes,
    )
    try:
        app.run()
    finally:
        pool.kill_all()      # 兜底：不给子进程留活口


if __name__ == "__main__":
    main()
