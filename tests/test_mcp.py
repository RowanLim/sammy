"""MCP 工具层（T5）的判据 —— 客户端这一半。

全部离线：假 server 是真子进程（tests/fixtures/fake_mcp_server.py），
但**不是 sammy 自己的代码** —— 考的是对协议的理解，不是自己跟自己握手。

判据围绕四件事：
1. 两代协议都要能动：现代（每个请求带 _meta、无握手）/ 遗留（先 initialize 握手）；
2. 出问题必须是可读的异常或字符串，不许挂死、不许把对话炸掉；
3. 挂进工具表之后，走 Sammy 自己的 tools.call 要能一路通到子进程；
4. 收摊要干净 —— 进程不许留在机器上。
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

import pytest

from sammy import mcp, tools

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fixtures" / "fake_mcp_server.py"

META_KEY = "io.modelcontextprotocol/protocolVersion"


def fake_config(*extra, name="fake"):
    return mcp.ServerConfig(name=name, command=sys.executable, args=[str(FAKE), *extra])


@pytest.fixture
def clients():
    """收集用例里开的客户端 —— 结束一律送走（进程不许留）。"""
    opened = []
    yield opened
    for c in opened:
        with contextlib.suppress(Exception):
            c.stop()


@pytest.fixture
def registry_guard():
    """挂进全局工具表的用例，结束后摘干净。"""
    before = set(tools.REGISTRY)
    yield
    for name in list(tools.REGISTRY):
        if name not in before:
            del tools.REGISTRY[name]


def start(clients, *extra, **kw):
    kw.setdefault("timeout", 5.0)
    kw.setdefault("probe_timeout", 3.0)
    client = mcp.McpClient(fake_config(*extra), **kw)
    clients.append(client)
    client.start()
    return client


def read_log(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── 谈代：现代还是遗留 ────────────────────────────


def test_modern_era_via_discover(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--log", str(log))
    assert c.era == "modern"
    assert c.version == "2026-07-28"
    assert c.server_info == {"name": "fake-mcp", "version": "1.0"}


def test_modern_requests_all_carry_meta(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--log", str(log))
    c.list_tools()
    reqs = read_log(log)
    assert reqs and reqs[0]["method"] == "server/discover"
    for req in reqs:
        meta = (req.get("params") or {}).get("_meta") or {}
        assert meta.get(META_KEY) == c.version, f"{req['method']} 少了 _meta"


def test_unsupported_version_retries_with_theirs(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--supported", "2099-01-01", "--log", str(log))
    assert c.era == "modern"
    assert c.version == "2099-01-01"
    discovers = [r for r in read_log(log) if r["method"] == "server/discover"]
    assert len(discovers) == 2, "应该先探、被 -32022 挡回、再拿对方给的版本探一次"
    assert discovers[1]["params"]["_meta"][META_KEY] == "2099-01-01"


def test_legacy_fallback_on_method_not_found(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--no-discover", "--log", str(log))
    assert c.era == "legacy"
    assert c.version == "2025-11-25"
    assert c.server_info == {"name": "fake-mcp", "version": "1.0"}
    methods = [r["method"] for r in read_log(log)]
    assert methods[:2] == ["server/discover", "initialize"]


def test_legacy_requests_carry_no_meta(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--no-discover", "--log", str(log))
    c.list_tools()
    for req in read_log(log):
        if req["method"] == "server/discover":
            continue  # 探测那一下本来就带 _meta（那是谈代用的）
        assert "_meta" not in (req.get("params") or {}), f"{req['method']} 遗留时代不该带 _meta"


def test_legacy_list_and_call_work(tmp_path, clients):
    c = start(clients, "--no-discover")
    names = [t.name for t in c.list_tools()]
    assert names[:2] == ["echo", "fail"]
    assert c.call_tool_text("echo", {"text": "嗨"}) == "echo:嗨"


# ── 起不来 / 炸了 / 超时：都不许挂死 ──────────────


def test_start_failure_on_missing_command(tmp_path, clients):
    cfg = mcp.ServerConfig(name="bad", command=str(tmp_path / "没有这个程序"))
    c = mcp.McpClient(cfg, timeout=3, probe_timeout=2)
    clients.append(c)
    with pytest.raises(mcp.McpError) as ei:
        c.start()
    assert "起不来" in str(ei.value)


def test_server_dying_on_start_raises_not_hangs(clients):
    c = mcp.McpClient(fake_config("--die-on-start"), timeout=3, probe_timeout=2)
    clients.append(c)
    started = time.monotonic()
    with pytest.raises(mcp.McpError):
        c.start()
    assert time.monotonic() - started < 5
    c.stop()  # 幂等


def test_call_crash_is_error_not_hang(clients):
    c = start(clients)
    started = time.monotonic()
    with pytest.raises(mcp.McpError):
        c.call_tool("booms")
    assert time.monotonic() - started < 5, "进程没了要立刻知道，不能等满超时"
    # 死透之后调用也不能挂：马上换成一句话回来
    out = c.call_tool_text("echo", {"text": "在吗"})
    assert "调用失败" in out


def test_call_timeout_raises(clients):
    c = start(clients, timeout=1.0)
    started = time.monotonic()
    with pytest.raises(mcp.McpTimeout):
        c.call_tool("slow", {"seconds": 20}, timeout=1.0)
    assert time.monotonic() - started < 5


def test_stop_terminates_and_is_idempotent(clients):
    c = start(clients)
    proc = c._proc  # 测试就是要把这个进程盯死
    c.stop()
    assert proc.poll() is not None, "stop 之后进程必须没了"
    c.stop()
    with pytest.raises(mcp.McpError):
        c.call_tool("echo", {"text": "x"})


def test_notifications_are_skipped_and_recorded(clients):
    c = start(clients, "--noisy")
    assert c.list_changed is True, "回话前塞进来的通知：要记下来、别干扰取结果"
    tds = c.list_tools()
    assert len(tds) == 5
    methods = [n.get("method") for n in c.notifications]
    assert "notifications/tools/list_changed" in methods


# ── 列工具 / 调工具 ───────────────────────────────


def test_list_tools_shape(clients):
    c = start(clients)
    tds = c.list_tools()
    assert [t.name for t in tds] == ["echo", "fail", "slow", "booms", "big"]
    echo = tds[0]
    assert echo.description
    assert echo.input_schema["properties"]["text"]["type"] == "string"


def test_list_tools_paginates_until_done(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--paginate", "--log", str(log))
    names = [t.name for t in c.list_tools()]
    assert names == ["echo", "fail", "slow", "booms", "big"]
    lists = [r for r in read_log(log) if r["method"] == "tools/list"]
    assert len(lists) == 2, "两页要翻完，不能只拿第一页"
    assert lists[1]["params"].get("cursor") == "2"


def test_call_echo_roundtrip(clients):
    c = start(clients)
    assert c.call_tool_text("echo", {"text": "嗨"}) == "echo:嗨"


def test_call_error_result_is_flagged(clients):
    c = start(clients)
    raw = c.call_tool("fail")
    assert raw.get("isError") is True
    text = c.call_tool_text("fail")
    assert "坏掉了" in text and "出错" in text, "工具自报的错要带给模型（它能自纠）"


def test_call_unknown_tool_raises_rpc_then_string(clients):
    c = start(clients)
    with pytest.raises(mcp.McpRpcError) as ei:
        c.call_tool("nope")
    assert ei.value.code == -32602
    assert "没有叫" in str(ei.value)
    assert "调用失败" in c.call_tool_text("nope")


def test_stderr_is_captured(clients):
    c = start(clients, "--stderr-lines", "3")
    c.list_tools()
    assert "fake stderr 第 1 行" in c.recent_stderr()


def test_describe_shape(clients):
    c = start(clients)
    c.list_tools()
    d = c.describe()
    assert d["name"] == "fake"
    assert d["era"] == "modern"
    assert "echo" in d["tools"]


def test_format_call_result_shapes():
    two = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    assert mcp.format_call_result(two) == "a\nb"
    assert mcp.format_call_result({"content": [{"type": "image", "data": "x"}]}) == "[图片]"
    assert mcp.format_call_result({"content": []}) == "（空结果）"
    long_text = "长" * 9000
    out = mcp.format_call_result({"content": [{"type": "text", "text": long_text}]})
    assert len(out) < 5000 and "截断" in out
    assert mcp.format_call_result({"content": [], "structuredContent": {"a": 1}}) == '{"a": 1}'


# ── 挂进工具表（「挂上去」就在这）──────────────────


def test_mount_registers_prefixed_tools(clients, registry_guard):
    c = start(clients)
    added = mcp.mount_client(c)
    assert "mcp__fake__echo" in added
    schema = tools.schemas(["mcp__fake__echo"])[0]
    assert schema["function"]["name"] == "mcp__fake__echo"
    assert schema["function"]["parameters"]["properties"]["text"]["type"] == "string"


def test_mounted_call_goes_through_subprocess(clients, registry_guard):
    c = start(clients)
    mcp.mount_client(c)
    out = tools.call("mcp__fake__echo", '{"text": "嗨"}')
    assert out == "echo:嗨", "要真的走子进程一个来回，不是内存里假装一下"


def test_mounted_error_is_a_string_not_an_exception(clients, registry_guard):
    c = start(clients)
    mcp.mount_client(c)
    out = tools.call("mcp__fake__fail", "{}")
    assert isinstance(out, str)
    assert "坏掉了" in out


def test_mounted_tool_when_server_died_returns_string(clients, registry_guard):
    c = start(clients)
    mcp.mount_client(c)
    c.stop()
    out = tools.call("mcp__fake__echo", "{}")
    assert isinstance(out, str)
    assert "调用失败" in out


def test_mount_twice_skips_existing_and_umount_cleans(clients, registry_guard):
    c = start(clients)
    first = mcp.mount_client(c)
    assert first
    assert mcp.mount_client(c) == [], "重复挂不该覆盖或报错，安静跳过"
    gone = mcp.unmount_client("fake")
    assert "mcp__fake__echo" in gone
    assert "mcp__fake__echo" not in tools.REGISTRY


def test_mount_from_config_good_bad_disabled(tmp_path, clients, registry_guard):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "fake", "command": sys.executable, "args": [str(FAKE)]},
                    {"name": "dead", "command": str(tmp_path / "没有这个")},
                    {"name": "off", "command": sys.executable, "enabled": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    report = mcp.mount_from_config(cfg)
    assert report.mounted["fake"]
    assert any(n == "dead" for n, _ in report.failures)
    assert "off" not in report.mounted and all(n != "off" for n, _ in report.failures)
    assert "mcp__fake__echo" in tools.REGISTRY
    lines = report.summary_lines()
    assert any("fake" in x and "挂上" in x for x in lines)
    assert any("dead" in x for x in lines)
    mcp.stop_all()
    assert "mcp__fake__echo" not in tools.REGISTRY, "收摊要连工具一起摘干净"


def test_mount_from_config_missing_file_is_quiet(tmp_path):
    report = mcp.mount_from_config(tmp_path / "还没有.json")
    assert report.mounted == {}
    assert report.failures == []
    assert report.ok


def test_mount_from_config_bad_json_reports_not_raises(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{不是 json", encoding="utf-8")
    report = mcp.mount_from_config(cfg)
    assert report.failures and report.failures[0][0] == "（配置）"
    assert not report.ok


def test_load_config_defaults_and_validation(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps({"servers": [{"command": "x", "args": ["a"], "额外": 1}]}), encoding="utf-8"
    )
    servers = mcp.load_config(cfg)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "server1" and s.command == "x" and s.args == ["a"] and s.enabled

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"servers": [{"name": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        mcp.load_config(bad)


def test_list_tools_caches_until_refresh(tmp_path, clients):
    log = tmp_path / "req.jsonl"
    c = start(clients, "--log", str(log))
    c.list_tools()
    c.list_tools()
    lists = [r for r in read_log(log) if r["method"] == "tools/list"]
    assert len(lists) == 1, "第二次应该吃缓存，别白跑一趟"
    c.list_tools(refresh=True)
    lists = [r for r in read_log(log) if r["method"] == "tools/list"]
    assert len(lists) == 2
