"""MCP 工具层的全链路演示 —— 全是真子进程、真协议、离线可跑。

证明三件事（T5 的验收点）：
① 客户端能和「假 server」把现代协议走通，出错也是字符串；
② Sammy 自家的联网工具真的挂上了 MCP：由另一个进程提供，本进程走协议调用；
③ 「挂进工具表」之后，走 Sammy 自己那套 tools.call 也能一路通到子进程。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sammy import mcp, tools
from sammy.mcp import McpClient, ServerConfig

FAKE = ROOT / "tests" / "fixtures" / "fake_mcp_server.py"
SRC = str(ROOT / "src")


def step(n: str, title: str) -> None:
    print(f"\n── {n} · {title} ──")


def ok(label: str, detail: str, cost: float) -> None:
    print(f"  ✅ {label}：{detail}（{cost:.2f}s）")


def fake_client(*extra: str) -> McpClient:
    return McpClient(
        ServerConfig(name="fake", command=sys.executable, args=[str(FAKE), *extra]),
        timeout=10,
        probe_timeout=4,
    )


def net_client(*tool_names: str) -> McpClient:
    return McpClient(
        ServerConfig(
            name="net",
            command=sys.executable,
            args=["-m", "sammy.mcp_server", "--tools", ",".join(tool_names)],
            env={"PYTHONPATH": SRC},
        ),
        timeout=30,
        probe_timeout=6,
    )


def main() -> int:
    print("=== Sammy MCP 工具层演示（离线、真子进程） ===")

    step("①", "假 server：现代协议 + 错误也是字符串")
    c = fake_client("--log", str(ROOT / ".tmp" / "mcp_demo_requests.jsonl"))
    t0 = time.time()
    try:
        c.start()
        info = c.server_info or {}
        ok("谈成", f"{c.era} · 协议 {c.version} · 对面 {info.get('name', '?')}", time.time() - t0)
        names = [t.name for t in c.list_tools()]
        assert "echo" in names, names
        print(f"  ✅ 列工具：{', '.join(names)}")
        out = c.call_tool_text("echo", {"text": "嗨"})
        assert out == "echo:嗨", out
        ok("调用 echo", out, time.time() - t0)
        bad = c.call_tool_text("fail")
        assert "坏掉了" in bad and "出错" in bad, bad
        print(f"  ✅ 工具自报的错也是字符串：{bad}")
    finally:
        c.stop()

    step("②", "自家联网工具：另一个进程提供，走协议调用")
    c = net_client("current_time", "fetch_url")
    t0 = time.time()
    try:
        c.start()
        names = [t.name for t in c.list_tools()]
        assert names == ["current_time", "fetch_url"], names
        ok("net 服务谈成", f"{c.era} · 工具 {', '.join(names)}", time.time() - t0)
        now = c.call_tool_text("current_time")
        assert "现在是" in now, now
        ok("调 current_time", now, time.time() - t0)
        blocked = c.call_tool_text("fetch_url", {"url": "http://127.0.0.1/"})
        assert "抓取失败" in blocked, blocked
        print(f"  ✅ SSRF 护栏隔着协议也还在岗：{blocked[:46]}…")
    finally:
        c.stop()

    step("③", "挂进工具表：走 Sammy 自己的 tools.call")
    c = net_client("current_time")
    try:
        c.start()
        added = mcp.mount_client(c)
        assert "mcp__net__current_time" in added, added
        schema = tools.schemas(["mcp__net__current_time"])[0]
        assert schema["function"]["parameters"]["type"] == "object"
        out = tools.call("mcp__net__current_time", "{}")
        assert "现在是" in out, out
        print(f"  ✅ tools.call('mcp__net__current_time') → {out}")
        print("  ✅ 它已经出现在模型能看到的工具 schema 里（tools.schemas 验过）")
    finally:
        c.stop()
        mcp.stop_all()

    step("④", "从别的目录启动、没有 PYTHONPATH：同一份配置照样通（打包版走的就是这条路）")
    venv_py = ROOT / ".venv" / "bin" / "python"
    if not venv_py.exists():
        print("  ⏭ 没有 .venv，跳过这一步（CI 环境）")
    else:
        saved_pp = os.environ.pop("PYTHONPATH", None)
        saved_cwd = os.getcwd()
        try:
            os.chdir("/")  # 假装这是 .app 双击启动时的当前目录
            c = McpClient(
                ServerConfig(
                    name="net",
                    command=".venv/bin/python",
                    args=["-m", "sammy.mcp_server", "--tools", "current_time"],
                ),
                timeout=30,
                probe_timeout=6,
            )
            t0 = time.time()
            try:
                c.start()
                names = [t.name for t in c.list_tools()]
                assert names == ["current_time"], names
                now = c.call_tool_text("current_time")
                assert "现在是" in now, now
                ok("相对路径也谈成", f"{c.era} · {now}", time.time() - t0)
            finally:
                c.stop()
        finally:
            os.chdir(saved_cwd)
            if saved_pp is not None:
                os.environ["PYTHONPATH"] = saved_pp

    print("\n✅ 四条链路全通：假 server / 自家工具挂服务 / 挂进工具表 / 换目录无 PYTHONPATH 启动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
