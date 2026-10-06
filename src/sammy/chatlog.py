"""对话记录（PRD P1-11）：可查、可清空。

**为什么和记忆分开**：`data/sammy.db` 里存的是**记忆**（槽位 + 日记，是 Sammy
"记住的事"），这里存的是**流水**（谁在哪一秒说了什么）。两件事混在一起会有个坏结果：
"清空对话记录"会连带把记忆删掉 —— 而用户想擦掉的只是聊天流水。

**格式用 JSONL**（一行一条）：这是追加写的流水，坏了最坏丢一行；
换成数据库，一旦损坏会把整段历史一起锁住。追加 + 逐行解析最抗损。

**为什么要有轮换**：它是长期跑的陪伴程序，流水会一直长。
在树莓派那种小存储上不能无限长，所以超过上限就把旧记录轮换成 `.1`。
"""

from __future__ import annotations

import contextlib
import json
import time

from .paths import data_dir

LOG_FILE = data_dir() / "chat.jsonl"
ROTATED = LOG_FILE.with_name(LOG_FILE.name + ".1")
MAX_BYTES = 2 * 1024 * 1024  # 2MB ≈ 上万条，够回看，又不会把设备塞满


def _rotate_if_needed() -> None:
    """太大就把当前记录挪成 `.1`（覆盖上一次轮换）。"""
    try:
        if LOG_FILE.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return
    with contextlib.suppress(OSError):
        LOG_FILE.replace(ROTATED)


def append(role: str, text: str, when: float | None = None, kind: str = "") -> None:
    """记一条。**写不进去也不该影响聊天** —— 打一行日志就继续。"""
    if not text:
        return
    line = json.dumps(
        {
            "t": round(when if when is not None else time.time(), 1),
            "role": str(role),
            "text": str(text),
            "kind": kind,
        },
        ensure_ascii=False,
    )
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed()
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"  ⚠️ 对话记录写不进去（{e}）—— 不影响聊天")


def _read(path) -> list[dict]:
    """读一个文件。**坏行跳过** —— 记录坏了不该让"查看"整个失败。"""
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("text"):
            out.append(item)
    return out


def recent(n: int = 20) -> list[dict]:
    """最近 n 条，**旧的在前**（含轮换过的旧记录）。"""
    if n <= 0:
        return []
    items = _read(ROTATED) + _read(LOG_FILE)
    return items[-n:]


def count() -> int:
    return len(_read(ROTATED)) + len(_read(LOG_FILE))


def clear() -> int:
    """清空对话记录，返回删掉多少条。

    ⚠️ **只动流水，不碰记忆**（记忆在 `sammy.db` 里 —— 那是 Sammy 记住的事，
    擦掉记忆等于把它变成陌生人，那是另一件事，得单独决定）。
    """
    n = count()
    for p in (LOG_FILE, ROTATED):
        with contextlib.suppress(FileNotFoundError):
            p.unlink()
    return n


def format_recent(n: int = 20) -> str:
    """给 `--history` 打印用。"""
    items = recent(n)
    if not items:
        return "（还没有对话记录）"
    who = {"user": "你", "assistant": "Sammy"}
    lines = []
    for it in items:
        ts = time.strftime("%m-%d %H:%M", time.localtime(float(it.get("t") or 0)))
        name = who.get(it.get("role", ""), it.get("role", "?"))
        tag = "（主动）" if it.get("kind") == "proactive" else ""
        lines.append(f"  [{ts}] {name}{tag}：{it['text']}")
    return "\n".join(lines) + f"\n\n  共 {count()} 条，显示最近 {len(items)} 条"


__all__ = ["LOG_FILE", "MAX_BYTES", "append", "clear", "count", "format_recent", "recent"]
