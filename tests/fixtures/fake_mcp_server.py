"""测试用的假 MCP server —— 行为可编排（现代 / 遗留 / 捣乱三种人格）。

它**故意不 import sammy**：客户端测试考的必须是协议对话本身，
两边用同一套代码的话，同一个理解错误会在两端互相抵消、测不出来。

命令行开关：
  --no-discover       对 server/discover 回「没有这个方法」（装遗留 server）
  --supported VER,..  对外只报这些版本（用来测 -32022 重试探路）
  --paginate          tools/list 分两页（测客户端会不会翻完）
  --log PATH          收到的每条消息追加到文件（测试拿来核对请求序列）
  --die-on-start      爬起来就死（测「起不来」）
  --stderr-lines N    先往 stderr 写 N 行（测客户端抓不抓得住）
  --noisy             每次回话前先发一条 list_changed 通知（测跳过通知）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

DEFAULT_SUPPORTED = ["2026-07-28", "2025-11-25"]

TOOLS = [
    {
        "name": "echo",
        "description": "把 text 原样送回",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "总是失败（isError）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "slow",
        "description": "睡一会儿再回",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
        },
    },
    {
        "name": "booms",
        "description": "被调用时把进程炸掉",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "big",
        "description": "返回一段很长的文本",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class RpcFail(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class FakeServer:
    def __init__(self, args):
        self.args = args
        self.supported = (
            list(args.supported.split(",")) if args.supported else list(DEFAULT_SUPPORTED)
        )
        self.log_file = None
        if args.log:
            # 句柄要活一整个进程（每写一行都 flush），不套 with
            self.log_file = open(args.log, "a", encoding="utf-8")  # noqa: SIM115
        self.sent_stderr = False

    def log(self, msg):
        if self.log_file:
            self.log_file.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.log_file.flush()

    def out(self, msg):
        if self.args.noisy and "result" in msg:
            note = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
            sys.stdout.write(json.dumps(note, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def error(self, rid, code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": rid, "error": err}

    def handle(self, msg):
        self.log(msg)
        if not self.sent_stderr and self.args.stderr_lines:
            for i in range(1, self.args.stderr_lines + 1):
                sys.stderr.write(f"fake stderr 第 {i} 行\n")
            sys.stderr.flush()
            self.sent_stderr = True
        if not isinstance(msg, dict):
            return self.error(None, -32600, "不是对象")
        rid = msg.get("id")
        if rid is None:
            return None  # 通知，不回
        method = msg.get("method")
        params = msg.get("params") or {}
        try:
            result = self.dispatch(method, params)
        except RpcFail as e:
            return self.error(rid, e.code, e.message, e.data)
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def dispatch(self, method, params):
        if method == "initialize":
            ver = params.get("protocolVersion") or ""
            back = (
                ver
                if ver in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
                else "2025-06-18"
            )
            return {
                "protocolVersion": back,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "fake-mcp", "version": "1.0"},
            }
        if method == "server/discover":
            if self.args.no_discover:
                raise RpcFail(-32601, "Method not found")
            meta = params.get("_meta") or {}
            ver = meta.get("io.modelcontextprotocol/protocolVersion")
            if ver not in self.supported:
                raise RpcFail(
                    -32022,
                    "Unsupported protocol version",
                    {"supported": list(self.supported), "requested": ver},
                )
            return {
                "resultType": "complete",
                "supportedVersions": list(self.supported),
                "capabilities": {"tools": {}},
                "_meta": {
                    "io.modelcontextprotocol/serverInfo": {"name": "fake-mcp", "version": "1.0"}
                },
                "ttlMs": 1000,
                "cacheScope": "private",
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            if self.args.paginate:
                cursor = params.get("cursor")
                if cursor is None:
                    return {"resultType": "complete", "tools": TOOLS[:2], "nextCursor": "2"}
                if cursor == "2":
                    return {"resultType": "complete", "tools": TOOLS[2:]}
                raise RpcFail(-32602, "未知 cursor")
            return {"resultType": "complete", "tools": TOOLS}
        if method == "tools/call":
            return self.call_tool(params)
        raise RpcFail(-32601, f"没有这个方法：{method}")

    def call_tool(self, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            return {"content": [{"type": "text", "text": "echo:" + str(args.get("text"))}]}
        if name == "fail":
            return {
                "content": [{"type": "text", "text": "坏掉了，换个参数再试"}],
                "isError": True,
            }
        if name == "slow":
            time.sleep(float(args.get("seconds", 1.0)))
            return {"content": [{"type": "text", "text": "终于好了"}]}
        if name == "booms":
            sys.stdout.flush()
            os._exit(7)
        if name == "big":
            return {"content": [{"type": "text", "text": "长" * 5000}]}
        raise RpcFail(-32602, f"没有叫 {name} 的工具")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fake_mcp_server")
    parser.add_argument("--no-discover", action="store_true")
    parser.add_argument("--supported")
    parser.add_argument("--paginate", action="store_true")
    parser.add_argument("--log")
    parser.add_argument("--die-on-start", action="store_true")
    parser.add_argument("--stderr-lines", type=int, default=0)
    parser.add_argument("--noisy", action="store_true")
    args = parser.parse_args(argv)

    if args.die_on_start:
        return 3

    server = FakeServer(args)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            server.out(server.error(None, -32700, "不是合法 JSON"))
            continue
        resp = server.handle(msg)
        if resp is not None:
            server.out(resp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
