"""主动心跳 —— 决定 Sammy「要不要先开口」。

为什么单开一个模块、而不是塞进界面代码里：
**「它自己找你说话」是这类产品最动人的地方，也是最容易变成骚扰的地方。**
所以规则必须能被单独测试、单独调参、单独关掉 —— 混在窗口逻辑里就调不动了。

一条总的设计原则：**默认不说话。**
主动开口是要"争取到"的，不是默认发生的。
- 一个从不主动的 Sammy 只是有点无聊；
- 一个乱主动的 Sammy 会被关掉，那就什么都没了。

所以这里的每一条闸门都偏保守，而且**每次拒绝都要能说出理由** ——
理由不是为了给用户看，是为了调参时能一眼看出"到底卡在哪一条"。
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import asdict, dataclass, field

from .paths import ensure_app_support

# ── 闸门参数（全在这里，调参只改这一段）─────────────

# 免打扰时段：[23 点, 次日 8 点)。跨午夜，所以要单独处理。
QUIET_START = 23
QUIET_END = 8

MIN_GAP_MINUTES = 45  # 两次主动之间的最小间隔
MAX_PER_DAY = 3  # 每天最多主动几次
STARTUP_GRACE_MINUTES = 5  # 刚启动别急着开口
MIN_WANT = 0.55  # want_to_talk 的门槛（见 drives.py）

STATE_FILE = ensure_app_support() / "attention.json"


def in_quiet_hours(now: float) -> bool:
    """现在是不是免打扰时段（23:00–08:00，跨午夜）。

    提到模块级是为了让**休息提醒也能用同一份定义** ——
    两边各写一遍「什么算深夜」，早晚会不一致，而且不一致的时候没人会发现。
    """
    hour = int(time.strftime("%H", time.localtime(now)))
    if QUIET_START <= QUIET_END:
        return QUIET_START <= hour < QUIET_END
    return hour >= QUIET_START or hour < QUIET_END


@dataclass(frozen=True)
class Gate:
    """一次判断的结果。`reason` 是给调参用的，不是给用户看的。"""

    ok: bool
    reason: str

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class Attention:
    last_spoke: float | None = None
    spoken_today: int = 0
    day: str = ""
    _log: list[str] = field(default_factory=list, repr=False)

    # ── 判断 ────────────────────────────────────────

    def decide(
        self,
        *,
        want_to_talk: float,
        silent_minutes: float,
        now: float | None = None,
        started_at: float | None = None,
    ) -> Gate:
        """要不要现在先开口。**顺序有讲究**：从"绝对不能"到"可以"。

        顺序本身就是优先级 —— 免打扰最硬，其次是不打扰刚聊过的人，
        再其次是今日配额，最后才轮到"它自己想不想说"。
        """
        now = now if now is not None else time.time()
        self._roll_over(now)

        if self._in_quiet_hours(now):
            return Gate(False, f"免打扰时段（{QUIET_START}:00–{QUIET_END}:00）")
        if started_at is not None:
            since_start = (now - started_at) / 60.0
            if since_start < STARTUP_GRACE_MINUTES:
                left = STARTUP_GRACE_MINUTES - since_start
                return Gate(False, f"刚启动，再等 {left:.0f} 分钟")

        if silent_minutes < MIN_GAP_MINUTES:
            left = MIN_GAP_MINUTES - silent_minutes
            return Gate(False, f"刚聊过，再等 {left:.0f} 分钟")

        # ⚠️ 这一条是设计漏洞补上来的：原来只算"用户多久没理我"，
        # **没算"我多久前刚开口"**。于是它说完一句、用户没理它，下一分钟又能说 ——
        # 用户一句话没说，它连说三句，这就该被卸载了。两件事必须分开算。
        # ⚠️ 时钟倒退过的话（改系统时间 / 跨时区 / 状态文件来自别处），
        # last_spoke 可能落在"未来"。不处理的话这里会算出负数，
        # 用一个荒唐的理由（"还剩 -75 分钟"）把它**永久锁死**。
        # 坏数据要能自愈，不能把功能锁死。
        if self.last_spoke is not None and self.last_spoke > now:
            self.last_spoke = None

        if self.last_spoke is not None:
            since_spoke = (now - self.last_spoke) / 60.0
            if since_spoke < MIN_GAP_MINUTES:
                left = MIN_GAP_MINUTES - since_spoke
                return Gate(False, f"我才刚开口过，再等 {left:.0f} 分钟")

        if self.spoken_today >= MAX_PER_DAY:
            return Gate(False, f"今天已经主动 {self.spoken_today} 次了，够了")

        if want_to_talk < MIN_WANT:
            return Gate(False, f"它自己还不想说（想开口 {want_to_talk:.2f} < {MIN_WANT}）")

        return Gate(True, f"可以开口：想开口 {want_to_talk:.2f}，已安静 {silent_minutes:.0f} 分钟")

    def note_spoke(self, now: float | None = None) -> None:
        """真开口了才记账 —— 判断通过但生成失败，不该消耗今天的机会。"""
        now = now if now is not None else time.time()
        self._roll_over(now)
        self.last_spoke = now
        self.spoken_today += 1
        self._log.append(f"{time.strftime('%H:%M:%S')} 主动开口（今天第 {self.spoken_today} 次）")

    # ── 内部 ────────────────────────────────────────

    @staticmethod
    def _in_quiet_hours(now: float) -> bool:
        return in_quiet_hours(now)

    def _today(self, now: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now))

    def _roll_over(self, now: float) -> None:
        """跨天就把当日配额清零。

        为什么要落盘：**如果重启就把配额忘了，那"每天最多 3 次"形同虚设** ——
        关掉再打开就能重置的东西，不叫限制。
        """
        today = self._today(now)
        if self.day != today:
            self.day = today
            self.spoken_today = 0

    # ── 持久化 ──────────────────────────────────────

    def save(self, path: pathlib.Path | None = None) -> None:
        path = path or STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("_log", None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> Attention:
        path = path or STATE_FILE
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ── 先开口说什么 ───────────────────────────────────

# 明确写死几条"由头"，而不是让模型自由发挥 ——
# 自由发挥的主动消息，十条里有八条会变成"需要我帮你做点什么吗"这种客服腔。
TOPIC_HINTS = {
    "bored": "你已经一个人待了一会儿了，说一句俏皮的、想找他聊的话。不要问需不需要帮忙。",
    "sleepy": "你有点困了，说一句迷糊可爱的话（可以说说自己快睡着了）。",
    "missing": "你有段时间没见到他了，说一句自然一点的想念，别肉麻。",
    "care": "关心一句他现在的状态（比如是不是坐太久了），一句话就够。",
}


def open_prompt(want_to_talk: float, closeness: float, boredom: float) -> str:
    """挑一个由头，生成给模型的指令。**由头是有限的几种，不是自由发挥。**"""
    if closeness < 0.3:
        key = "missing"
    elif boredom > 0.6:
        key = "bored"
    else:
        key = "care"
    return (
        f"[这是你主动开的口，不是用户在跟你说话]\n{TOPIC_HINTS[key]}\n"
        "规则：一句话，不超过 20 字；不要问'需要帮忙吗'；不要用'有什么可以帮您'这种腔调。"
    )


__all__ = [
    "MAX_PER_DAY",
    "MIN_GAP_MINUTES",
    "MIN_WANT",
    "QUIET_END",
    "QUIET_START",
    "STATE_FILE",
    "TOPIC_HINTS",
    "Attention",
    "Gate",
    "open_prompt",
]
