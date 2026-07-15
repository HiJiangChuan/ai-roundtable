import asyncio
import json
import os
import sys
import time

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


def test_codex_skip_git_repo_check():
    # TUI 工作目录不一定是 git 仓库，缺这个 flag codex exec 会直接拒绝运行
    a = CodexAdapter("codex", {"cmd": "codex"})
    assert "--skip-git-repo-check" in a.build_command("p")
    # 用户 flags 已含该项时不重复
    b = CodexAdapter("codex", {"cmd": "codex",
                               "flags": ["--skip-git-repo-check"]})
    assert b.build_command("p").count("--skip-git-repo-check") == 1


def test_claude_env_overrides_removes_claudecode():
    # 嵌套在 Claude Code 里运行时，子 claude 不能看到 CLAUDECODE
    assert ClaudeAdapter("claude", {}).env_overrides() == {"CLAUDECODE": None}


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


# ── 进程组与环境（超时不稳的根源）─────────────────────────────────────────────

async def test_engine_timeout_kills_whole_process_group():
    """超时击杀必须覆盖 CLI 派生的孙进程，不留孤儿烧 token / 占 daemon 连接。"""
    registry = ProcessRegistry()
    task = asyncio.create_task(run_cli(
        ShAdapter("sleep 30 & exec sleep 30"), "p",
        safety_timeout=0.5, registry=registry))
    await asyncio.sleep(0.2)
    pgid = next(iter(registry._procs)).pid    # start_new_session ⇒ pgid == pid
    res = await task
    assert not res.ok and "超时" in res.error
    for _ in range(50):                        # SIGKILL 生效与收尸需要片刻
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("进程组仍存活：孙进程未被击杀")


async def test_engine_grandchild_holding_pipe_does_not_hang():
    """直接子进程退出但孙进程握着 stdout 管道：EOF 永远不来，旧实现会永久挂死。"""
    res = await asyncio.wait_for(
        run_cli(ShAdapter("sleep 30 & echo hi"), "p", safety_timeout=1.0),
        timeout=10.0)
    assert not res.ok and "超时" in res.error


async def test_engine_cancel_kills_whole_process_group():
    """取消（关 tab / 退出）同样要整组击杀。"""
    registry = ProcessRegistry()
    task = asyncio.create_task(run_cli(
        ShAdapter("sleep 30 & exec sleep 30"), "p", registry=registry))
    await asyncio.sleep(0.3)
    pgid = next(iter(registry._procs)).pid
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(50):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("取消后进程组仍存活")


async def test_engine_applies_adapter_env_overrides(monkeypatch):
    monkeypatch.setenv("RT_DROP_ME", "1")

    class EnvShAdapter(ShAdapter):
        def env_overrides(self):
            return {"RT_DROP_ME": None, "RT_MARKER": "yes"}

    res = await run_cli(EnvShAdapter(
        'echo "D=${RT_DROP_ME:-unset} M=${RT_MARKER:-none}"'), "p")
    assert res.ok
    assert "D=unset" in res.text and "M=yes" in res.text


async def test_engine_injects_terminal_env_as_default(monkeypatch):
    # 父环境缺 TERM 时注入缺省值；已有值不覆盖
    monkeypatch.delenv("TERM", raising=False)
    res = await run_cli(ShAdapter('echo "TERM=${TERM:-none}"'), "p")
    assert res.ok and "TERM=xterm-256color" in res.text
    monkeypatch.setenv("TERM", "vt100")
    res = await run_cli(ShAdapter('echo "TERM=$TERM"'), "p")
    assert res.ok and "TERM=vt100" in res.text


# ── 输入/输出的极端尺寸 ───────────────────────────────────────────────────────

async def test_engine_oversized_single_line_no_crash():
    # 单行 9MB（> 8MB 缓冲上限）：不能把引擎炸出异常，须优雅报错
    res = await run_cli(
        ShAdapter("head -c 9437184 /dev/zero | tr '\\0' x; echo"), "p",
        safety_timeout=30)
    assert not res.ok and "缓冲上限" in res.error


@pytest.mark.skipif(sys.platform != "linux",
                    reason="单参数 128KB 上限（MAX_ARG_STRLEN）是 Linux 行为")
async def test_engine_oversized_argv_friendly_error():
    class ArgvAdapter(AgentAdapter):
        prompt_via_stdin = False

        def build_command(self, prompt):
            return ["echo", prompt]

    res = await run_cli(ArgvAdapter("argv", {}), "x" * (200 * 1024))
    assert not res.ok and "过长" in res.error


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
    assert pool.max_concurrent == 2                    # 默认限流


async def test_pool_serializes_same_agent_calls():
    """同一 agent 的并发调用要经过 semaphore 串行化（保护 daemon 型 CLI）。"""
    pool = AgentPool({"ais": {}, "limits": {"max_concurrent_per_agent": 1}})
    pool.adapters["sh"] = ShAdapter("sleep 0.3; echo ok")
    t0 = time.monotonic()
    r1, r2 = await asyncio.gather(pool.call("sh", "p"), pool.call("sh", "p"))
    assert r1.ok and r2.ok
    assert time.monotonic() - t0 >= 0.55               # 并行只需 ~0.3s


async def test_pool_per_call_timeout_override():
    pool = AgentPool({"ais": {}})
    pool.adapters["sh"] = ShAdapter("exec sleep 30")
    t0 = time.monotonic()
    res = await pool.call("sh", "p", safety_timeout=0.5)
    assert not res.ok and "超时" in res.error
    assert time.monotonic() - t0 < 5


async def test_pool_per_agent_max_concurrent_from_ai_cfg():
    pool = AgentPool({"ais": {"sh": {"cmd": "bash", "max_concurrent": 3}},
                      "limits": {"max_concurrent_per_agent": 1}})
    assert pool._sem("sh")._value == 3                 # ais.<name> 覆盖全局默认
