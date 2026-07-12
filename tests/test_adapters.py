import asyncio
import json

import pytest

from ai_roundtable.adapters import (AgentPool, CallResult, ProcessRegistry,
                                    make_adapter)
from ai_roundtable.adapters.agy import AgyAdapter
from ai_roundtable.adapters.base import AgentAdapter
from ai_roundtable.adapters.claude import ClaudeAdapter
from ai_roundtable.adapters.codex import CodexAdapter
from ai_roundtable.adapters.engine import run_cli
from ai_roundtable.adapters.generic import GenericAdapter
from ai_roundtable.adapters.kimi import KimiAdapter


# ── 命令构建 ──────────────────────────────────────────────────────────────────

def test_claude_command_stdin():
    a = ClaudeAdapter("claude", {"cmd": "claude",
                                 "flags": ["--dangerously-skip-permissions"]})
    cmd = a.build_command("prompt")
    assert a.prompt_via_stdin
    assert "prompt" not in cmd                    # prompt 不进 argv
    assert cmd[:2] == ["claude", "-p"]
    assert "--output-format" in cmd and "stream-json" in cmd
    assert cmd[-1] == "--dangerously-skip-permissions"   # 用户 flags 保留


def test_codex_command_stdin_dash():
    a = CodexAdapter("codex", {"cmd": "codex"})
    cmd = a.build_command("prompt")
    assert a.prompt_via_stdin
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert cmd[-1] == "-"


def test_agy_command_argv_with_timeout():
    a = AgyAdapter("agy", {"cmd": "agy"})
    cmd = a.build_command("你好")
    assert not a.prompt_via_stdin
    assert cmd[:3] == ["agy", "--print", "你好"]
    assert "--print-timeout=15m" in cmd


def test_kimi_command_stdin_stream_json():
    a = KimiAdapter("kimi", {"cmd": "kimi", "flags": ["--no-thinking"]})
    cmd = a.build_command("prompt")
    assert a.prompt_via_stdin
    assert "prompt" not in cmd
    assert cmd[:2] == ["kimi", "--print"]
    assert "--input-format" in cmd and "stream-json" in cmd
    assert cmd[-1] == "--no-thinking"


def test_generic_adapter_legacy_config():
    a = make_adapter("mycli", {"cmd": "mycli", "prompt_flag": "--ask",
                               "flags": ["-x"]})
    assert isinstance(a, GenericAdapter)
    assert a.build_command("q") == ["mycli", "--ask", "q", "-x"]
    b = make_adapter("other", {"cmd": "other", "subcommand": "run"})
    assert b.build_command("q") == ["other", "run", "q"]


# ── 流式解析 ──────────────────────────────────────────────────────────────────

def test_claude_parse_line():
    a = ClaudeAdapter("claude", {})
    assert a.parse_line(json.dumps({"type": "system"}))[0].kind == "heartbeat"
    ev = a.parse_line(json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta",
                  "delta": {"type": "text_delta", "text": "你好"}}}))
    assert ev[0].kind == "delta" and ev[0].text == "你好"
    ev = a.parse_line(json.dumps({"type": "result", "result": "全文"}))
    assert ev[0].kind == "final" and ev[0].text == "全文"
    assert a.parse_line("not json") == []
    assert a.parse_line("") == []


def test_codex_parse_line():
    a = CodexAdapter("codex", {})
    ev = a.parse_line(json.dumps({
        "type": "item.started",
        "item": {"type": "command_execution", "command": "ls -la"}}))
    assert ev[0].kind == "progress" and "ls -la" in ev[0].text
    ev = a.parse_line(json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "回答"}}))
    assert ev[0].kind == "delta" and ev[0].text == "回答"
    ev = a.parse_line(json.dumps({"type": "turn.completed"}))
    assert ev[0].kind == "final" and ev[0].text == ""
    ev = a.parse_line(json.dumps({"type": "turn.failed",
                                  "error": {"message": "quota"}}))
    assert ev[0].kind == "progress" and "quota" in ev[0].text
    assert ev[1].kind == "final"


def test_kimi_parse_line():
    a = KimiAdapter("kimi", {})
    # 真实录制的 kimi 1.48.0 stream-json 输出行
    real = ('{"role":"assistant","content":[{"type":"think","think":'
            '"用户要求只回复两个字：收到。","encrypted":null},'
            '{"type":"text","text":"收到"}]}')
    events = a.parse_line(real)
    kinds = [(e.kind, e.text) for e in events]
    assert ("delta", "收到") in kinds
    assert any(k == "progress" and t.startswith("🤔") for k, t in kinds)

    # 工具调用块 → 进度；非 assistant 行 → 心跳；非 JSON → 忽略
    ev = a.parse_line('{"role":"assistant","content":'
                      '[{"type":"tool_call","name":"bash"}]}')
    assert ev[0].kind == "progress" and "bash" in ev[0].text
    assert a.parse_line('{"role":"tool","content":[]}')[0].kind == "heartbeat"
    assert a.parse_line("plain noise") == []
    # stderr 的续聊提示是噪音
    assert a.parse_progress("To resume this session: kimi -r abc") is None
    assert a.parse_progress("real error") == "real error"


def test_plaintext_parse_strips_ansi():
    a = AgyAdapter("agy", {})
    ev = a.parse_line("\x1b[32m绿色文本\x1b[0m")
    assert ev[0].kind == "delta" and ev[0].text == "绿色文本"
    assert a.parse_line("   ") == []


def test_progress_noise_filtered():
    a = ClaudeAdapter("claude", {})
    assert a.parse_progress("YOLO mode: all tool calls will be automatically approved") is None
    assert a.parse_progress("real error message") == "real error message"


# ── 引擎（真实子进程）─────────────────────────────────────────────────────────

class ShAdapter(AgentAdapter):
    """跑任意 shell 片段的测试适配器。"""
    prompt_via_stdin = False

    def __init__(self, script: str, stdin: bool = False):
        super().__init__("sh", {})
        self.script = script
        self.prompt_via_stdin = stdin

    def build_command(self, prompt):
        return ["bash", "-c", self.script]


async def test_engine_collects_stdout():
    res = await run_cli(ShAdapter("printf 'line1\\nline2\\n'"), "p")
    assert res.ok
    assert res.text == "line1\nline2"


async def test_engine_stdin_delivery():
    res = await run_cli(ShAdapter("cat", stdin=True), "提示词内容")
    assert res.ok and res.text == "提示词内容"


async def test_engine_large_stdin_no_deadlock():
    # 512KB prompt：stdin 写入与 stdout 读取必须并发，否则管道互堵
    big = "x" * (512 * 1024)
    res = await run_cli(ShAdapter("cat", stdin=True), big)
    assert res.ok and len(res.text) == len(big)


async def test_engine_error_reports_stderr():
    res = await run_cli(ShAdapter("echo boom >&2; exit 3"), "p")
    assert not res.ok
    assert "boom" in res.error
    assert "[无响应：" in res.display_text


async def test_engine_empty_output():
    res = await run_cli(ShAdapter("true"), "p")
    assert not res.ok and "输出为空" in res.error


async def test_engine_command_not_found():
    class Missing(AgentAdapter):
        prompt_via_stdin = False
        def build_command(self, prompt):
            return ["definitely-not-a-real-cli-xyz"]
    res = await run_cli(Missing("ghost", {}), "p")
    assert not res.ok and "命令未找到" in res.error


async def test_engine_safety_timeout_kills():
    res = await run_cli(ShAdapter("exec sleep 30"), "p", safety_timeout=0.5)
    assert not res.ok and "超时" in res.error
    assert res.elapsed < 10


async def test_engine_cancel_kills_process():
    registry = ProcessRegistry()
    task = asyncio.create_task(
        run_cli(ShAdapter("exec sleep 30"), "p", registry=registry))
    await asyncio.sleep(0.3)
    assert len(registry._procs) == 1
    proc = next(iter(registry._procs))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(registry._procs) == 0
    assert proc.returncode is not None        # 子进程确实死了


async def test_engine_delta_callback_stream():
    chunks = []
    res = await run_cli(ShAdapter("printf 'a\\nb\\n'"), "p",
                        on_delta=chunks.append)
    assert res.ok
    assert chunks == ["a\n", "b\n"]


# ── AgentPool ────────────────────────────────────────────────────────────────

async def test_pool_unknown_agent():
    pool = AgentPool({"ais": {}})
    res = await pool.call("ghost", "p")
    assert not res.ok and "未知 agent" in res.error


def test_pool_builds_adapters_and_limits():
    pool = AgentPool({
        "ais": {"claude": {"cmd": "claude"}, "custom": {"cmd": "x"}},
        "limits": {"idle_notify_seconds": 10, "safety_timeout_seconds": 60},
    })
    assert isinstance(pool.adapters["claude"], ClaudeAdapter)
    assert isinstance(pool.adapters["custom"], GenericAdapter)
    assert pool.idle_notify == 10
    assert pool.safety_timeout == 60
