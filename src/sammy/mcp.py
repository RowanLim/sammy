"""MCP（Model Context Protocol）stdio 客户端 —— Sammy 接外部能力的入口。

为什么自己写、不用官方 SDK：
1. 项目第一原则是「只用标准库」（树莓派上少一个依赖少一个坑）；
2. 我们真正用到的只有很小一块：连上 stdio 服务、列工具（tools/list）、
   调工具（tools/call），外加协议代次的探测。

**两代协议都要会说**（2026 年 7 月的 MCP 大改版把握手删了）：
- 「现代」（2026-07-28 起）：没有握手，每个请求自带 `_meta`（版本 / 身份 / 能力）；
- 「遗留」（2025-11-25 及以前）：先 `initialize` 握手，之后的请求是裸的。
探测用的方法叫 `server/discover`：它回的版本不对、或者回一个不认识的方法错误，
就说明对方是老式的 —— 规格里就是这么定的（-32022 之类的「现代错误」
说明对方懂新协议；回别的错误、或者干脆不理，按遗留处理）。

配置里 command 的启动规矩：含斜杠的相对路径按项目根解析、子进程的 PYTHONPATH
默认带上项目 src、工作目录默认项目根 —— 源码模式与打包后的 .app 用同一份
data/mcp.json（见 resolve_command / child_env / spawn_spec）。
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import select
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import tools as _tools
from .paths import data_dir, project_root

# ── 协议常量 ────────────────────────────────────────

MODERN_VERSION = "2026-07-28"  # 我们最想说的版本（无握手）
LEGACY_VERSION = "2025-11-25"  # 遗留里最新的一个（握手用）
LEGACY_RETRY_VERSION = "2025-06-18"  # 老 server 不认上面那个时的退步

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

CLIENT_INFO = {"name": "Sammy", "version": "0.3"}

ERR_UNSUPPORTED_VERSION = -32022  # UnsupportedProtocolVersionError
# -32020 / -32021 同属「现代」错误码：见到它们就说明对方懂新协议
MODERN_ERROR_CODES = frozenset({-32020, -32021, -32022})

MAX_RESULT_CHARS = 4000  # 工具结果回给模型前的截断线
MAX_PAGES = 20  # tools/list 翻页上限（防服务器一直给 nextCursor）
MAX_STDERR = 65536  # stderr 留存量（出事时用来讲清楚，不要无限囤）


# ── 错误：MCP 层出错是**可读的异常**，到了工具层会变成一句话 ──


class McpError(Exception):
    """MCP 层一切错误的基类。"""


class McpRpcError(McpError):
    """服务器回的 JSON-RPC 错误。"""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(f"服务器报错 {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class McpTimeout(McpError):
    """等一个响应等到超时。"""


class McpServerGone(McpError):
    """服务器进程没了（起不来 / 半路退出）。"""


# ── 配置：data/mcp.json ─────────────────────────────


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True


def default_config_path() -> Path:
    """配置放 data/mcp.json（项目目录里，跟着隔离规矩走）。"""
    return data_dir() / "mcp.json"


def load_config(path: str | Path | None = None) -> list[ServerConfig]:
    """读配置。文件不存在 = 还没配任何服务，返回空表（这不是错误）。"""
    p = Path(path) if path else default_config_path()
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    entries = raw.get("servers") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{p} 里应该是一个 servers 数组")
    out: list[ServerConfig] = []
    for i, item in enumerate(entries):
        if not isinstance(item, dict) or not item.get("command"):
            raise ValueError(f"{p} 第 {i + 1} 个服务少了 command")
        out.append(
            ServerConfig(
                name=str(item.get("name") or f"server{i + 1}"),
                command=str(item["command"]),
                args=[str(a) for a in item.get("args") or []],
                env={str(k): str(v) for k, v in (item.get("env") or {}).items()},
                cwd=str(item["cwd"]) if item.get("cwd") else None,
                enabled=bool(item.get("enabled", True)),
            )
        )
    return out


# ── 子进程启动规矩：源码模式与打包模式同一套 ─────────


def resolve_command(command: str) -> str:
    """把配置里的 command 解析成能执行的样子。

    规矩只有一条：看起来像路径的（含斜杠）相对写法按**项目根**解析 ——
    data/mcp.json 里的 command 按惯例写成项目内相对路径（如 .venv/bin/python），
    它在源码模式天然成立（启动前会先 cd 到项目根），但打包后的 .app
    双击启动时当前目录是「/」，同一份配置就找不到文件。绝对路径原样返回；
    裸命令名（npx、python3 这类）原样交给 PATH —— 那本来就是系统的事。
    """
    if command.startswith("~"):
        return os.path.expanduser(command)
    if os.sep in command and not os.path.isabs(command):
        return str(project_root() / command)
    return command


def child_env(config: ServerConfig) -> dict[str, str]:
    """子进程的环境：默认保证项目的 src 在 PYTHONPATH 里。

    源码模式靠 run.sh 里那行 PYTHONPATH=src；打包模式没人帮这个忙，
    所以在这里统一补上。config.env 里显式给的键优先（含 PYTHONPATH）。
    """
    env = os.environ.copy()
    src = str(project_root() / "src")
    parts = [p for p in (env.get("PYTHONPATH") or "").split(os.pathsep) if p]
    if src not in parts:
        parts.insert(0, src)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.update(config.env)
    return env


def spawn_spec(config: ServerConfig) -> tuple[list[str], dict[str, str], str]:
    """把配置翻成子进程启动三件套：命令数组、环境、工作目录。

    工作目录默认**项目根**（而不是继承启动方的当前目录）——
    无论 Sammy 从哪启动，子进程眼里的当前目录都是同一个地方。
    """
    cmd = [resolve_command(config.command), *config.args]
    return cmd, child_env(config), config.cwd or str(project_root())


# ── 客户端 ──────────────────────────────────────────


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict


def _as_tool_def(raw: object) -> ToolDef | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"]:
        return None
    schema = raw.get("inputSchema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return ToolDef(
        name=raw["name"], description=str(raw.get("description") or ""), input_schema=schema
    )


class McpClient:
    """一条通往 stdio MCP 服务器的管道（同步：一次一个请求）。

    故意的简单：Sammy 的用法就是「列一次工具、偶尔调一次」，
    不值得为它养线程加队列。同步的代价是**不许并发调用** ——
    挂进工具层之后，调用发生在它自己的工作线程里，天然满足。
    """

    def __init__(self, config: ServerConfig, timeout: float = 30.0, probe_timeout: float = 5.0):
        self.config = config
        self.name = config.name
        self.timeout = timeout
        self.probe_timeout = probe_timeout
        self.era: str | None = None  # "modern" / "legacy"，谈完才知道
        self.version = MODERN_VERSION
        self.server_info: dict | None = None
        self.notifications: list[dict] = []  # 对面随手发的通知（如 list_changed）
        self.list_changed = False  # 收到过 tools/list_changed
        self._proc: subprocess.Popen | None = None
        self._buf = b""
        self._stderr_raw = b""
        self._next_id = 0
        self._tool_cache: list[ToolDef] | None = None

    # ── 生命周期 ────────────────────────────────────

    def start(self) -> McpClient:
        """拉起进程 + 谈协议代。起不来或者谈不拢，抛 McpError 异常。"""
        if self._proc is not None:
            return self
        cmd, env, cwd = spawn_spec(self.config)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        except OSError as e:
            raise McpError(f"起不来（{cmd[0]}）：{e}") from e
        try:
            self._negotiate()
        except McpError:
            self.stop()
            raise
        return self

    def _negotiate(self) -> None:
        """先按现代探；探不动就退回握手。判代规则的实现全在这一个函数里。"""
        try:
            result = self._request_raw(
                "server/discover",
                {},
                meta=self._modern_meta(MODERN_VERSION),
                timeout=self.probe_timeout,
            )
        except McpRpcError as e:
            if e.code == ERR_UNSUPPORTED_VERSION:
                supported = self._supported_from_error(e)
                self.version = (
                    MODERN_VERSION
                    if MODERN_VERSION in supported
                    else (supported[0] if supported else MODERN_VERSION)
                )
                result = self._request_raw(  # 换它给得起的版本再探一次
                    "server/discover",
                    {},
                    meta=self._modern_meta(self.version),
                    timeout=self.probe_timeout,
                )
                self._absorb_discover(result)
                return
            if e.code in MODERN_ERROR_CODES:
                # 懂新协议、只是这会儿没得聊：按现代走
                self.era = "modern"
                self.version = MODERN_VERSION
                return
            self._legacy_handshake()
            return
        except McpTimeout:
            self._legacy_handshake()  # 规格原话：不理就算遗留
            return
        self._absorb_discover(result)

    def _absorb_discover(self, result: dict) -> None:
        self.era = "modern"
        versions = result.get("supportedVersions")
        if isinstance(versions, list) and versions:
            self.version = MODERN_VERSION if MODERN_VERSION in versions else str(versions[0])
        meta = result.get("_meta")
        info = meta.get(META_SERVER_INFO) if isinstance(meta, dict) else None
        if isinstance(info, dict):
            self.server_info = info

    @staticmethod
    def _supported_from_error(e: McpRpcError) -> list[str]:
        data = e.data if isinstance(e.data, dict) else {}
        supported = data.get("supported")
        return [str(v) for v in supported] if isinstance(supported, list) else []

    def _modern_meta(self, version: str) -> dict:
        return {META_VERSION: version, META_CLIENT_INFO: CLIENT_INFO, META_CLIENT_CAPS: {}}

    def _legacy_handshake(self) -> None:
        params = {
            "protocolVersion": LEGACY_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }
        try:
            result = self._request_raw("initialize", params, meta=None, timeout=self.timeout)
        except McpRpcError:
            params["protocolVersion"] = LEGACY_RETRY_VERSION  # 退一步，再不行就认栽
            result = self._request_raw("initialize", params, meta=None, timeout=self.timeout)
        self.era = "legacy"
        ver = result.get("protocolVersion")
        self.version = str(ver) if ver else LEGACY_VERSION
        info = result.get("serverInfo")
        if isinstance(info, dict):
            self.server_info = info
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # ── 请求 / 响应 ──────────────────────────────────

    def _request_raw(self, method: str, params: dict, meta: dict | None, timeout: float) -> dict:
        self._ensure_alive()
        self._next_id += 1
        rid = self._next_id
        full = dict(params)
        if meta is not None:
            full["_meta"] = meta
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": full})
        return self._wait_response(rid, timeout)

    def _request(
        self, method: str, params: dict | None = None, timeout: float | None = None
    ) -> dict:
        """按当前代发请求：现代带 _meta，遗留不带。"""
        meta = self._modern_meta(self.version) if self.era == "modern" else None
        wait = self.timeout if timeout is None else timeout
        return self._request_raw(method, params or {}, meta, wait)

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpServerGone(f"服务「{self.name}」没在跑")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
        except OSError as e:
            raise McpServerGone(f"给服务「{self.name}」写消息失败（进程多半没了）：{e}") from e

    def _ensure_alive(self) -> None:
        proc = self._proc
        if proc is None:
            raise McpServerGone(f"服务「{self.name}」没在跑")
        rc = proc.poll()
        if rc is not None:
            tail = self.recent_stderr(10)
            extra = f"；最近的 stderr：{tail}" if tail else ""
            raise McpServerGone(f"服务「{self.name}」的进程已经退出（{rc}）{extra}")

    def _wait_response(self, rid: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTimeout(f"等服务「{self.name}」的回复超时（{timeout:.1f}s）")
            message = self._next_message(remaining)
            mid = message.get("id")
            if mid == rid and ("result" in message or "error" in message):
                if "error" in message:
                    err = message.get("error")
                    err = err if isinstance(err, dict) else {}
                    raise McpRpcError(
                        int(err.get("code") or 0),
                        str(err.get("message") or "没有说明"),
                        err.get("data"),
                    )
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if mid is not None and ("result" in message or "error" in message):
                # 不是我们在等的那条响应：记下来，别丢（理论上单线程不该出现）
                self._record({"不请自来的响应": message})
            else:
                self._record(message)

    def _next_message(self, timeout: float) -> dict:
        """等一条 JSON 消息（跳过空行与坏行）；超时或进程死掉，抛对应子类异常。"""
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue  # 对面写了非协议内容：丢掉，但不炸
                if isinstance(msg, dict):
                    return msg
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTimeout(f"等了 {timeout:.1f} 秒没等到服务「{self.name}」的消息")
            proc = self._proc
            if proc is None or proc.stdout is None:
                raise McpServerGone(f"服务「{self.name}」没在跑")
            try:
                ready, _, _ = select.select([proc.stdout], [], [], remaining)
            except (OSError, ValueError):
                ready = []
            if not ready:
                self._drain_stderr()
                continue
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                raise self._server_gone_error()
            self._buf += chunk
            self._drain_stderr()

    def _drain_stderr(self) -> None:
        """把 stderr 里已经有的东西收进尾巴缓冲 —— 出事时用来讲清楚发生了什么。"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        fd = proc.stderr.fileno()
        try:
            while select.select([proc.stderr], [], [], 0)[0]:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                self._stderr_raw = (self._stderr_raw + chunk)[-MAX_STDERR:]
        except (OSError, ValueError):
            return

    def recent_stderr(self, lines: int = 80) -> str:
        """最近若干行 stderr（先顺手收一次，保证拿到的是最新的）。"""
        self._drain_stderr()
        text = self._stderr_raw.decode("utf-8", errors="replace")
        tail = [x for x in text.splitlines() if x.strip()][-lines:]
        return "\n".join(tail)

    def _record(self, message: dict) -> None:
        """记下一条不需要现在处理的消息（通知 / 别人的响应）。"""
        self.notifications.append(message)
        if len(self.notifications) > 50:
            del self.notifications[:-50]
        if message.get("method") == "notifications/tools/list_changed":
            self.list_changed = True

    def _server_gone_error(self) -> McpServerGone:
        proc = self._proc
        rc = proc.poll() if proc is not None else None
        if proc is not None and rc is None:
            try:
                rc = proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                rc = None
        tail = self.recent_stderr(10)
        extra = f"；最近的 stderr：{tail}" if tail else ""
        return McpServerGone(f"服务「{self.name}」的进程没了（退出码 {rc}）{extra}")

    # ── 工具（对外主要的两个动作）────────────────────

    def list_tools(self, refresh: bool = False) -> list[ToolDef]:
        if self._tool_cache is not None and not refresh and not self.list_changed:
            return list(self._tool_cache)
        tools: list[ToolDef] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            params = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            self._require_complete(result)
            for raw in result.get("tools") or []:
                td = _as_tool_def(raw)
                if td is not None:
                    tools.append(td)
            nxt = result.get("nextCursor")
            if not nxt:
                break
            cursor = str(nxt)
        self._tool_cache = tools
        self.list_changed = False
        return list(tools)

    def call_tool(
        self, name: str, arguments: dict | None = None, timeout: float | None = None
    ) -> dict:
        """调一个工具，返回原始 result（content / isError 都在里面）。"""
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout
        )
        self._require_complete(result)
        return result

    def call_tool_text(
        self, name: str, arguments: dict | None = None, timeout: float | None = None
    ) -> str:
        """调工具并把结果压成一段文本 —— 出错也是文本（工具层的铁律）。"""
        try:
            result = self.call_tool(name, arguments, timeout)
        except McpError as e:
            return f"MCP 工具 {self.name}.{name} 调用失败：{e}"
        return format_call_result(result)

    @staticmethod
    def _require_complete(result: dict) -> None:
        rt = result.get("resultType")
        if rt not in (None, "complete"):
            raise McpError(f"服务器回了不认识的 resultType：{rt!r}")

    # ── 收摊 ────────────────────────────────────────

    def stop(self) -> None:
        """送走进程：先关 stdin（按规矩它该自己退），不行再升级 TERM / KILL 两档。"""
        proc, self._proc = self._proc, None
        self._tool_cache = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=2)
        if proc.poll() is not None and proc.stderr is not None:
            try:
                rest = proc.stderr.read()
                if rest:
                    self._stderr_raw = (self._stderr_raw + rest)[-MAX_STDERR:]
            except (OSError, ValueError):
                pass
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if f:
                    f.close()
            except OSError:
                pass

    def describe(self) -> dict:
        return {
            "name": self.name,
            "era": self.era or "（还没谈过）",
            "version": self.version,
            "server_info": dict(self.server_info or {}),
            "tools": [t.name for t in self._tool_cache or []],
        }


# ── 结果压缩：给模型看的一段文本 ────────────────────


def format_call_result(result: dict) -> str:
    """把 MCP 的 content 数组压成一段文本；坏了也有话说，绝不抛异常。"""
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "image":
            parts.append("[图片]")
        elif kind == "audio":
            parts.append("[音频]")
        elif kind == "resource_link":
            parts.append(f"[链接：{item.get('uri') or '?'}]")
        elif kind == "resource":
            parts.append("[内嵌资源]")
        elif kind:
            parts.append(f"[{kind}]")
    if not parts:
        sc = result.get("structuredContent")
        if sc is not None:
            parts.append(json.dumps(sc, ensure_ascii=False))
    text = "\n".join(x for x in parts if x).strip() or "（空结果）"
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "……（结果太长，截断了）"
    if result.get("isError"):
        text = "工具执行出错：" + text
    return text


def _slug(text: str) -> str:
    """名字进注册表前的安全化：只留 ASCII 字母数字下划线连字符。"""
    s = re.sub(r"[^0-9A-Za-z_-]+", "_", text or "").strip("_")
    return s[:32] or "unnamed"


# ── 挂进工具层（「挂上去」就在这）──────────────────


def _bridged_fn(client: McpClient, tool_name: str) -> Callable[[dict], str]:
    def fn(args: dict) -> str:
        return client.call_tool_text(tool_name, args)

    return fn


def mount_client(client: McpClient) -> list[str]:
    """把某个 MCP 服务的工具挂进 Sammy 的工具表，返回这次新挂上的名字。

    名字前缀 mcp__服务__，一眼看得出是外挂工具，也不会和自带的撞名。
    """
    defs = client.list_tools()
    added: list[str] = []
    for td in defs:
        full = f"mcp__{_slug(client.name)}__{_slug(td.name)}"
        if full in _tools.REGISTRY:
            continue
        desc = td.description or f"来自 MCP 服务 {client.name} 的工具 {td.name}"
        _tools.REGISTRY[full] = _tools.Tool(
            name=full,
            description=desc,
            parameters=td.input_schema,
            fn=_bridged_fn(client, td.name),
        )
        added.append(full)
    old = _MOUNTED.get(client.name)
    if old is not None and old[0] is not client:
        with contextlib.suppress(Exception):
            old[0].stop()  # 同名服务换了个新进程：把旧的送走
    _MOUNTED[client.name] = (client, added)
    return added


def _unmount_tools(name: str) -> list[str]:
    prefix = f"mcp__{_slug(name)}__"
    gone = [k for k in list(_tools.REGISTRY) if k.startswith(prefix)]
    for k in gone:
        del _tools.REGISTRY[k]
    return gone


def unmount_client(name: str) -> list[str]:
    """摘掉某个服务的工具，顺带把它的进程送走。返回摘掉的名字。"""
    entry = _MOUNTED.pop(name, None)
    gone = _unmount_tools(name)
    if entry is not None:
        with contextlib.suppress(Exception):
            entry[0].stop()
    return gone


# ── 批量挂载（应用启动时走的路）────────────────────


@dataclass
class MountReport:
    config_path: Path | None = None
    mounted: dict[str, list[str]] = field(default_factory=dict)
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for name, names in self.mounted.items():
            lines.append(f"🧩 MCP 服务「{name}」挂上 {len(names)} 个工具：{', '.join(names)}")
        for name, why in self.failures:
            lines.append(f"⚠️ MCP 服务「{name}」没挂上：{why}")
        return lines


_MOUNTED: dict[str, tuple[McpClient, list[str]]] = {}
_atexit_done = False


def mount_from_config(path: str | Path | None = None) -> MountReport:
    """按 data/mcp.json 把所有启用的服务挂进工具表。

    铁律：绝不因为 MCP 挂不上而挡住 Sammy 启动 —— 起不来的服务
    进 failures 报告（界面或日志里提示一声），其它服务照常。
    """
    global _atexit_done
    report = MountReport(config_path=Path(path) if path else default_config_path())
    try:
        configs = load_config(path)
    except Exception as e:  # 配置坏了也只是「挂不上」，不是崩溃
        report.failures.append(("（配置）", f"{type(e).__name__}: {e}"))
        return report
    for cfg in configs:
        if not cfg.enabled:
            continue
        client = McpClient(cfg)
        try:
            client.start()
            report.mounted[cfg.name] = mount_client(client)
        except McpError as e:
            report.failures.append((cfg.name, str(e)))
            client.stop()
    if not _atexit_done:
        atexit.register(stop_all)
        _atexit_done = True
    return report


def stop_all() -> None:
    """收摊：把挂着的服务都送走、工具都摘掉（应用退出时的兜底）。"""
    for name in list(_MOUNTED):
        unmount_client(name)


__all__ = [
    "CLIENT_INFO",
    "LEGACY_VERSION",
    "META_SERVER_INFO",
    "META_VERSION",
    "MODERN_VERSION",
    "McpClient",
    "McpError",
    "McpRpcError",
    "McpServerGone",
    "McpTimeout",
    "MountReport",
    "ServerConfig",
    "ToolDef",
    "child_env",
    "default_config_path",
    "format_call_result",
    "load_config",
    "mount_client",
    "mount_from_config",
    "resolve_command",
    "spawn_spec",
    "stop_all",
    "unmount_client",
]
