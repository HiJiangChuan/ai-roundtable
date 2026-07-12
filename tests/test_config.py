import yaml

from ai_roundtable.config import (available_agents, deep_merge, enabled_agents,
                                  ensure_user_files, load_config, save_config)


def test_deep_merge_nested_override():
    base = {"a": {"x": 1, "y": 2}, "b": 1, "c": [1, 2]}
    override = {"a": {"y": 9, "z": 3}, "c": [7]}
    merged = deep_merge(base, override)
    assert merged == {"a": {"x": 1, "y": 9, "z": 3}, "b": 1, "c": [7]}
    assert base["a"] == {"x": 1, "y": 2}  # 不改原 dict


def test_ensure_user_files_first_run(paths):
    messages = ensure_user_files(paths)
    assert paths.config_file.exists()
    assert (paths.prompts_dir / "guest.md").exists()
    assert len(messages) == 2
    # 二次运行不再复制
    assert ensure_user_files(paths) == []


def test_load_config_merges_user_over_defaults(paths):
    ensure_user_files(paths)
    paths.config_file.write_text(
        yaml.safe_dump({
            "ais": {"claude": {"enabled": False}},
            "version": "0.0.68",      # 旧版遗留字段
            "deep": {"full_rounds_kept": 7},
        }, allow_unicode=True),
        encoding="utf-8")
    config = load_config(paths)
    # 用户覆盖生效
    assert config["ais"]["claude"]["enabled"] is False
    assert config["deep"]["full_rounds_kept"] == 7
    # 默认值下沉：用户没写的键来自包内默认
    assert config["ais"]["claude"]["cmd"] == "claude"
    assert config["ais"]["codex"]["icon"] == "🟡"
    assert config["limits"]["safety_timeout_seconds"] == 900
    # version 字段被剥离
    assert "version" not in config


def test_load_config_survives_corrupt_user_file(paths):
    ensure_user_files(paths)
    paths.config_file.write_text(":: not yaml ::[", encoding="utf-8")
    config = load_config(paths)
    assert "ais" in config      # 回退到默认


def test_save_config_strips_version(paths):
    ensure_user_files(paths)
    save_config({"ais": {}, "version": "9.9.9"}, paths)
    saved = yaml.safe_load(paths.config_file.read_text(encoding="utf-8"))
    assert "version" not in saved


def test_agent_filters():
    config = {"ais": {
        "a": {"cmd": "sh", "enabled": True},          # sh 一定在 PATH
        "b": {"cmd": "sh", "enabled": False},
        "c": {"cmd": "definitely-not-a-real-cli-xyz", "enabled": True},
    }}
    assert enabled_agents(config) == ["a", "c"]
    assert available_agents(config) == ["a"]
