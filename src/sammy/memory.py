"""Sammy 的记忆 —— 槽位 + 日记 + 夜里整理。

设计依据（docs/research/同类项目调研.md）：
- 学 Miru：**槽位（结构化事实）和日记（带日期的事件）分开存**，别混成一锅粥。
- 夜里整理：Sammy 睡着的时候跑摘要与归并 —— 和"它会犯困会睡觉"这个人设天然契合。
- 用便宜模型干整理，聊天才用好模型。

设计依据（docs/research/对标-NOMI与贾维斯.md）：
- 隐私原则：**原始感知数据不进长期记忆**，只存"结论"。
- NOMI 的"认得你"靠的就是槽位这种结构化档案。

存储位置：macOS 标准应用数据目录（不是项目目录）—— 项目在外置盘上，
拔盘不该丢记忆；而且它在备份清单里单独备份。
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

APP_DIR = pathlib.Path.home() / "Library" / "Application Support" / "Sammy"
DB_FILE = APP_DIR / "sammy.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    source      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS journal (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    day      TEXT NOT NULL,
    kind     TEXT NOT NULL,          -- event | explicit | digest | consolidation
    text     TEXT NOT NULL,
    tags     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_journal_day ON journal(day);
CREATE INDEX IF NOT EXISTS idx_journal_kind ON journal(kind);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 用户明确要求记住的说法 —— 命中就当作高优先级，不依赖模型判断
EXPLICIT_PATTERNS = (
    "记住",
    "帮我记",
    "记一下",
    "记得我",
    "别忘",
    "以后都",
    "我的偏好是",
    "记住我",
    "remember",
)


class Memory:
    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path else DB_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── 槽位：结构化事实 ────────────────────────────

    def set_slot(self, key: str, value: str, source: str = "") -> None:
        # 在**唯一的写入点**做归一化：上层不管传中文、大小写还是同义词，落库都是规范名。
        # （原来只 strip 一下，于是同一种事实能以不同 key 存进去 → 记忆越长越乱。）
        key = canonical_key(key)
        value = (value or "").strip()
        if not key or not value:
            return
        self.conn.execute(
            "INSERT INTO slots(key, value, updated_at, source) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, source=excluded.source",
            (key, value, time.time(), source),
        )
        self.conn.commit()

    def slots(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM slots ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def drop_slot(self, key: str) -> None:
        self.conn.execute("DELETE FROM slots WHERE key = ?", (key,))
        self.conn.commit()

    # ── 日记：带日期的事件 ──────────────────────────

    def add(self, text: str, kind: str = "event", tags: str = "", day: str | None = None) -> int:
        text = (text or "").strip()
        if not text:
            return -1
        day = day or date.today().isoformat()
        cur = self.conn.execute(
            "INSERT INTO journal(ts, day, kind, text, tags) VALUES(?,?,?,?,?)",
            (time.time(), day, kind, text, tags),
        )
        self.conn.commit()
        return cur.lastrowid or -1

    def recent(self, days: int = 3, include_digests: bool = True) -> list[sqlite3.Row]:
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        kinds = ("event", "explicit", "digest") if include_digests else ("event", "explicit")
        q = (
            "SELECT * FROM journal WHERE day >= ? AND kind IN "
            f"({','.join('?' * len(kinds))}) ORDER BY ts ASC"
        )
        return self.conn.execute(q, (since, *kinds)).fetchall()

    def day_entries(self, day: str, kinds=("event", "explicit")) -> list[sqlite3.Row]:
        q = (
            "SELECT * FROM journal WHERE day = ? AND kind IN "
            f"({','.join('?' * len(kinds))}) ORDER BY ts ASC"
        )
        return self.conn.execute(q, (day, *kinds)).fetchall()

    def has_digest(self, day: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM journal WHERE day = ? AND kind = 'digest' LIMIT 1", (day,)
        ).fetchone()
        return row is not None

    def stats(self) -> dict:
        s = self.conn.execute("SELECT COUNT(*) c FROM slots").fetchone()["c"]
        j = self.conn.execute("SELECT COUNT(*) c FROM journal").fetchone()["c"]
        d = self.conn.execute(
            "SELECT COUNT(DISTINCT day) c FROM journal WHERE kind='digest'"
        ).fetchone()["c"]
        first = self.conn.execute("SELECT MIN(day) d FROM journal").fetchone()["d"]
        return {"slots": s, "journal": j, "digests": d, "since": first, "db": str(self.path)}

    # ── 给提示词用的上下文 ──────────────────────────

    def context_block(self, max_chars: int = 700) -> str:
        """把记忆压成一段能塞进 system prompt 的文字。宁短不滥。"""
        parts: list[str] = []

        slots = self.slots()
        if slots:
            parts.append("【你记得关于 Rowan 的事】")
            parts.extend(f"- {k}：{v}" for k, v in slots.items())

        rows = self.recent(days=3)
        if rows:
            parts.append("\n【最近这几天】")
            cur_day = ""
            for r in rows:
                if r["day"] != cur_day:
                    cur_day = r["day"]
                    parts.append(f"{cur_day}:")
                mark = "★" if r["kind"] == "explicit" else ("◈" if r["kind"] == "digest" else "·")
                parts.append(f"  {mark} {r['text']}")

        if not parts:
            return ""
        block = "\n".join(parts)
        if len(block) > max_chars:
            block = block[: max_chars - 20].rstrip() + "\n…(更早的记不清细节了)"
        return block


# ── 对话后的记忆抽取 ────────────────────────────────

EXTRACT_PROMPT = """从下面这轮对话里，提取**值得长期记住**的信息。像人一样判断：只有以后还用得上的才记。

要提取的：
- 关于 Rowan 的稳定事实（昵称、工作、习惯、偏好、重要日期、关系、长期目标）
- 他明确说"记住"的事（这类必须提取）
- 有后续影响的事件（约定、承诺、正在做的事）

不要提取的：
- 寒暄、闲聊、临时情绪
- 你自己说的话
- 已经在上面的已知事实里出现过的重复内容

**只输出 JSON，不要任何其他文字。** 没有值得记的就输出 {{"slots":{{}},"journal":[]}}

格式：
{{"slots": {{"键": "值"}},
 "journal": ["一句话描述的事件"]}}

键用小写英文或中文短语，值要具体（"喜欢喝美式" 好过 "有咖啡偏好"）。

已知事实（别重复提取）：
{slots}

这轮对话：
Rowan：{user}
Sammy：{reply}"""


CONSOLIDATE_PROMPT = """你在整理 Sammy 一天里记下的事，压成一段能长期保留的摘要。

要求：
- 摘要 3-5 句，只留以后还用得上的（发生了什么、有什么进展、什么情绪底色）
- 顺手把新发现的**稳定事实**提取成槽位；已知的要修正就覆盖
- 只输出 JSON，不要任何其他文字

键**只能从下面这张表里挑**（挑最贴切的一个）：
name / nickname / age / city / residence / occupation / company /
current_project / machine / tools / hobbies / interests /
coffee_preference / diet / schedule / health / family / pets / language

表里实在没有合适的，才用 other_主题 的写法。
**不要自创同义词** —— 同一个事实换个键名，对你来说就是"又多了一件事"，会让记忆越长越乱。
值用简短名词短语，不要整句。

格式：
{{"digest": "一段摘要", "slots": {{"键": "值"}}}}

已知事实：
{slots}

{day} 这天记下的事：
{entries}"""


def _extract_json(raw: str) -> dict:
    """从模型输出里抠出 JSON 对象。模型爱加 ```json 包裹或前后废话，这里做容错。"""
    text = (raw or "").strip()
    if not text:
        return {}

    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                text = text[start : i + 1]
                break
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# 槽位 key 的规范名。
#
# 为什么必须有这个：key 不稳定 = 记忆不可靠。
# 实测过同一种事实，一次跑出来是 `name`、另一次是 `名字` —— 那么"更新一条事实"
# 就变成了"新增一条"，几个月后记忆里全是重复和自相矛盾。
# 这是和「情绪只能从固定表里挑」同一个套路：**把输出空间收窄，收敛才有保证。**
KEY_SYNONYMS: dict[str, str] = {
    # 名字
    "名字": "name",
    "姓名": "name",
    "user_name": "name",
    "full_name": "name",
    "称呼": "nickname",
    "昵称": "nickname",
    "小名": "nickname",
    # 机器 / 环境
    "电脑": "machine",
    "电脑型号": "machine",
    "设备": "machine",
    "主机": "machine",
    "机器": "machine",
    "computer": "machine",
    "device": "machine",
    # 项目 / 工作
    "项目": "current_project",
    "正在开发的项目": "current_project",
    "项目名称": "current_project",
    "project": "current_project",
    "project_name": "current_project",
    "职业": "occupation",
    "工作": "occupation",
    "job": "occupation",
    # 住
    "居住地": "residence",
    "住址": "residence",
    "城市": "city",
    "所在城市": "city",
    # 偏好
    "咖啡偏好": "coffee_preference",
    "饮食": "diet",
    "饮食偏好": "diet",
    "爱好": "hobbies",
    "兴趣": "hobbies",
    "interest": "hobbies",
    "宠物": "pets",
    "家人": "family",
}


def canonical_key(key: str) -> str:
    """把槽位 key 归一化：转小写、全角转半角、空白转下划线、中文同义词映射到规范名。

    未知的 key **原样保留（只做格式归一）**，不丢弃 ——
    宁可多一条不常见的槽位，也不能把用户说过的事悄悄丢掉。
    """
    k = str(key).strip().lower()
    k = k.translate(str.maketrans("．　－", "._-"))  # 全角 → 半角
    k = re.sub(r"[^\w]+", "_", k).strip("_")
    k = re.sub(r"_+", "_", k)
    return KEY_SYNONYMS.get(k, k)


def _clean_slots(slots) -> dict[str, str]:
    if not isinstance(slots, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in slots.items():
        key, val = canonical_key(k), str(v).strip()
        if key and val:
            out[key] = val  # 归一化后撞车的：后写的覆盖先写的
    return out


def parse_extraction(raw: str) -> dict:
    """模型输出 → {'slots': {...}, 'journal': [...]}"""
    data = _extract_json(raw)
    journal = data.get("journal") or []
    if not isinstance(journal, list):
        journal = []
    return {
        "slots": _clean_slots(data.get("slots")),
        "journal": [str(j).strip() for j in journal if str(j).strip()],
    }


def parse_digest(raw: str) -> dict:
    """模型输出 → {'digest': str, 'slots': {...}}"""
    data = _extract_json(raw)
    digest = str(data.get("digest") or "").strip()
    return {"digest": digest, "slots": _clean_slots(data.get("slots"))}


def looks_explicit(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(p in t for p in EXPLICIT_PATTERNS)


def today() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ── 服务层：把大脑和存储串起来（界面层只调这两个） ──────


def extract_and_store(brain, mem: Memory, user_text: str, reply: str) -> dict:
    """对话后抽取记忆并落库。在后台线程里跑，不占对话延迟。"""
    explicit = looks_explicit(user_text)
    if explicit:
        # 用户明确要求记住的，先原样存一条高优先级，不赌模型抽不抽得出来
        mem.add(user_text, kind="explicit", tags="user-asked")

    result = brain.extract_memories(user_text, reply, mem.slots())
    for k, v in result["slots"].items():
        mem.set_slot(k, v, source="extract")
    for item in result["journal"]:
        mem.add(item, kind="event")

    return {
        "explicit": explicit,
        "slots": len(result["slots"]),
        "journal": len(result["journal"]),
        "keys": list(result["slots"].keys()),
    }


def consolidate_now(brain, mem: Memory, day: str | None = None) -> dict:
    """立刻跑一次「夜里整理」。默认整理昨天（模拟睡了一觉）。"""
    day = day or (date.today() - timedelta(days=1)).isoformat()
    entries = [r["text"] for r in mem.day_entries(day)]
    if not entries:
        return {"day": day, "entries": 0, "digest": "", "new_slots": 0}

    result = brain.consolidate(day, entries, mem.slots())
    for k, v in result["slots"].items():
        mem.set_slot(k, v, source="consolidate")
    if result["digest"]:
        mem.add(result["digest"], kind="digest", day=day)

    return {
        "day": day,
        "entries": len(entries),
        "digest": result["digest"],
        "new_slots": len(result["slots"]),
    }


def needs_nightly(mem: Memory) -> str | None:
    """该整理哪一天？没有就返回 None。

    规则：**先把已经过完、但还没整理的日子补上**（最老的优先）——
    因为 Sammy 可能好几天没开机，"睡了一觉"要能补课。

    今天的只有在深夜（23 点后）才顺手整理；否则当天刚整理过，
    之后新增的记录就永远不会被整理了（这个 bug 真踩过）。
    """
    today_s = date.today().isoformat()
    rows = mem.conn.execute(
        "SELECT DISTINCT day FROM journal WHERE kind IN ('event','explicit') ORDER BY day"
    ).fetchall()
    for row in rows:
        day = row["day"]
        if day == today_s:
            continue
        if not mem.has_digest(day):
            return day

    if datetime.now().hour >= 23 and mem.day_entries(today_s) and not mem.has_digest(today_s):
        return today_s
    return None
