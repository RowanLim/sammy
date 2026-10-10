"""MCP 工具层（T5）的判据 —— 服务端这一半（把 Sammy 的工具挂出去）。

分两层：
- 纯逻辑层：直接喂消息给 Session，核对每条回复的形状（快、准、可读）；
- 接线层：真起 python 子进程（-m sammy.mcp_server），用客户端把整条链路走通。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sammy import mcp, tools
from sammy.mcp_server import Session, serve_stdio
from sammy.tools import REGISTRY, Tool

ROOT = Path(__file__).resolve().parents[1]
META_KEY = "io.modelcontextprotocol/protocolVersion"


def new_session():
    return Session(dict(REGISTRY))


def call(sess, method, params=None, rid=1, meta_version=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    p = dict(params or {})
    if meta_version:
        p["_meta"] = {META_KEY: meta_version}
    if params is not None or meta_version:
        msg["params"] = p
    return sess.handle(msg)


def server_config(*extra, name="self"):
    return mcp.ServerConfig(
        name=name,
        command=sys.executable,
        args=["-m", "sammy.mcp_server", *extra],
        env={"PYTHONPATH": str(ROOT / "src")},
    )


@pytest.fixture
def registry_guard():
    before = set(tools.REGISTRY)
    yield
    for name in list(tools.REGISTRY):
        if name not in before:
            del tools.REGISTRY[name]


# ── 纯逻辑层：握手 / 探代 / 工具 ──────────────────


def test_initialize_legacy_shape():
    resp = call(new_session(), "initialize", {"protocolVersion": "2025-11-25"})
    r = resp["result"]
    assert r["protocolVersion"] == "2025-11-25"
    assert r["capabilities"]["tools"] == {"listChanged": False}
    assert r["serverInfo"]["name"] == "sammy"


def test_initialize_unknown_version_counteroffers_latest_legacy():
    resp = call(new_session(), "initialize", {"protocolVersion": "1900-01-01"})
    assert resp["result"]["protocolVersion"] == mcp.LEGACY_VERSION


def test_discover_shape():
    resp = call(new_session(), "server/discover", meta_version=mcp.MODERN_VERSION)
    r = resp["result"]
    assert r["resultType"] == "complete"
    assert mcp.MODERN_VERSION in r["supportedVersions"]
    assert r["capabilities"]["tools"] == {}
    assert r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "sammy"
    assert isinstance(r["ttlMs"], int) and r["cacheScope"] in ("public", "private")


def test_discover_bad_version_rejected_with_supported():
    resp = call(new_session(), "server/discover", meta_version="1900-01-01")
    err = resp["error"]
    assert err["code"] == mcp.ERR_UNSUPPORTED_VERSION
    assert mcp.MODERN_VERSION in err["data"]["supported"]
    assert err["data"]["requested"] == "1900-01-01"


def test_discover_without_meta_rejected():
    resp = call(new_session(), "server/discover")
    assert resp["error"]["code"] == -32602


def test_tools_list_requires_meta_before_handshake():
    resp = call(new_session(), "tools/list")
    assert resp["error"]["code"] == -32602


def test_modern_tools_list_shape():
    resp = call(new_session(), "tools/list", meta_version=mcp.MODERN_VERSION)
    r = resp["result"]
    assert r["resultType"] == "complete"
    names = [t["name"] for t in r["tools"]]
    assert "current_time" in names
    ct = next(t for t in r["tools"] if t["name"] == "current_time")
    assert ct["description"] and ct["inputSchema"]["type"] == "object"
    assert "io.modelcontextprotocol/serverInfo" in r["_meta"]


def test_legacy_flow_plain_requests_ok():
    sess = new_session()
    call(sess, "initialize", {"protocolVersion": "2025-06-18"})
    resp = call(sess, "tools/list", rid=2)
    r = resp["result"]
    assert "web_search" in [t["name"] for t in r["tools"]]
    assert "resultType" not in r, "遗留回包不带现代协议的新字段"


def test_tools_call_current_time():
    resp = call(
        new_session(),
        "tools/call",
        {"name": "current_time", "arguments": {}},
        meta_version=mcp.MODERN_VERSION,
    )
    r = resp["result"]
    assert r["isError"] is False
    assert "现在是" in r["content"][0]["text"]


def test_tools_call_unknown_tool_is_protocol_error():
    resp = call(
        new_session(),
        "tools/call",
        {"name": "不存在", "arguments": {}},
        meta_version=mcp.MODERN_VERSION,
    )
    assert resp["error"]["code"] == -32602
    assert "没有叫" in resp["error"]["message"]


def test_tools_call_bad_arguments_rejected():
    resp = call(
        new_session(),
        "tools/call",
        {"name": "current_time", "arguments": "不是对象"},
        meta_version=mcp.MODERN_VERSION,
    )
    assert resp["error"]["code"] == -32602


def test_tool_internal_error_becomes_iserror_result():
    def boom(_):
        raise RuntimeError("内部炸了")

    sess = Session({"boom": Tool("boom", "测试", {"type": "object"}, boom)})
    resp = call(
        sess, "tools/call", {"name": "boom", "arguments": {}}, meta_version=mcp.MODERN_VERSION
    )
    r = resp["result"]
    assert r["isError"] is True
    assert "内部炸了" in r["content"][0]["text"]


def test_unknown_method_is_method_not_found():
    resp = call(new_session(), "no/such", meta_version=mcp.MODERN_VERSION)
    assert resp["error"]["code"] == -32601


def test_ping_works_without_meta():
    resp = call(new_session(), "ping")
    assert resp["result"] == {}


def test_notifications_get_no_reply():
    assert new_session().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# ── 帧层：一行一条，坏行不许炸整个服务 ────────────


def test_serve_stdio_framing_and_bad_json():
    msgs = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        "这不是 json",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
    ]
    stdin = io.BytesIO(("\n".join(msgs) + "\n").encode("utf-8"))
    stdout = io.BytesIO()
    rc = serve_stdio(dict(REGISTRY), stdin=stdin, stdout=stdout)
    assert rc == 0
    out = [json.loads(x) for x in stdout.getvalue().decode("utf-8").splitlines()]
    assert len(out) == 3, "两条请求各回一条 + 一条坏行的报错；通知没有回"
    assert out[0]["id"] == 1
    assert out[1]["error"]["code"] == -32700
    assert out[2]["id"] == 2


# ── 接线层：真子进程的端到端 ──────────────────────


def test_real_server_end_to_end_via_client():
    client = mcp.McpClient(server_config("--tools", "current_time"), timeout=15, probe_timeout=5)
    try:
        client.start()
        assert client.era == "modern"
        assert client.server_info == {"name": "sammy", "version": "0.3"}
        assert [t.name for t in client.list_tools()] == ["current_time"]
        assert "现在是" in client.call_tool_text("current_time")
        with pytest.raises(mcp.McpRpcError):
            client.call_tool("根本不存在")
    finally:
        client.stop()


def test_real_server_mounted_into_registry(registry_guard):
    client = mcp.McpClient(
        server_config("--tools", "current_time,fetch_url"), timeout=15, probe_timeout=5
    )
    try:
        client.start()
        added = mcp.mount_client(client)
        assert "mcp__self__current_time" in added
        assert "现在是" in tools.call("mcp__self__current_time", "{}")
        blocked = tools.call("mcp__self__fetch_url", '{"url": "http://127.0.0.1/"}')
        assert "抓取失败" in blocked, "经过一整圈协议之后护栏还得在岗"
    finally:
        mcp.stop_all()


def test_real_server_exits_zero_on_eof():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "sammy.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0
    proc.stdout.close()
    proc.stderr.close()


def test_real_server_rejects_bad_tools_flag():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "sammy.mcp_server", "--tools", "nope"],
        capture_output=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 2
    assert "nope" in proc.stderr.decode("utf-8")
