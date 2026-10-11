"""驱力系统 —— Sammy 的"内在状态"。

为什么需要它（依据 docs/research/对标-NOMI与贾维斯.md）：
原来它的行为是**硬编码的定时器**：无交互 120 秒变犯困、300 秒变睡着。
那不是"性格"，那是 `if` 语句。而对标 NOMI，陪感感的来源恰恰是
**"它有自己的状态，状态会随时间漂移，而且用户能看见"**。

三条驱力（都能被交互和睡眠影响，都在 0..1 之间）：
- **energy 精力**：清醒时下降，睡着时回升。低了就犯困、再低就睡着。
- **boredom 无聊**：没人理它就涨，被搭理就掉。高了会想找你、会"偷看"。
- **closeness 亲近**：被搭理会涨，久不理缓慢衰减。这是"关系"的量化。

设计上有一条硬约束：**它只影响"表情"和"想不想说话"，不直接替用户做任何事。**
状态可以调皮，但不能越权。
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import asdict, dataclass, field

from .expressions import EMOTIONS
from .paths import data_dir

# 数据全部在 <项目>/data/ 里 —— Rowan 的隔离要求（见 paths.py）。
# 不在 ~/Library 里建东西：删掉项目文件夹 = 这个项目在你机器上彻底消失。
APP_DIR = data_dir()
STATE_FILE = APP_DIR / "drives.json"

# 漂移速率（每小时）。数字本身不需要精确 —— 需要的是**方向对、量级合理**，
# 而且全都能被测试钉住。调参只该改这里。
ENERGY_PER_HOUR_AWAKE = 0.10
ENERGY_PER_HOUR_ASLEEP = 0.55
BOREDOM_PER_HOUR = 0.22
# 睡着时不但不长无聊，反而**把它解开**：睡醒该是精神好、想看点什么，
# 而不是刚睡醒就"憋坏了"（这一条是看演示数据时发现的，不是推出来的）。
BOREDOM_RELIEF_PER_HOUR_ASLEEP = 0.11
CLOSENESS_DECAY_PER_HOUR = 0.05

# 交互带来的即时变化
ON_INTERACTION = {"energy": +0.02, "boredom": -0.30, "closeness": +0.06}
# 打招呼必须**每一项都比随手戳一下更有效** —— 否则"被搭理"和"被打扰"就没区别了
ON_GREETING = {"energy": +0.06, "boredom": -0.45, "closeness": +0.14}

SLEEPY_BELOW = 0.30
ASLEEP_BELOW = 0.12
# 被叫醒的门槛。用独立常量而不是"ASLEEP_BELOW + 0.15"这种算式：
# 算式会刚好卡在边界上（0.27 > 0.27 不成立），导致精神还行却叫不醒。
WAKE_ENERGY_ABOVE = 0.20

# ── 作息（2026-10-12 加：「它该有自己的日夜」）────────────
# 夜里（23:00-07:00）精力掉得更快 —— 一台老机器到了后半夜就该犯困。
# 为什么是"掉得更快"而不是"到点直接睡着"：让它**自己走到**睡着。
# 犯困→睡着这段本来就是设计里有的，抄近路就没有"越来越困"的过程了。
# 另外：这**不是**高峰/空闲那条规矩（那是给我花钱定的），是它的作息。
NIGHT_FROM_H, NIGHT_TO_H = 23, 7
NIGHT_DRAIN_FACTOR = 1.6


def night_factor(hour: int) -> float:
    """这一刻的「夜度」：夜里 1.6 倍、白天 1.0。只放大消耗，不动物理上限。"""
    return NIGHT_DRAIN_FACTOR if (hour >= NIGHT_FROM_H or hour < NIGHT_TO_H) else 1.0


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def status_text(d: Drives) -> str:
    """把状态翻译成界面上的一行字。顺序必须和 `expression()` 一致 ——
    否则会出现"脸是睡着的、话却说困得不行"这种自相矛盾（踩过）。"""
    if d.asleep or d.exhausted:
        return "睡着了"
    if d.sleepy:
        return "有点困了"
    if d.boredom > 0.65:
        return "有点无聊"
    if d.closeness < 0.3:
        return "想你了"
    return "在线"


@dataclass
class Drives:
    """三条驱力 + 上次结算时间。默认从"睡饱了但有点想你"开始。"""

    energy: float = 0.85
    boredom: float = 0.15
    closeness: float = 0.55
    last_update: float = field(default_factory=time.time)
    asleep: bool = False
    # 结算历史，方便调试（不落盘，只留最近几次）
    _log: list[str] = field(default_factory=list, repr=False)

    # ── 时间推进 ────────────────────────────────────

    def tick(self, now: float | None = None) -> Drives:
        """按经过的时间结算一次。可以放心地频繁调用（时间不长就不动）。"""
        now = now if now is not None else time.time()
        hours = max(0.0, (now - self.last_update) / 3600.0)
        if hours <= 0:
            return self

        if self.asleep:
            self.energy = _clamp(self.energy + ENERGY_PER_HOUR_ASLEEP * hours)
            self.boredom = _clamp(self.boredom - BOREDOM_RELIEF_PER_HOUR_ASLEEP * hours)
        else:
            # 作息：取这段时间**中点**的时刻判夜/昼（一个小时的块里两者等价，
            # 机器合上盖放了两天这种长间隔下，中点是个不会太离谱的近似）
            hour = time.localtime((self.last_update + now) / 2.0).tm_hour
            self.energy = _clamp(self.energy - ENERGY_PER_HOUR_AWAKE * night_factor(hour) * hours)
            self.boredom = _clamp(self.boredom + BOREDOM_PER_HOUR * hours)
            self.closeness = _clamp(self.closeness - CLOSENESS_DECAY_PER_HOUR * hours)

        # 精力见底就自己睡过去 —— 不是站在那儿"困得不行"
        if not self.asleep and self.energy < ASLEEP_BELOW:
            self.asleep = True
            self._log.append("累得睡着了")
        # 睡醒：睡够了就自己醒过来（它不是在等用户叫它）
        elif self.asleep and self.energy >= 0.9:
            self.asleep = False
            self._log.append("睡饱了，自己醒了")

        self.last_update = now
        return self

    def fast_forward(self, *, awake: float = 0.0, asleep: float = 0.0) -> Drives:
        """测试与调试用：跳过时间，不用真等。

        `awake=6` 表示"清醒地过 6 小时"，`asleep=6` 表示"睡 6 小时"。
        不要还原 asleep 标志 —— 否则"睡饱了自己醒过来"这条路径永远测不到。
        """
        if awake and asleep:
            raise ValueError("一次只能推进一种状态")
        if awake:
            self.asleep = False
            self.tick(now=self.last_update + awake * 3600)
        elif asleep:
            self.asleep = True
            self.tick(now=self.last_update + asleep * 3600)
        return self

    # ── 交互 ────────────────────────────────────────

    def on_interaction(self, greeted: bool = False) -> Drives:
        """被搭理了。greeted=用户主动打招呼（比单纯戳一下更有分量）。"""
        self.tick()
        delta = ON_GREETING if greeted else ON_INTERACTION
        self.energy = _clamp(self.energy + delta["energy"])
        self.boredom = _clamp(self.boredom + delta["boredom"])
        self.closeness = _clamp(self.closeness + delta["closeness"])
        if self.asleep and self.energy > WAKE_ENERGY_ABOVE:
            self.asleep = False
            self._log.append("被叫醒了")
        return self

    def go_to_sleep(self) -> Drives:
        self.tick()
        self.asleep = True
        return self

    # ── 派生状态 ────────────────────────────────────

    @property
    def sleepy(self) -> bool:
        return self.energy < SLEEPY_BELOW

    @property
    def exhausted(self) -> bool:
        return self.energy < ASLEEP_BELOW

    @property
    def want_to_talk(self) -> float:
        """0..1：它此刻"想找你说话"的程度。

        给主动心跳用的。组成上：越无聊越想、精力越足越说得动、
        太亲近了反而不会一直叨扰（关系稳了就不焦虑）。
        """
        drive = self.boredom * (0.4 + 0.6 * self.energy)
        missing = max(0.0, 0.35 - self.closeness) * 0.8  # 疏远了会想你
        return _clamp(drive + missing)

    def expression(self) -> int:
        """此刻该摆哪张脸。用**情绪名**查表，不写死编号 —— 编号重排时不会悄悄错位。"""
        if self.asleep or self.exhausted:
            mood = "sleep"
        elif self.sleepy:
            mood = "sleepy"
        elif self.closeness < 0.3:
            mood = "expect"  # 疏远了 = 想你了（不必再叠加"无聊" —— 会和状态文字对不上）
        elif self.boredom > 0.65:
            mood = "bored"
        elif self.boredom > 0.4:
            mood = "curious"
        elif self.energy > 0.7 and self.closeness > 0.6:
            mood = "content"
        else:
            mood = "normal"
        return EMOTIONS[mood]

    def snapshot(self) -> dict:
        d = asdict(self)
        d.pop("_log", None)
        d.update(
            sleepy=self.sleepy,
            exhausted=self.exhausted,
            asleep=self.asleep,
            want_to_talk=round(self.want_to_talk, 3),
            face=self.expression(),
        )
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}

    # ── 持久化 ──────────────────────────────────────

    def save(self, path: pathlib.Path | None = None) -> None:
        path = path or STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("_log", None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> Drives:
        """读回上次的状态 —— **重启不该让它"满血复活"**，否则人设是断的。"""
        path = path or STATE_FILE
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
