"""把 Sammy 的工具挂到 MCP 上的服务端 —— 一个 stdio MCP 服务。

    .venv/bin/python -m sammy.mcp_server [--tools current_time,web_search]

为什么要有这一半（T5 的原话是「把现有联网工具挂上去」）：
以前这些工具只活在 Sammy 进程里，只有它自己用得上；挂成 MCP 服务之后，
任何说 MCP 的程序都能调它们 —— 和 Sammy 从外部服务拿工具是同一套协议。
将来二期把「脸」和舵机也挂上去，走的还是这条路。

两代都说：认 initialize 握手（遗留），也认每个请求带 _meta 的现代请求。
现代请求按无状态处理；收到过 initialize 就同时开着遗留模式。
"""

from __future__ import annotations

import argparse
import json
import sys

from .mcp import LEGACY_VERSION, META_SERVER_INFO, META_VERSION, MODERN_VERSION
from .tools import REGISTRY, Tool

SERVER_INFO = {"name": "sammy", "version": "0.3"}
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]  # 对外报的「都会说」清单
STATELESS_ACCEPT = frozenset({MODERN_VERSION, LEGACY_VERSION})
LEGACY_ACCEPT = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})


class RpcFail(Exception):
    """要让调用方回一个 JSON-RPC 错误的失败（协议层错误）。"""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _error(rid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _meta_version(params: dict) -> str | None:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    v = meta.get(META_VERSION)
    return str(v) if isinstance(v, str) and v else None


class Session:
    """一次服务会话的状态机 —— 纯逻辑、不碰 IO，方便直接喂消息测。"""

    def __init__(self, tools_map: dict[str, Tool]):
        self.tools = tools_map
        self.legacy = False  # 收到过 initialize 就开；之后不强制要 _meta

    def handle(self, msg: object) -> dict | None:
        """一条消息进，一条（或零条）消息出。"""
        if not isinstance(msg, dict):
            return _error(None, -32600, "不是 JSON-RPC 对象")
        if msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id"), -32600, "只认 jsonrpc 2.0")
        method = msg.get("method")
        rid = msg.get("id")
        if not isinstance(method, str):
            return None if rid is None else _error(rid, -32600, "没有 method")
        if method.startswith("notifications/"):
            return None  # 通知一律不回
        if rid is None:
            return None  # 其它没 id 的也当通知
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(rid, -32602, "params 得是个对象")
        try:
            result = self._dispatch(method, params)
        except RpcFail as e:
            return _error(rid, e.code, e.message, e.data)
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    # ── 分派 ────────────────────────────────────────

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return self._initialize(params)
        if method == "server/discover":
            meta = _meta_version(params)
            if meta is None:
                raise RpcFail(-32602, "server/discover 需要 _meta（里面要有协议版本）")
            self._check_version(meta)
            return self._modern(
                {
                    "supportedVersions": list(SUPPORTED_VERSIONS),
                    "capabilities": {"tools": {}},
                    "instructions": "Sammy 的联网工具：查时间、搜网页、抓正文。",
                    "ttlMs": 3_600_000,
                    "cacheScope": "private",
                }
            )
        if method == "ping":
            return {}
        meta = _meta_version(params)
        if meta is None and not self.legacy:
            raise RpcFail(-32602, "这个请求既没带 _meta，也没走过 initialize 握手")
        if meta is not None:
            self._check_version(meta)
        modern = meta is not None
        if method == "tools/list":
            return self._list_tools(modern)
        if method == "tools/call":
            return self._call_tool(params, modern)
        raise RpcFail(-32601, f"没有这个方法：{method}")

    def _initialize(self, params: dict) -> dict:
        self.legacy = True
        req = params.get("protocolVersion")
        ver = req if req in LEGACY_ACCEPT else LEGACY_VERSION
        return {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": dict(SERVER_INFO),
        }

    def _check_version(self, version: str) -> None:
        if version not in STATELESS_ACCEPT:
            raise RpcFail(
                -32022,
                "Unsupported protocol version",
                {"supported": list(SUPPORTED_VERSIONS), "requested": version},
            )

    @staticmethod
    def _modern(payload: dict) -> dict:
        out = {"resultType": "complete", **payload}
        out["_meta"] = {META_SERVER_INFO: dict(SERVER_INFO)}
        return out

    def _list_tools(self, modern: bool) -> dict:
        tools = [
            {"name": name, "description": t.description, "inputSchema": t.parameters}
            for name, t in self.tools.items()
        ]
        payload = {"tools": tools}
        return self._modern(payload) if modern else payload

    def _call_tool(self, params: dict, modern: bool) -> dict:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RpcFail(-32602, "tools/call 少了 name")
        tool = self.tools.get(name)
        if tool is None:
            raise RpcFail(-32602, f"没有叫 {name} 的工具")
        args = params.get("arguments")
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                raise RpcFail(-32602, "arguments 不是合法 JSON") from None
        if not isinstance(args, dict):
            raise RpcFail(-32602, "arguments 得是个对象")
        try:
            text = str(tool.fn(args))
            is_error = False
        except Exception as e:
            # 工具执行错误 = 交给模型自纠的机会（isError），不是协议错误
            text = f"工具执行出错（{type(e).__name__}: {e}）"
            is_error = True
        payload = {"content": [{"type": "text", "text": text}], "isError": is_error}
        return self._modern(payload) if modern else payload


# ── 帧层与入口 ──────────────────────────────────────


def serve_stdio(tools_map: dict[str, Tool], stdin=None, stdout=None) -> int:
    """按行收发 JSON-RPC 直到 stdin 关闭，正常退出码是零。"""
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    session = Session(tools_map)
    for raw in stdin:
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            out = _error(None, -32700, "这一行不是合法 JSON")
        else:
            out = session.handle(msg)
        if out is None:
            continue
        data = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            stdout.write(data)
            stdout.flush()
        except OSError:
            return 0  # 对面关了管子：收工，不炸
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sammy.mcp_server", description="Sammy 工具的 MCP stdio 服务"
    )
    parser.add_argument("--tools", help="要挂哪些工具，逗号分隔（默认全部）")
    args = parser.parse_args(argv)
    if args.tools:
        wanted = [n.strip() for n in args.tools.split(",") if n.strip()]
        missing = [n for n in wanted if n not in REGISTRY]
        if missing:
            names = ", ".join(missing)
            have = ", ".join(REGISTRY)
            print(f"❌ 没有这些工具：{names}；有的是：{have}", file=sys.stderr)
            return 2
        tools_map = {n: REGISTRY[n] for n in wanted}
    else:
        tools_map = dict(REGISTRY)
    return serve_stdio(tools_map)


if __name__ == "__main__":
    raise SystemExit(main())
