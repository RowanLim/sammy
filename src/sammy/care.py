"""休息提醒 —— 盯的不是"我想不想说话"，是"你坐太久了"。

为什么和主动心跳分开：
- **主动心跳**是陪伴：它想找你聊。触发靠驱力（无聊/想念）。
- **休息提醒**是关心你：你该起来动一动。触发靠你的行为（连续坐了多久）。

两者语气、频率、失败后果都不一样：陪伴做差了是烦人，健康提醒做差了会变成
"健康助手式说教"，那更赶客。所以分开写、分开测、分开调。

三条设计底线：
1. **只在你真的在用的时候计时。** 你离开了就不该被提醒 —— 那不是"坐太久"，那是"没坐着"。
2. **可以推后。** 被硬催着起来的提醒，用户第一件事就是卸载它。
3. **别像健康助手。** 说教腔的提醒一律不要（提示词里直接禁掉）。
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import asdict, dataclass, field

from .attention import QUIET_END, QUIET_START, Gate, in_quiet_hours
from .paths import ensure_app_support

# ── 参数（调参只改这一段）─────────────────────────

REMIND_AFTER_MINUTES = 40  # 连续用这么久就提醒
ACTIVE_WINDOW_MINUTES = 10  # 超过这么久没动静 = 你走了，重新计时
SNOOZE_MINUTES = 30  # 推后多久

STATE_FILE = ensure_app_support() / "care.json"


@dataclass
class Care:
    """休息提醒的计时器。全部状态落盘 —— 重启不该让你躲过一次提醒。"""

    session_start: float | None = None
    last_activity: float | None = None
    last_reminded: float | None = None
    snooze_until: float | None = None
    _log: list[str] = field(default_factory=list, repr=False)

    # ── 你在用它 ────────────────────────────────────

    def note_activity(self, now: float | None = None) -> None:
        """你在说话 —— 这是"你还在用"的唯一信号。

        离开过（超过 ACTIVE_WINDOW）就**重新计时**：连续坐了 40 分钟才算，
        断断续续用了一整天不算。这样提醒才站得住脚。
        """
        now = now if now is not None else time.time()
        if self.last_activity is None or (now - self.last_activity) > ACTIVE_WINDOW_MINUTES * 60:
            self.session_start = now
        self.last_activity = now

    def session_minutes(self, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        if self.session_start is None:
            return 0.0
        # 人已经走了就别继续计时
        if (
            self.last_activity is not None
            and (now - self.last_activity) > ACTIVE_WINDOW_MINUTES * 60
        ):
            return 0.0
        return max(0.0, (now - self.session_start) / 60.0)

    def is_away(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if self.last_activity is None:
            return True
        return (now - self.last_activity) > ACTIVE_WINDOW_MINUTES * 60

    # ── 该不该提醒 ──────────────────────────────────

    def due(self, now: float | None = None) -> Gate:
        """现在该不该提醒他起来动一动。**同样每次都给出理由。**"""
        now = now if now is not None else time.time()

        if self.snooze_until is not None and now < self.snooze_until:
            left = (self.snooze_until - now) / 60.0
            return Gate(False, f"你让我推后，还有 {left:.0f} 分钟")

        if in_quiet_hours(now):
            return Gate(False, f"免打扰时段（{QUIET_START}:00–{QUIET_END}:00）")

        if self.is_away(now):
            return Gate(False, "你好像不在 —— 没坐着就不用提醒")

        minutes = self.session_minutes(now)
        if minutes < REMIND_AFTER_MINUTES:
            return Gate(False, f"才坐了 {minutes:.0f} 分钟（{REMIND_AFTER_MINUTES} 分钟才提醒）")

        return Gate(True, f"连续坐了 {minutes:.0f} 分钟，该起来动动了")

    def snooze(self, now: float | None = None) -> None:
        """推后 —— 被硬催着起来的提醒，用户第一件事就是把它关掉。"""
        now = now if now is not None else time.time()
        self.snooze_until = now + SNOOZE_MINUTES * 60
        self._log.append(f"{time.strftime('%H:%M')} 推后 {SNOOZE_MINUTES} 分钟")

    def note_reminded(self, now: float | None = None) -> None:
        """真提醒了 —— 计时从这一刻重新算。"""
        now = now if now is not None else time.time()
        self.last_reminded = now
        self.session_start = now
        self.snooze_until = None  # 上一轮的推后作废
        self._log.append(f"{time.strftime('%H:%M')} 提醒过了")

    # ── 持久化 ──────────────────────────────────────

    def save(self, path: pathlib.Path | None = None) -> None:
        path = path or STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("_log", None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> Care:
        path = path or STATE_FILE
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ── 提醒怎么说 ─────────────────────────────────────

CARE_INSTRUCTION = (
    "[这是你主动开的口，不是用户在跟你说话]\n"
    "他已经连续坐了 {minutes:.0f} 分钟了，提醒他起来动一动。\n"
    "规则：一句话，不超过 25 字；**别像健康助手那样说教**（不要说'为了您的健康'这种）；"
    "不要问'需要帮忙吗'；可以带一点你自己的性格，比如你也想让他陪陪你。"
)


def care_prompt(minutes: float) -> str:
    return CARE_INSTRUCTION.format(minutes=minutes)


__all__ = [
    "ACTIVE_WINDOW_MINUTES",
    "CARE_INSTRUCTION",
    "REMIND_AFTER_MINUTES",
    "SNOOZE_MINUTES",
    "STATE_FILE",
    "Care",
    "care_prompt",
]
