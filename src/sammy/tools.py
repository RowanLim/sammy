"""Sammy 的工具层 —— 让它能联网思考。

设计原则：
1. **只用标准库**（树莓派上要好装，少一个依赖少一个坑）。
2. **工具永远返回字符串**：工具失败不是异常，是一条"我失败了"的结果交回给模型。
   模型看到失败还能换个说法回答，而不是把整个对话炸掉。
3. **安全护栏内建**：抓网页会解析 DNS 并拒绝内网/回环地址（SSRF 护栏）——
   Sammy 要能上网，但不该变成扫描你自己局域网的工具。
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Sammy/0.2 (+desktop pet)"
MAX_BYTES = 400_000


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., str]

    def schema(self) -> dict:
        """OpenAI function-calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── 安全护栏 ────────────────────────────────────────


def _host_is_public(host: str) -> tuple[bool, str]:
    """解析主机名，判断是不是公网地址。返回 (是否放行, 原因)。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return False, f"域名解析不了：{e}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, f"拒绝访问非公网地址（{ip}）—— Sammy 不上内网"
    return True, ""


def _http_get(url: str, timeout: int = 15) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"只支持 http/https，收到 {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL 里没有主机名")
    ok, why = _host_is_public(parsed.hostname)
    if not ok:
        raise ValueError(why)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# ── HTML → 文本 ─────────────────────────────────────


def html_to_text(raw: str) -> str:
    """粗糙但够用的正文提取：去脚本/样式/标签，压缩空白。"""
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)  # 换行两侧的空格是噪音，对模型没用
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


# ── 工具实现 ────────────────────────────────────────


def current_time(_: dict | None = None) -> str:
    """Sammy 之前老实说"我没办法获取实时日期" —— 这个工具就是补这个洞。"""
    now = datetime.now()
    week = "一二三四五六日"[now.weekday()]
    return f"现在是 {now:%Y-%m-%d %H:%M}，星期{week}（本地时间，时区 {time.tzname[0]}）"


def web_search(args: dict) -> str:
    """DuckDuckGo 的 HTML 版，不需要任何 key。"""
    query = str(args.get("query") or "").strip()
    if not query:
        return "搜索失败：query 是空的"
    limit = int(args.get("max_results") or 5)
    limit = max(1, min(limit, 8))

    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        raw = _http_get(url, timeout=20)
    except Exception as e:
        return f"搜索失败了（{type(e).__name__}: {e}）。可以告诉我你不知道，或者换个问法。"

    hits = parse_ddg(raw, limit)
    if not hits:
        return f"没搜到「{query}」的结果（也可能被搜索服务限流了）。"

    lines = [f"关于「{query}」搜到 {len(hits)} 条："]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h['title']}\n   {h['url']}\n   {h['snippet']}")
    lines.append("\n（要细看某一条就调 fetch_url 抓它的正文）")
    return "\n".join(lines)


def parse_ddg(raw: str, limit: int = 5) -> list[dict]:
    """从 DDG HTML 结果页里抠出标题/链接/摘要。"""
    hits: list[dict] = []
    # 结果块：<a ... class="result__a" href="...">标题</a> ... <a class="result__snippet" ...>摘要</a>
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        raw,
        re.S,
    ):
        href, title_html = m.group(1), m.group(2)
        link = _clean_ddg_url(href)
        tail = raw[m.end() : m.end() + 4000]
        snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', tail, re.S)
        hits.append(
            {
                "title": html_to_text(title_html)[:160] or "(无标题)",
                "url": link,
                "snippet": html_to_text(snip.group(1))[:320] if snip else "",
            }
        )
        if len(hits) >= limit:
            break
    return hits


def _clean_ddg_url(href: str) -> str:
    """DDG 的链接常是 /l/?uddg=<encoded> 的跳转形式，取出真地址。"""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        q = urllib.parse.urlparse(href).query
        real = urllib.parse.parse_qs(q).get("uddg", [""])[0]
        if real:
            return real
    return href


def fetch_url(args: dict) -> str:
    """抓一个网页的正文。"""
    url = str(args.get("url") or "").strip()
    if not url:
        return "抓取失败：url 是空的"
    limit = int(args.get("max_chars") or 3000)
    limit = max(500, min(limit, 8000))
    try:
        raw = _http_get(url)
    except Exception as e:
        return f"抓取失败了（{type(e).__name__}: {e}）"

    text = html_to_text(raw)
    if len(text) > limit:
        text = text[:limit] + f"\n…（后面还有 {len(text) - limit} 字，需要就再说）"
    return f"{url} 的正文：\n{text}" if text else f"{url} 抓到了内容，但正文是空的"


REGISTRY: dict[str, Tool] = {
    "current_time": Tool(
        name="current_time",
        description="获取当前的日期、时间和星期。任何和'现在''今天''几点了'有关的问题都要先调它，不要靠猜。",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=lambda args: current_time(args),
    ),
    "web_search": Tool(
        name="web_search",
        description="联网搜索。用于查最新消息、你不确定的事实、或者你自己的知识可能过期的事情。返回标题、网址和摘要。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，像人一样自然描述"},
                "max_results": {"type": "integer", "description": "返回条数，默认 5"},
            },
            "required": ["query"],
        },
        fn=web_search,
    ),
    "fetch_url": Tool(
        name="fetch_url",
        description="抓取一个网页的正文内容。搜索结果里的链接要用它才能看到详细内容。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整网址，http 或 https 开头"},
                "max_chars": {"type": "integer", "description": "最多取多少字，默认 3000"},
            },
            "required": ["url"],
        },
        fn=fetch_url,
    ),
}


def schemas(names: list[str] | None = None) -> list[dict]:
    picked = names or list(REGISTRY)
    return [REGISTRY[n].schema() for n in picked if n in REGISTRY]


def call(name: str, arguments: dict | str) -> str:
    """执行工具。**永远返回字符串** —— 失败也是字符串，不抛异常给对话。"""
    tool = REGISTRY.get(name)
    if tool is None:
        return f"没有叫 {name!r} 的工具。可用的：{', '.join(REGISTRY)}"
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"参数不是合法 JSON：{arguments[:120]}"
    if not isinstance(arguments, dict):
        return "参数格式不对，应该是一个对象"
    try:
        return str(tool.fn(arguments))
    except Exception as e:
        return f"工具 {name} 执行出错（{type(e).__name__}: {e}）"


__all__ = ["REGISTRY", "Tool", "call", "current_time", "html_to_text", "parse_ddg", "schemas"]
