"""回忆主动性 —— 让「主动开口」有时带上它想起的旧事。

为什么要有：之前每一次主动开口，由头都是"无聊 / 想你 / 关心你"，
和"它记得的事"没有关系 —— 那更像一个会定时的客服。
像活物的一个关键瞬间是：**它会在某个时刻突然想起你说过的一件事。**

为什么必须有闸门（和 attention.py 同一条哲学：默认沉默）：
- **刚说过的不提**：刚提过的（冷却期）、聊天里刚聊到的，都不算"想起"，
  硬提就像在念档案，一眼假；
- **一天最多提几次**：这是"活物感"最容易过火的地方 —— 宁可少，不能腻；
- **不该提的别乱提**：住址、健康、凭证类的东西，以及纯技术配置，
  它不该随口把这些翻出来。

和 attention / care 的关系：回忆不是独立触发的一条路 ——
它是在"要不要先开口"**通过之后**，决定"开口说什么"时的第一选项。
配额分账：回忆有自己的每日上限，同时照常消耗主动开口的额度。
"""

from __future__ import annotations

import json
import pathlib
import random
import re
import time
from dataclasses import dataclass, field

from .paths import data_dir

# ── 闸门参数（调参只改这一段）─────────────────────

MAX_RECALLS_PER_DAY = 2  # 一天最多提几次旧事（主动开口总共 ≤3/天，回忆占其中一部分）
ITEM_COOLDOWN_DAYS = 7  # 同一件事提过一次，一周内不再提
SAID_WINDOW_HOURS = 48  # 聊天里 48 小时内出现过的话题，算"刚说过"
ELIGIBLE_AFTER_HOURS = 24  # 24 小时内的事不算"想起"（那是接着聊，不是回忆）
ELIGIBLE_BEFORE_DAYS = 90  # 太久远的也别翻（对不上现在的上下文）
MAX_TEXT_LEN = 200  # 太长的不适合当话题（把摘要整段端出来很奇怪）
PRUNE_AFTER_DAYS = ITEM_COOLDOWN_DAYS * 2  # 冷却记录留两倍冷却期就够，别让状态文件无限长

STATE_FILE = data_dir() / "recall.json"

# 各类旧事的"份量"：用户明确让记的 > 当天事件 > 槽位事实 > 日记摘要
KIND_WEIGHTS = {"explicit": 4.0, "event": 3.0, "slot": 2.0, "digest": 1.0}

# 「不该提的」之一：这些槽位 key 永远不进话题池
BLOCKED_KEYS = {
    "residence",  # 住址：私密，不该被它随口提起
    "health",  # 健康：主动挑起来说很冒昧
    "machine",  # 机器配置：像在念档案，不是聊天
    "tools",  # 同上
    "language",  # 同上
}
KEY_BADWORDS = (
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "api_key",
    "apikey",
    "密码",
    "口令",
    "密钥",
)
_KEY_BAD_RE = re.compile(r"(^|_)keys?($|_)")

# 「不该提的」之二：内容里带这些词的一律不进话题池（凭证类、隐私类）
CONTENT_BADWORDS = (
    "密码",
    "口令",
    "密钥",
    "验证码",
    "token",
    "api key",
    "apikey",
    "secret",
    "passwd",
    "password",
    "credential",
    "身份证",
    "银行卡",
    "信用卡",
    "手机号",
    "住址",
)

_NORM_RE = re.compile(r"[\s\W_]+")
_SAY_GRAM = 4  # "刚说过"判定用的 n-gram 长度（见 _was_said_recently）


@dataclass(frozen=True)
class RecallItem:
    """一条可提的旧事。id 要**跨重启稳定** —— 冷却记录认的就是它。"""

    id: str  # slot:{key} / journal:{rowid}
    kind: str  # explicit / event / slot / digest
    text: str  # 放进指令里的原文
    weight: float
    norm: str  # 归一化后的"话题核心"（判重、判"刚说过"用）


@dataclass(frozen=True)
class RecallGate:
    """一次判断的结果。`reason` 给调参看，`item` 是挑中的旧事（如果通过）。"""

    ok: bool
    reason: str
    item: RecallItem | None = None
    candidates: int = 0

    def __bool__(self) -> bool:
        return self.ok


def _norm(text: str) -> str:
    """归一化：只留字母 / 数字 / 汉字，去掉空白与标点（大小写也统一）。"""
    return _NORM_RE.sub("", str(text).lower())


def _slot_key_blocked(key: str) -> bool:
    k = str(key).lower()
    if k in BLOCKED_KEYS or k.startswith("sammy"):
        return True
    return any(b in k for b in KEY_BADWORDS) or bool(_KEY_BAD_RE.search(k))


def _text_ok(text: str) -> bool:
    if len(text) < 2 or len(text) > MAX_TEXT_LEN:
        return False
    low = text.lower()
    return not any(b in low for b in CONTENT_BADWORDS)


def candidates(mem, *, now: float | None = None) -> list[RecallItem]:
    """把记忆里"值得想起的事"翻出来（闸门在 decide 里，这里只筛资格）。

    **记忆坏了不该连累开口** —— 读不出来就当没有候选，不往上抛错。
    槽位给 key：value 全文；日记给原文；一字不差的重复只留一份
    （同一条被抽进过事件、又进过槽位这种事真实存在）。
    """
    now = now if now is not None else time.time()
    out: list[RecallItem] = []
    if mem is None:
        return out

    try:
        slots = mem.slots() or {}
    except Exception:
        slots = {}
    for key, val in slots.items():
        if _slot_key_blocked(key):
            continue
        val = str(val or "").strip()
        if not _text_ok(val):
            continue
        out.append(
            RecallItem(
                id=f"slot:{key}",
                kind="slot",
                text=f"{key}：{val}",
                weight=KIND_WEIGHTS["slot"],
                norm=_norm(val),
            )
        )

    getter = getattr(mem, "entries_between", None)
    rows = []
    if getter is not None:
        try:
            rows = getter(
                now - ELIGIBLE_BEFORE_DAYS * 86400,
                now - ELIGIBLE_AFTER_HOURS * 3600,
            )
        except Exception:
            rows = []
    for row in rows:
        text = str(row["text"] or "").strip()
        if not _text_ok(text):
            continue
        kind = row["kind"] if row["kind"] in KIND_WEIGHTS else "event"
        out.append(
            RecallItem(
                id=f"journal:{row['id']}",
                kind=kind,
                text=text,
                weight=KIND_WEIGHTS[kind],
                norm=_norm(text),
            )
        )

    ordered = sorted(out, key=lambda c: (-c.weight, c.id))
    kept: list[RecallItem] = []
    for it in ordered:
        if any(it.norm == k.norm for k in kept):
            continue
        kept.append(it)
    kept.sort(key=lambda c: c.id)  # 顺序稳定，固定种子才可复现
    return kept


def _was_said_recently(cand_norm: str, recent_norm: str) -> bool:
    """聊天里是不是刚出现过这件事。

    用 n-gram 交集而不是整串相等：聊天里聊到"树莓派小车"时，
    记忆里的句子不会一字不差地出现。宁可多挡（少提一次不亏），
    不可漏挡（刚聊过又"想起来"，一眼假）。
    """
    if not cand_norm or not recent_norm:
        return False
    if len(cand_norm) < _SAY_GRAM:
        return cand_norm in recent_norm
    return any(
        cand_norm[i : i + _SAY_GRAM] in recent_norm for i in range(len(cand_norm) - _SAY_GRAM + 1)
    )


def chat_text_since(messages, *, now: float | None = None, hours: float = SAID_WINDOW_HOURS) -> str:
    """把最近一段时间的聊天文本拼起来 —— "刚说过"判定的原料。"""
    now = now if now is not None else time.time()
    cutoff = now - hours * 3600
    parts = []
    for m in messages or []:
        try:
            t = float(m.get("t") or 0)
        except (TypeError, ValueError):
            continue
        if t >= cutoff and m.get("text"):
            parts.append(str(m["text"]))
    return "\n".join(parts)


@dataclass
class Recaller:
    """回忆的账本：今天提过几次、每条最近什么时候提过。全部落盘 ——
    重启不该把"刚提过"忘掉（和 attention 同一条理由：能靠重启重置的限制不算限制）。"""

    day: str = ""
    recalled_today: int = 0
    recent_items: dict[str, float] = field(default_factory=dict)
    _log: list[str] = field(default_factory=list, repr=False)

    # ── 判断 + 挑选 ────────────────────────────────

    def decide(self, mem, *, now=None, recent_text: str = "", rng=None) -> RecallGate:
        """能不能提、提哪一条。**每次拒绝都给出理由**（和 attention 的规矩一样）。"""
        now = now if now is not None else time.time()
        self._roll_over(now)
        self._heal(now)

        if self.recalled_today >= MAX_RECALLS_PER_DAY:
            return RecallGate(False, f"今天已经提过 {self.recalled_today} 次旧事了，够了")

        pool = candidates(mem, now=now)
        if not pool:
            return RecallGate(False, "手头没有可以想起的旧事")

        alive = [c for c in pool if not self._cooling(c.id, now)]
        if recent_text:
            recent_norm = _norm(recent_text)
            alive = [c for c in alive if not _was_said_recently(c.norm, recent_norm)]
        if not alive:
            return RecallGate(False, f"有 {len(pool)} 条旧事，但都刚提过或刚聊到，先不提")

        roller = rng if rng is not None else random
        item = roller.choices(alive, weights=[i.weight for i in alive], k=1)[0]
        return RecallGate(
            True,
            f"想起来了：{item.text[:18]}（{item.kind}）",
            item=item,
            candidates=len(alive),
        )

    def note_recalled(self, item_id: str, now=None) -> None:
        """真把它说出口了才记账 —— 生成失败不该消耗机会（和 attention 同规矩）。"""
        now = now if now is not None else time.time()
        self._roll_over(now)
        self.recent_items[str(item_id)] = now
        self.recalled_today += 1
        self._heal(now)
        self._log.append(f"{time.strftime('%H:%M')} 提起 {item_id}")

    # ── 内部 ────────────────────────────────────────

    def _cooling(self, item_id: str, now: float) -> bool:
        ts = self.recent_items.get(item_id)
        return ts is not None and (now - ts) < ITEM_COOLDOWN_DAYS * 86400

    def _heal(self, now: float) -> None:
        """清两种坏账：未来的时间戳（时钟倒退 / 跨时区）和过期的冷却记录。

        坏数据要能自愈 —— 一条落在未来的记录如果不清，会把功能**永久锁死**
        （attention.py 里踩过同款坑）。
        """
        for k in list(self.recent_items.keys()):
            ts = self.recent_items[k]
            if ts > now or (now - ts) > PRUNE_AFTER_DAYS * 86400:
                del self.recent_items[k]

    def _today(self, now: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now))

    def _roll_over(self, now: float) -> None:
        today = self._today(now)
        if self.day != today:
            self.day = today
            self.recalled_today = 0

    # ── 持久化 ──────────────────────────────────────

    def save(self, path: pathlib.Path | None = None) -> None:
        path = path or STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "day": self.day,
            "recalled_today": self.recalled_today,
            "recent_items": self.recent_items,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> Recaller:
        path = path or STATE_FILE
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}  # type: ignore[attr-defined]
        raw = {k: v for k, v in data.items() if k in known}
        raw.pop("recent_items", None)
        try:
            r = cls(**raw)
        except TypeError:
            return cls()
        items = data.get("recent_items")
        if isinstance(items, dict):
            r.recent_items = {
                str(k): float(v)
                for k, v in items.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        return r


# ── 先开口说什么：想起了旧事 ────────────────────────

RECALL_INSTRUCTION = (
    "[这是你主动开的口，不是用户在跟你说话]\n"
    "你想起了这样一件事：{text}\n"
    "规则：一句话，不超过 25 字；像聊天时自然想起来了那样说（'对了…'那种感觉）；"
    "别念档案（不许说'根据我的记录'这种）；不要问'需要帮忙吗'。"
)


def recall_prompt(text: str) -> str:
    return RECALL_INSTRUCTION.format(text=text)


__all__ = [
    "BLOCKED_KEYS",
    "ELIGIBLE_AFTER_HOURS",
    "ELIGIBLE_BEFORE_DAYS",
    "ITEM_COOLDOWN_DAYS",
    "KIND_WEIGHTS",
    "MAX_RECALLS_PER_DAY",
    "MAX_TEXT_LEN",
    "STATE_FILE",
    "RecallGate",
    "RecallItem",
    "Recaller",
    "candidates",
    "chat_text_since",
    "recall_prompt",
]
