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

## 第二根轴：**劲头**（spirit）

一根轴只说得清「今天过得好不好」，说不清「今天过得热闹还是冷清」。
而这两件事对一张脸的影响是不同的：过得**好**嘴角往上走；过得**冷清**
（一直没人理、也没发生什么事）眼神该发飘、脑袋该放空。

所以加第二根轴 —— 但**落盘还是只存一个数**：劲头从 `valence`
与 `notes`（最近发生的事）**算出来**（`spirit_from`），不新增要迁移的字段。
理由：多一个字段就多一类「文件坏了/旧文件读不出」的故障面，
而算出来的东西永远不会和已有的数打架。

两根轴都**不许互相代理**：推劲头不碰 `valence`，默认表情仍由第一根轴单独决定
（`idle_expression_for` 只是把它写成显式接口，数一个不变）。

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

# ── 第二根轴：劲头 ────────────────────────────────
# 0 = 平常，+1 = 来劲/兴奋，-1 = 发蔫/走神
SPIRIT_HOME = 0.0
SPIRIT_NUDGE = 0.18  # 每轮回复对劲头的推动量（比心情大一档：热闹是看得出来的）
SPIRIT_POKE = 0.10  # 被戳一下
SPIRIT_ALONE_RATE = 0.04  # 没人理时每小时往下多少（与 ALONE_RATE 同量级）
# 谱的两头：劲头 >= SPIRIT_UP 叫「来劲」，<= SPIRIT_DOWN 叫「发蔫」
SPIRIT_UP = 0.5
SPIRIT_DOWN = -0.5
# 劲头这五档的切点，按**下界（含）**记，四刀切五档：
#   走神 | 偏蔫 | 平常 | 偏活 | 兴奋
# SPIRIT_HOME = 0.0 落在**正中间**那档（判据 test_the_flat_spirit_lands_in_the_middle_band 钉着）。
# 第一版写成位置索引（SPIRIT_CUTS[1]）取用，结果「偏活」那档永远轮不到 ——
# 这种错外面看不出来（每档都还有名字），所以另有一条判据扫「每个词都得真的用得上」。
SPIRIT_GLUM = -0.5
SPIRIT_MILD_DOWN = -0.15
SPIRIT_MILD_UP = 0.15
SPIRIT_CUTS = (SPIRIT_GLUM, SPIRIT_MILD_DOWN, SPIRIT_MILD_UP, SPIRIT_UP)


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

# 劲头往上：不是「开心」就算热闹，而是**真的闹起来了**（大笑/搞怪/新奇/期待）。
# 微笑（3）故意不算 —— 它太常见，算了就等于劲头一直高位，等于常量。
LIVELY_EXPRS = {4, 7, 14, 20, 21, 23, 24, 34}  # 大笑 惊喜 亲亲 星星眼 爱心 燃 坏笑 期待
# 劲头往下：**没精神**的那几张脸。负面情绪故意不算 —— 难过是往下那根轴的事，
# 不是「没劲」那根轴的事，两根轴不该互相代理。
DULL_EXPRS = {1, 5}  # 睡眠 困

NOTE_UP = "聊得挺开心"
NOTE_DOWN = "有点不痛快"
NOTE_POKE = "被人逗了一下"
NOTE_ALONE = "安静好一阵了"
NOTE_LIVELY = "热闹了一下"
NOTE_SLEEPY = "困得不行"


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


def shrink_for(valence: float, anim_on: bool, asleep: bool) -> float:
    """心情落进「有点蔫」后，它的静止姿态自己收一小圈（效果看不到「在动」，但看得出「没精神」）。
    动画关或睡着时回 1.0（闸门在这里统一道）。
    """
    from . import anim as _anim

    if not anim_on or asleep:
        return 1.0
    return _anim.mood_shrink(valence)


# ── 全谱：一张 5 x 5 的表，一格一个字 ──────────────
# 行＝劲头（0 走神 / 1 偏蔫 / 2 平常 / 3 偏活 / 4 兴奋），列＝心情（低落…很好）。
# 写成表而不是 if 阶梯：改一格、漏一格、词用不上，都看得见。
SPECTRUM = (
    ("空落落的", "发蔫", "放空", "悠着", "安安静静地高兴"),
    ("提不起劲", "有点闷", "有点走神", "有点懒懒的", "静静的满足"),
    ("低落", "有点蔫", "还行", "挺轻松", "心情挺好"),
    ("提不起劲", "有点闷", "挺有兴致", "挺来劲的", "兴致很高"),
    ("心里堵得慌", "有点坐不住", "有点躁", "挺来劲的", "兴致很高"),
)

# ── 第二根轴：纯函数（判据都打在这几个上）────────────


def clamp_spirit(v: float) -> float:
    return max(-1.0, min(1.0, float(v)))


def spirit_nudge(spirit: float, expr: int) -> float:
    """按这一轮回复的表情推一把劲头。中性/平静的开心都不动它。"""
    if expr in LIVELY_EXPRS:
        return clamp_spirit(spirit + SPIRIT_NUDGE)
    if expr in DULL_EXPRS:
        return clamp_spirit(spirit - SPIRIT_NUDGE)
    return clamp_spirit(spirit)


def spirit_alone(spirit: float, hours_alone: float) -> float:
    """实在没意思的时候自己往下走 —— **和心情共用同一道闸门**（ALONE_AFTER_H）。

    单独一套时间常数就会变成两套作息，迟早打架。
    """
    if hours_alone <= ALONE_AFTER_H:
        return clamp_spirit(spirit)
    return clamp_spirit(spirit - SPIRIT_ALONE_RATE * (hours_alone - ALONE_AFTER_H))


def spirit_decayed(spirit: float, hours: float, half_life: float = HALF_LIFE_H) -> float:
    """劲头也朝平常回归：热闹过完一阵子会淡下来，但比心情快（半衰期取一半）。"""
    if hours <= 0 or half_life <= 0:
        return clamp_spirit(spirit)
    keep = 0.5 ** (hours / (half_life / 2.0))
    return clamp_spirit(SPIRIT_HOME + (spirit - SPIRIT_HOME) * keep)


def note_effect(text: str) -> float:
    """一件事对劲头的影响。**只有两种事会动它**：聊得热闹 / 实在没劲。"""
    if text == NOTE_LIVELY:
        return 1.0
    if text == NOTE_SLEEPY:
        return -1.0
    return 0.0


def spirit_from(valence: float, notes: list[str] | None = None, hours_alone: float = 0.0) -> float:
    """从**文件里读得到**的东西算劲头：心情 + 最近发生的事 + 多久没人理。

    为什么不落盘：多一个字段就多一类「旧文件读不出」的故障面；
    而算出来的东西永远不会和已有的数打架。
    """
    v = clamp(valence)
    s = 0.0
    if v >= 0.55:
        s += 0.4  # 心情好本身就是「有劲」的一部分
    elif v <= -0.25:
        s -= 0.3
    for note in (notes or [])[-3:]:
        s += 0.25 * note_effect(note)
    if v <= -0.05 and s > 0.2:
        # 「心里堵」：不好的心情会把亢奋压住（不是删掉这一格，是别让它变成乱闹）
        s *= 0.6
    return spirit_alone(clamp_spirit(s), hours_alone)


def spectrum_label(valence: float, spirit: float) -> str:
    """两根轴合起来说人话 —— `describe()`（也就是 `--mood`）用这个。

    写法：**一张 5 x 5 的表，一格一个字**（TABLE 就在函数上面，改哪儿一眼看得见）。
    第一版写成了一串 if 阶梯，结果出了个外面看不出来的 bug：
    「偏活」那一档被位置索引算进了别的档，成了死代码 —— 表里那格有名字，
    只是那个名字永远轮不到（判据 test_the_spectrum_is_full 只查「有没有名字」，
    查不出「这个词永远用不上」）。所以后面加了一条：**每个名字都得真的出现**。

    规矩两条：
    - 基线 0.15 是**略偏正面**，不该被叫「平静」（那是不好不坏的意思）；
    - 低落那一路（valence ≤ -0.05）且劲头低的时候，名字里**不许出现好词**
      —— 陪伴产品在这上面翻过车。这两条都有判据扫。
    """
    return SPECTRUM[spirit_band_of(spirit)][band_of(valence)]


def band_of(valence: float) -> int:
    """第一根轴落哪一档（0 低落 / 1 有点蔫 / 2 平静 / 3 不错 / 4 很好）。

    判定顺序从低档往上，**用 `label_of` 的同一套边界**（它先写、被多份判据钉着）：
    `label_of` 里 -0.25 是「低落」、-0.05 是「平静」、0.55 是「很好」，
    所以这里也用 `<= / <` 的同一套归属 —— 判据 test_bands_agree_with_label_of 钉着。
    """
    v = clamp(valence)
    if v <= -0.25:
        return 0
    if v < -0.05:
        return 1
    if v < 0.25:
        return 2
    if v < 0.55:
        return 3
    return 4


def spirit_band_of(spirit: float) -> int:
    """第二根轴落哪一档（0 走神 / 1 偏蔫 / 2 平常 / 3 偏活 / 4 兴奋）。

    切点 `SPIRIT_CUTS` 按**下界（含）**记，中间那档以 `SPIRIT_HOME = 0.0` 为中心：
    ±0.15 之内是平常，`SPIRIT_UP = 0.5` 以上是兴奋。
    `SPIRIT_HOME` 必须落在**正中间**（2 平常）—— 判据钉着这条。
    """
    s = clamp_spirit(spirit)
    band = 0
    for cut in SPIRIT_CUTS:
        if s >= cut:
            band += 1
    return band


def spirit_hint(valence: float, spirit: float) -> str | None:
    """给提示词接的一句（只在两头出现，中间什么都不加 —— 别把提示词写成流水账）。"""
    s = clamp_spirit(spirit)
    v = clamp(valence)
    if -SPIRIT_UP < s < SPIRIT_UP:
        return None
    if v <= -0.05 and s > 0:
        return "你现在心里不太痛快、又有点躁 —— **别闹**，也别亢奋地安慰自己"
    if s > 0:
        return "你现在兴致挺高 —— 可以主动找点话说，但别吵"
    if v <= -0.05:
        return "你现在有点发蔫 —— 答话短一点没关系，不用硬撑"
    return "你现在有点走神 —— 像在想别的事，别急着找话说"


def idle_expression_for(valence: float, spirit: float) -> int:
    """默认摆哪张脸。**数上与加第二根轴之前一字不差** —— 现在仍由第一根轴单独决定。

    写成显式接口只是为了让「劲头不许碰默认表情」这条有个可打的靶子；
    哪天真有真机观感了，改的也是这一处。
    """
    return idle_expression(valence)


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

    def spirit(self, now: float | None = None) -> float:
        """它此刻的劲头（算出来的，不落盘）。"""
        t = now if now is not None else time.time()
        hours = max(0.0, (t - self.mood.updated) / 3600.0)
        s = spirit_from(self.mood.valence, self.mood.notes)
        return spirit_decayed(s, hours)

    def describe(self, now: float | None = None) -> str:
        """给 `--mood` 打印。"""
        t = now if now is not None else time.time()
        h = max(0.0, (t - self.mood.updated) / 3600.0)
        s = self.spirit(now=t)
        lines = [
            f"心情：{self.label()}（{self.mood.valence:+.2f}）",
            f"劲头：{spectrum_label(self.mood.valence, s)}（{s:+.2f}）",
            f"上次更新：{h:.1f} 小时前",
            f"空闲时会摆的脸：{idle_expression(self.mood.valence)}",
            "最近影响它的事：" + ("；".join(self.mood.notes) if self.mood.notes else "（还没有）"),
        ]
        return "\n".join("  " + line for line in lines)


__all__ = [
    "ALONE_AFTER_H",
    "DULL_EXPRS",
    "FLOOR",
    "HOME",
    "LIVELY_EXPRS",
    "NEGATIVE_EXPRS",
    "NOTE_LIVELY",
    "NOTE_SLEEPY",
    "POSITIVE_EXPRS",
    "SPIRIT_DOWN",
    "SPIRIT_HOME",
    "SPIRIT_UP",
    "STATE_FILE",
    "Mood",
    "MoodTracker",
    "alone_drift",
    "clamp",
    "decayed",
    "idle_expression",
    "idle_expression_for",
    "label_of",
    "nudge_value",
    "prompt_line",
    "spectrum_label",
    "spirit_alone",
    "spirit_from",
    "spirit_hint",
    "spirit_nudge",
]
