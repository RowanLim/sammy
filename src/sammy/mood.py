"""心情：Sammy 的**底色**，不是每条回复的情绪。

和驱力（`drives.py`）的分工：
- **驱力**是生理性的：精力 / 无聊 / 亲近 —— 决定它**想不想**说话、累不累；
- **心情**是情绪底色：最近过得好不好 —— 决定它**语气**和默认表情。

两个都要有：只有驱力，它像个会累的客服；只有心情，它像个情绪不稳的聊天机器人。

## 它怎么变（三条来源）

1. **每次回复的情绪**：大脑每轮回一个表情编号，开心/爱心往上推，难过/生气往下推。
   注意推的是**底色**，不是当下那张脸 —— 一件事不该把它整天定死。
2. **被戳一下**：小幅度 +（有人来逗它总是开心的）。
3. **长时间没人理**：慢慢往下走，**但有下限**。
   这条特别小心：不能因为没人理就变成怨妇 —— 那是**情感绑架**，
   陪伴产品最容易在这里翻车（"你怎么不理我"这种话一次就让人想卸载）。

## 两条硬规矩

- **一切变化都朝基线回归**（半衰期 6 小时）：心情不该被一件事绑架一整天。
- **落盘**（`data/mood.json`），重启不重置 —— 否则"它今天心情不错"这种连续性就断了。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .paths import data_dir

STATE_FILE = data_dir() / "mood.json"

# ── 参数 ──────────────────────────────────────────

HOME = 0.15  # 基线：略偏正面（它本来就是个乐呵的性子）
HALF_LIFE_H = 6.0  # 回归基线的半衰期（小时）
FLOOR = -0.45  # **下限**：再没人理也不许比这更低（防情感绑架）
CEILING = 1.0
NUDGE = 0.12  # 每次回复的情绪对底色的推动量
POKE_NUDGE = 0.06
ALONE_AFTER_H = 3.0  # 多久没人说话开始"有点蔫"
ALONE_RATE = 0.05  # 每小时往下多少
MAX_NOTES = 5

# 表情编号 → 对心情的方向（编号↔名字见 expressions.py）
POSITIVE_EXPRS = {
    3,
    4,
    7,
    14,
    20,
    21,
    23,
    24,
    29,
    32,
    34,
}  # 微笑 开心 惊喜 亲亲 星星眼 爱心 满足 燃 坏笑 期待 卖萌
NEGATIVE_EXPRS = {6, 10, 12, 17, 25, 31, 33}  # 伤心 生气 可怜 难受 邪恶 委屈 不悦

NOTE_UP = "聊得挺开心"
NOTE_DOWN = "有点不痛快"
NOTE_POKE = "被人逗了一下"
NOTE_ALONE = "安静好一阵了"


# ── 纯函数（判据都打在这几个上）─────────────────────


def clamp(v: float) -> float:
    return max(FLOOR, min(CEILING, float(v)))


def label_of(valence: float) -> str:
    """心情的说法。**分档要说人话**，别用"valance=0.3"这种。"""
    v = clamp(valence)
    if v <= -0.25:
        return "低落"
    if v < -0.05:
        return "有点蔫"
    if v < 0.25:
        return "平静"
    if v < 0.55:
        return "不错"
    return "很好"


def nudge_value(valence: float, expr: int, amount: float = NUDGE) -> float:
    """按这一轮回复的表情推一把底色。中性表情不动它。"""
    if expr in POSITIVE_EXPRS:
        return clamp(valence + amount)
    if expr in NEGATIVE_EXPRS:
        return clamp(valence - amount)
    return clamp(valence)


def decayed(
    valence: float, hours: float, home: float = HOME, half_life: float = HALF_LIFE_H
) -> float:
    """朝基线回归：过了一个半衰期，距离基线就只剩一半。"""
    if hours <= 0 or half_life <= 0:
        return clamp(valence)
    keep = 0.5 ** (hours / half_life)
    return clamp(home + (valence - home) * keep)


def alone_drift(valence: float, hours_alone: float) -> float:
    """没人理的时候往下走 —— **有下限，且只在超过 ALONE_AFTER_H 之后**。

    为什么要有下限：陪伴产品的"你不理我"一旦过头，就从陪伴变成负担。
    """
    if hours_alone <= ALONE_AFTER_H:
        return clamp(valence)
    return clamp(valence - ALONE_RATE * (hours_alone - ALONE_AFTER_H))


def prompt_line(valence: float, notes: list[str] | None = None) -> str:
    """塞进系统提示词的一句话 —— 让语气跟着底色走。"""
    v = clamp(valence)
    lab = label_of(v)
    if v <= -0.25:
        tip = "说话可以软一点、慢一点，但**不要抱怨对方不理你**"
    elif v < 0.25:
        tip = "平常心就行"
    elif v < 0.55:
        tip = "可以稍微轻快一点"
    else:
        tip = "可以明显活泼一点，但别浮夸"
    line = f"你今天的心情：{lab}（{tip}）"
    if notes:
        # 只带最近两条，别让提示词变成流水账
        line += "。刚才发生的事：" + "；".join(notes[-2:])
    return line


def idle_expression(valence: float) -> int:
    """空闲时默认该摆哪张脸（不是回复时的表情）。"""
    v = clamp(valence)
    if v <= -0.25:
        return 1  # 睡眠/蔫（用 1 这个最安静的脸）
    if v < 0.05:
        return 2  # 普通
    if v < 0.45:
        return 3  # 微笑
    return 23  # 满足


# ── 带状态的那层 ──────────────────────────────────


@dataclass
class Mood:
    valence: float = HOME
    updated: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "valence": round(self.valence, 4),
            "updated": self.updated,
            "notes": self.notes[-MAX_NOTES:],
        }


class MoodTracker:
    """读写心情。**坏文件不许让它崩** —— 心情读不出来就当默认值。"""

    def __init__(self, path=None, now: float | None = None) -> None:
        self.path = path or STATE_FILE
        self._now = now
        self.mood = self.load()

    # ── 落盘 ──
    def load(self) -> Mood:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return Mood(
                valence=clamp(float(raw.get("valence", HOME))),
                updated=float(raw.get("updated") or time.time()),
                notes=[str(n) for n in (raw.get("notes") or [])][-MAX_NOTES:],
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return Mood()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.mood.as_dict(), ensure_ascii=False), encoding="utf-8"
            )
        except OSError as e:
            print(f"  ⚠️ 心情存不下来（{e}）—— 不影响聊天")

    # ── 变化 ──
    def _note(self, text: str) -> None:
        self.mood.notes = [*self.mood.notes, text][-MAX_NOTES:]

    def nudge(self, expr: int) -> float:
        """按这一轮的表情推一把。"""
        before = self.mood.valence
        self.mood.valence = nudge_value(before, expr)
        if self.mood.valence > before:
            self._note(NOTE_UP)
        elif self.mood.valence < before:
            self._note(NOTE_DOWN)
        return self.mood.valence

    def poke(self) -> float:
        self.mood.valence = clamp(self.mood.valence + POKE_NUDGE)
        self._note(NOTE_POKE)
        return self.mood.valence

    def tick(self, now: float | None = None, hours_alone: float = 0.0) -> float:
        """每分钟调一次：先按时间回归基线，再算"没人理"的漂移。"""
        t = now if now is not None else (self._now or time.time())
        hours = max(0.0, (t - self.mood.updated) / 3600.0)
        self.mood.valence = decayed(self.mood.valence, hours)
        self.mood.valence = alone_drift(self.mood.valence, hours_alone)
        self.mood.updated = t
        return self.mood.valence

    # ── 给别人看 ──
    def label(self) -> str:
        return label_of(self.mood.valence)

    def prompt(self) -> str:
        """给大脑提示词用的一行（心情 + 最近发生的事）。"""
        return prompt_line(self.mood.valence, self.mood.notes)

    def describe(self) -> str:
        """给 `--mood` 打印。"""
        h = max(0.0, (time.time() - self.mood.updated) / 3600.0)
        lines = [
            f"心情：{self.label()}（{self.mood.valence:+.2f}）",
            f"上次更新：{h:.1f} 小时前",
            f"空闲时会摆的脸：{idle_expression(self.mood.valence)}",
            "最近影响它的事：" + ("；".join(self.mood.notes) if self.mood.notes else "（还没有）"),
        ]
        return "\n".join("  " + line for line in lines)


__all__ = [
    "ALONE_AFTER_H",
    "FLOOR",
    "HOME",
    "NEGATIVE_EXPRS",
    "POSITIVE_EXPRS",
    "STATE_FILE",
    "Mood",
    "MoodTracker",
    "alone_drift",
    "clamp",
    "decayed",
    "idle_expression",
    "label_of",
    "nudge_value",
    "prompt_line",
]
