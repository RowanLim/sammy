"""桌上的一天（复刻）—— 在**那个目录挪走的同一小时**里替 Sammy 把日子过一遍。

为什么要有它（Rowan 2026-10-14 定的「1 小时长跑压测」）：
Sammy 的很多东西是**按小时**长出来的 —— 精力掉、无聊涨、亲近淡、心情回归、
「今天已经说过几次」的冷却。一小时的真机跑暴露不了这些：一小时精力只掉
0.10，什么状态都到不了。所以这一天不靠等，靠**自己把时间过掉**。

三块拼起来：
1. 活动脚本（「一天里你什么时候在」）—— 反复「搭理它 / 冷落它 / 隔夜」，
   48 小时过成几十秒；
2. 替身（`Replica`）—— 它有自己的数据目录（`data/replica/`），
   按喂进去的时间推进：精力、心情、亲近、记忆、日记都真的在走；
3. 账本（`DayReport`）—— 这一天里睡过几次、最低精力、心情走成什么样、崩没崩。

两条硬规矩（写在这里，免得将来为了省事绕过去）：

1. **不碰真实数据，也不挪它。** 替身有自己的目录，真实 `data/` 全程一字不改 ——
   挪真实数据是备份该干的事，不是压测该干的事（挪多了等于多一份丢数据的理由）。
2. **不回放他的流水。** 这一天是**合成的**：RepLay（`replay.py`）读他的真实聊天记录，
   复刻只按脚本推时间 —— 两件事分开，好坏各算各的账。

口径：时间台和 `replay.py` 一样从**真实时钟**起步（喂「真实时钟 + 这一天过到哪儿」），
否则心情的基线回归会被一个几十年的差值一次性拉到底。不碰系统时钟、不设机器级东西。
"""

from __future__ import annotations

import pathlib
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .paths import data_dir

# 一天里最长的一段「没人理」按多久算（8 小时 = 上班/睡觉的量级；
# 再长也只是让精力更低一点，而精力到 0 就自己睡过去，曲线会平掉）
MAX_GAP_S = 8 * 3600.0
DAY_S = 24 * 3600.0

# 一段式脚本默认的三种时间段（秒）：「你在」/「你走了」/「过夜」
DEFAULT_AWAKE_WINDOW_S = 2.5 * 3600.0
DEFAULT_AWAY_WINDOW_S = 4.0 * 3600.0
DEFAULT_NIGHT_S = 8.0 * 3600.0

GREETINGS = (
    "早",
    "回来了",
    "你在干嘛呀",
    "刚刚那个我想了想，还是算了",
    "我有点困",
    "今天过得怎么样",
    "帮我看一眼这个报错",
)


@dataclass
class Beat:
    """一天里的一拍：`gap_s` 秒之后，发生了什么。"""

    gap_s: float
    kind: str  # greet | poke | idle | night
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"gap_s": round(self.gap_s, 1), "kind": self.kind, "text": self.text}


@dataclass
class ActivityScript:
    """一天的形状：什么时候你在、什么时候你走、晚上睡多久。

    三种拍子：
    - `greet` 你主动说了一句话（打招呼，比戳一下更有分量）；
    - `poke`  你顺手戳了一下（不说话，逗它玩）；
    - `idle` / `night` 没人理，时间自己往前走。
    """

    beats: list[Beat] = field(default_factory=list)
    seed: int = 0

    @property
    def hours(self) -> float:
        return sum(b.gap_s for b in self.beats) / 3600.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "beats": len(self.beats),
            "hours": round(self.hours, 2),
            "greets": sum(1 for b in self.beats if b.kind == "greet"),
            "pokes": sum(1 for b in self.beats if b.kind == "poke"),
            "seed": self.seed,
        }

    def lines(self) -> list[str]:
        d = self.as_dict()
        return [
            f"这一天 {d['hours']:.1f} 小时 · {d['beats']} 拍"
            f" · 你说话 {d['greets']} 次 / 戳它 {d['pokes']} 次"
        ]


def _rng(seed: int | None) -> random.Random:
    """自己的随机流：种子一定，这一天就一模一样（可复现才敢报数字）。"""
    return random.Random(seed if seed is not None else time.time_ns())


def day_script(
    days: int = 1,
    *,
    seed: int | None = None,
    pause: bool = False,
    night: bool = False,
) -> ActivityScript:
    """造一天：白天你在两三个小时（说话 + 戳它），然后你走开，再回来。

    这就是桌面上真实的样子 —— 它一个人待着的时候，那些**按小时**长的东西
    才有机会长出来。
    """
    rng = _rng(seed)
    beats: list[Beat] = []
    for _ in range(max(1, int(days))):
        # 你回来
        beats.append(Beat(gap_s=0.0, kind="greet", text=rng.choice(GREETINGS)))
        if not pause:
            beats.append(Beat(gap_s=rng.uniform(20.0, 60.0), kind="poke"))
        beats.append(Beat(gap_s=DEFAULT_AWAKE_WINDOW_S, kind="idle"))
        # 你走开了
        beats.append(Beat(gap_s=DEFAULT_AWAY_WINDOW_S, kind="idle"))
        if night:
            beats.append(Beat(gap_s=DEFAULT_NIGHT_S, kind="night"))
    return ActivityScript(beats=beats, seed=int(seed if seed is not None else 0))


def from_beats(rows: list[dict], *, seed: int = 0) -> ActivityScript:
    """从「(隔多久, 发生了什么)」的列表造脚本 —— 报告里回看这一天的形状用。"""
    out: list[Beat] = []
    for row in rows:
        gap = float(row.get("gap_s") or 0.0)
        out.append(
            Beat(
                gap_s=gap if gap <= MAX_GAP_S else MAX_GAP_S,
                kind=str(row.get("kind") or "idle"),
                text=str(row.get("text") or ""),
            )
        )
    return ActivityScript(beats=out, seed=seed)


def _asleep_minutes(d: Any) -> float:
    """这一刻它在时间軸上睡了多久 —— 报告里「总共睡了几小时」靠它累加。"""
    return 0.0


@dataclass
class DayReport:
    """这一天过完的账本（压测报告要用的一节）。"""

    days: int = 0
    hours: float = 0.0
    beats: int = 0
    greets: int = 0
    pokes: int = 0
    energy_min: float = 1.0
    energy_max: float = 0.0
    valence_min: float = 0.0
    valence_max: float = 0.0
    slept_once: bool = False
    asleep_at_end: bool = False
    sleep_bouts: int = 0
    sleep_hours: float = 0.0
    crashes: int = 0
    last_error: str = ""
    states: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "hours": round(self.hours, 3),
            "beats": self.beats,
            "greets": self.greets,
            "pokes": self.pokes,
            "energy_min": round(self.energy_min, 3),
            "energy_max": round(self.energy_max, 3),
            "valence_min": round(self.valence_min, 3),
            "valence_max": round(self.valence_max, 3),
            "slept_once": self.slept_once,
            "asleep_at_end": self.asleep_at_end,
            "sleep_bouts": self.sleep_bouts,
            "sleep_hours": round(self.sleep_hours, 2),
            "crashes": self.crashes,
            "last_error": self.last_error,
            "states": self.states,
        }

    def human_lines(self) -> list[str]:
        d = self.as_dict()
        return [
            f"桌上的一天 {d['days']} 天 / {d['hours']:.1f} 小时 · {d['beats']} 拍"
            f" · 你说话 {d['greets']} 次 / 戳它 {d['pokes']} 次",
            f"精力最低 {d['energy_min']:.2f} · 心情 {d['valence_min']:+.2f} ~ {d['valence_max']:+.2f}"
            f" · 这一天睡着过：{'是' if d['slept_once'] else '否'}"
            f"（{d['sleep_bouts']} 次 / {d['sleep_hours']:.2f} 小时）",
        ]


def sim_data_dir(real: pathlib.Path | None = None) -> pathlib.Path:
    """替身的数据目录 —— 就在真实数据目录的**里面**（`data/replica/`）。

    为什么不挪走真实数据：挪是「备份」这个动作该干的事，压测顺手做一遍
    只会多一份丢数据的理由。替身有自己的目录就够隔离了：它的
    `drives.json` / `mood.json` / `memory.json` 全在这里，真实的一字不改。
    """
    return (real or data_dir()) / "replica"


class Replica:
    """替身：按喂进去的时间替它过日子（读真实起点，写自己的目录）。"""

    def __init__(
        self,
        *,
        real_dir: pathlib.Path | None = None,
        sim_dir: pathlib.Path | None = None,
        now: float | None = None,
    ) -> None:
        from .drives import Drives
        from .memory import Memory
        from .mood import MoodTracker

        self.real_dir = pathlib.Path(real_dir) if real_dir else data_dir()
        self.sim = pathlib.Path(sim_dir) if sim_dir else sim_data_dir(self.real_dir)
        self.sim.mkdir(parents=True, exist_ok=True)
        self._t0 = float(now if now is not None else time.time())
        self.now = self._t0
        self._drives_cls = Drives
        self._mood_cls = MoodTracker

        self.memory = Memory(self.sim / "memory.db")
        self.drives = self._load_drives()
        self.mood = self._load_mood()  # 起点与驱力同一刻

        self.script = ActivityScript()
        self.report = DayReport()
        self._asleep_since: float | None = self.now if self.drives.asleep else None

    # ── 起点的三条来源（口径抄自 replay.py，理由见文件头）──

    def _load_drives(self):
        """起点从真实状态里**读一眼**（这时候 SAMMY_HOME 还指着真实目录），
        然后把时间台挪到「现在」——之后它写的每一条都落在替身自己的目录里。"""
        d = self._drives_cls.load()
        self._seed_state = d.snapshot()
        d.last_update = self.now
        return d

    def _load_mood(self):
        m = self._mood_cls()
        # 心情的起点也对齐这一刻：它的基线回归按「距上次更新的小时数」算，
        # 拿一台从别处起跳的时间台去比，第一 tick 就会被一次性拉到底（踩过）
        m.mood.updated = self.now
        return m

    # ── 过日子 ──────────────────────────────────────

    def snapshot(self, kind: str = "", text: str = "") -> None:
        """记一帧状态（时间軸上的一格）—— 报告里的曲线就是这些帧。"""
        d = self.drives
        self.report.states.append(
            {
                "t": round((self.now - self._t0) / 3600.0, 3),
                "kind": kind,
                "text": text,
                "energy": round(d.energy, 3),
                "boredom": round(d.boredom, 3),
                "closeness": round(d.closeness, 3),
                "asleep": bool(d.asleep),
                "valence": round(self.mood.mood.valence, 3),
                "want_to_talk": round(d.want_to_talk, 3),
            }
        )
        r = self.report
        r.energy_min = min(r.energy_min, d.energy)
        r.energy_max = max(r.energy_max, d.energy)
        r.valence_min = min(r.valence_min, self.mood.mood.valence)
        r.valence_max = max(r.valence_max, self.mood.mood.valence)

    def _advance(self, gap_s: float) -> None:
        """把这段消逝的时间喂给驱力与心情，再落盘 —— 一天的全部意义就在这几行。"""
        gap = max(0.0, float(gap_s))
        if gap <= 0.0:
            return
        before_asleep = self.drives.asleep
        was = self.now
        self.now = was + gap
        self.drives.tick(now=self.now)
        self.mood.tick(now=self.now, hours_alone=gap / 3600.0)
        if before_asleep:
            self.report.sleep_hours += gap / 3600.0
        if not before_asleep and self.drives.asleep:
            self.report.slept_once = True
            self.report.sleep_bouts += 1
            self._asleep_since = self.now

    def live(self, beat: Beat) -> None:
        """一拍：先把时间推过去，再按拍子的种类办事。"""
        self._advance(beat.gap_s)
        if beat.kind == "greet":
            self.drives.on_interaction(greeted=True)
            self.mood.poke()
            self.memory.add("你说了句「" + beat.text + "」", kind="event")
        elif beat.kind == "poke":
            self.drives.on_interaction(greeted=False)
            self.mood.poke()
        self.snapshot(beat.kind, beat.text)

    def run(
        self,
        *,
        days: int = 1,
        seed: int | None = None,
        script: ActivityScript | None = None,
        brain: Any = None,
        pause: bool = False,
    ) -> DayReport:
        """把这一天过完。`brain=None` 时不说话（离线），只推时间与状态。"""
        script = script or day_script(days, seed=seed, pause=pause)
        self.script = script
        rep = self.report
        rep.days = max(1, int(days))
        self.snapshot("start")
        for beat in script.beats:
            rep.beats += 1
            if beat.kind == "greet":
                rep.greets += 1
            elif beat.kind == "poke":
                rep.pokes += 1
            try:
                self.live(beat)
                if brain is not None and beat.kind == "greet" and beat.text:
                    self.memory.add("它在这一天里被搭理过", kind="event")
            except Exception as e:  # 一拍出事记一笔，接着过 —— 和一晚上的压测一个规矩
                rep.crashes += 1
                rep.last_error = f"{type(e).__name__}: {e}"
        rep.hours = (self.now - self._t0) / 3600.0
        rep.asleep_at_end = bool(self.drives.asleep)
        self.save()
        return rep

    def save(self) -> None:
        self.drives.save(self.sim / "drives.json")
        self.mood.path = self.sim / "mood.json"
        self.mood.save()

    def real_untouched(self, before: dict) -> list[str]:
        """真实数据目录改过的文件（空列表 = 一字未动）—— 判据靠它。"""
        changed: list[str] = []
        for name, blob in before.items():
            p = self.real_dir / name
            if not p.exists() or p.read_bytes() != blob:
                changed.append(name)
        return changed
