"""历史回放 —— 把「过了几天」压成「几十秒」的同一套代码路径。

为什么需要它（Rowan 2026-10-14 定的「1 小时长跑压测」之前必须有的东西）：
Sammy 的很多东西是**按小时**长出来的 ——
驱力随时间漂移（`drives.tick`）、心情回归基线（`mood` 的半衰期 6 小时）、
作息（夜里精力掉得快 1.6 倍）、主动开口的「今天已经说过几次」、旧事的冷却……
一小时的真机压测能暴露内存与句柄泄漏，但**结构上**暴露不了这些：
一小时的驱力变化只有 0.10 的量级，什么状态都到不了。

回放解决的就是这个：事件之间的**墙上时间**（比如你在周五晚上说了句话、
周日凌晨又开机）原样喂给 `Drives.tick(now=...)` / `mood.tick(now=...)`，
于是「过了 30 小时」这件事真的发生了；而回放**自己**不等这 30 小时。
一条来自真实流水的序列因此能在几十秒里跑完，走的是和平常一模一样的代码路径。

两条硬规矩（写在这里，免得将来为了方便绕过去）：

1. **测试口子不许进生产路径。** 这里的时间是「喂进去的」，不是「拿系统时钟改的」
   —— 全程不碰系统时间、不设置任何机器级东西。回放只认 `now` 参数，
   生产路径不传它就是走真实时钟。
2. **不写真实状态。** 回放全程只读真实流水，状态落在一个临时目录里
   （`SAMMY_HOME` 指到那个目录）—— 它不是你的一天，不该改你的记忆与心情。

口径上有一处必须说清楚：`Drives.tick` 判昼夜用的是这段时间的**中点**
（见 drives.py 的注释）。所以回放里跨越夜里的长间隔，按中点近似 ——
和真机跑一夜的行为是同一套近似，不是回放特有的误差。
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from .paths import data_dir

LOG_FILE = data_dir() / "chat.jsonl"
DEFAULT_DAY_GAP_S = 8 * 3600.0


@dataclass
class Step:
    """一步：`gap_s` 秒之后他（或它自己）说了这句话。"""

    gap_s: float
    role: str
    text: str
    kind: str = ""

    @staticmethod
    def from_row(row: dict, gap_s: float) -> Step:
        return Step(
            gap_s=float(gap_s),
            role=str(row.get("role") or "user"),
            text=str(row.get("text") or ""),
            kind=str(row.get("kind") or ""),
        )


def steps_from_rows(rows: list[dict], *, day_gap_s: float = DEFAULT_DAY_GAP_S) -> list[Step]:
    """真实流水 → 回放步骤。**长间隔压缩，短间隔原样。**

    这是唯一一处「压过的时间轴」，规则只有一条：
    相邻两条之间差得比 `day_gap_s` 还远（比如隔了一天再开机），
    就按 `day_gap_s` 算 —— 保留「过了很久」这件事，但不为它空等一整天。
    两分钟内的一来一往原样保留（那本来就是一次对话的真实节奏）。
    """
    out: list[Step] = []
    prev: float | None = None
    for row in rows:
        ts = float(row.get("t") or 0.0)
        if prev is None:
            out.append(Step.from_row(row, 0.0))
        else:
            gap = max(0.0, ts - prev)
            out.append(Step.from_row(row, min(gap, day_gap_s) if gap > day_gap_s else gap))
        prev = ts
    return out


def steps_from_log(path: pathlib.Path | None = None) -> list[Step]:
    """读真实对话流水（`data/chat.jsonl`），坏行跳过（和 chatlog 一个口径）。"""
    p = pathlib.Path(path) if path is not None else LOG_FILE
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("text") and item.get("t") is not None:
            rows.append(item)
    return steps_from_rows(rows)


def summary_lines(steps: list[Step], hours: float) -> list[str]:
    """回放前先打一份「将要发生什么」—— 压测报告开头就该有这一段。"""
    real = sum(s.gap_s for s in steps)
    said = sum(1 for s in steps if s.role == "user")
    return [
        f"回放 {len(steps)} 步：时间轴 {real / 3600.0:.1f} 小时 → 压缩后 {hours:.3f} 小时",
        f"其中你说的话 {said} 句",
    ]


@dataclass
class ReplayReport:
    """回放跑完的账本（压测报告要用的一节）。"""

    steps: int = 0
    hours: float = 0.0
    turns: int = 0
    crashes: int = 0
    empties: int = 0
    latencies: list[float] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""

    def snapshot(self, drives, mood) -> None:
        """记一条状态（时间轴上的一帧）。"""
        self.states.append(
            {
                "t": round(self.hours, 2),
                "energy": round(drives.energy, 3),
                "boredom": round(drives.boredom, 3),
                "closeness": round(drives.closeness, 3),
                "asleep": bool(drives.asleep),
                "valence": round(mood.mood.valence, 3),
                "want_to_talk": round(drives.want_to_talk, 3),
            }
        )

    def as_dict(self) -> dict[str, Any]:
        from statistics import median

        return {
            "steps": self.steps,
            "hours": round(self.hours, 3),
            "turns": self.turns,
            "crashes": self.crashes,
            "empties": self.empties,
            "latency_p50": round(median(self.latencies), 3) if self.latencies else 0.0,
            "latency_max": round(max(self.latencies), 3) if self.latencies else 0.0,
            "asleep_at_end": bool(self.states and self.states[-1]["asleep"]),
            "slept_once": any(s["asleep"] for s in self.states),
            "valence_min": min((s["valence"] for s in self.states), default=0.0),
            "valence_max": max((s["valence"] for s in self.states), default=0.0),
            "energy_min": min((s["energy"] for s in self.states), default=0.0),
            "last_error": self.last_error,
            "states": self.states,
        }

    def human_lines(self) -> list[str]:
        d = self.as_dict()
        lines = [
            f"回放 {d['steps']} 步 / {d['hours']:.2f} 小时时间轴 · 真说话 {d['turns']} 次"
            f" · 崩 {d['crashes']} · 空回复 {d['empties']}"
            f" · 延迟 p50 {d['latency_p50']}s / max {d['latency_max']}s",
            f"精力最低 {d['energy_min']:.2f} · 心情 {d['valence_min']:+.2f} ~ {d['valence_max']:+.2f}"
            f" · 时间轴上睡着过：{'是' if d['slept_once'] else '否'}"
            f" · 结束时{'睡着' if d['asleep_at_end'] else '醒着'}",
        ]
        if d["last_error"]:
            lines.append(f"最后一次报错：{d['last_error']}")
        return lines


def replay(
    steps: list[Step],
    *,
    brain: Any = None,
    workdir: pathlib.Path | None = None,
    sleep_s: float = 0.0,
    recorder: Any = None,
) -> ReplayReport:
    """真的跑一遍：时间轴上每步先把时间喂给驱力与心情，再处理这句话。

    `brain` 给 None 时走**离线**路径（不联网）：只推时间、不产生回复 ——
    这样「长跑里状态怎么走」这件事本身可以被测试钉住，不需要凭证。
    `sleep_s` 是每一步让出的真实秒数（0 = 一步不停，回放就该是快的）。
    """
    from .drives import Drives
    from .mood import MoodTracker

    ours = workdir is not None
    tmp: tempfile.TemporaryDirectory | None = None
    if ours:
        tmp = tempfile.TemporaryDirectory(prefix="sammy-replay-")
        workdir = pathlib.Path(tmp.name)
        os.environ["SAMMY_HOME"] = str(workdir)

    rep = ReplayReport()
    try:
        drives = Drives.load()
        mood = MoodTracker()
        # 时间台从**真实时钟**起步，而不是从 0 起步 —— 理由是心情那边：
        # 它的回归按「距上次更新的小时数」算，拿一台从 0 起的时间台去比，
        # 第一次 tick 就会被一个几十年的差值一次性拉到底。起点对上真实时钟
        # 之后，回放里过一小时就是真的过一小时。
        # 所以 `now` 喂的是「真实时钟 + 回放时间」，不是回放时间本身。
        base = time.time()
        last = base
        drives.last_update = base
        mood.mood.updated = base
        rep.snapshot(drives, mood)
        for step in steps:
            rep.steps += 1
            last += float(step.gap_s)
            rep.hours = (last - base) / 3600.0
            # ① 先把这段消逝的时间喂给它 —— 回放的全部意义就在这两行
            drives.tick(now=last)
            mood.tick(now=last, hours_alone=max(0.0, step.gap_s / 3600.0))
            if step.role != "user":
                if recorder is not None:
                    recorder(step, drives, mood)
                continue  # 没人说话的一步：只推时间（上面已经推过）
            # 被搭理了 —— 真跑时这发生在窗口的 send() 里；回放走同一条
            # 记账路径（greeted 用「你主动说了一句」判，和窗口一致）。
            drives.on_interaction(greeted=True)
            if brain is None:
                rep.snapshot(drives, mood)
                continue  # 离线路径：不产生回复，但时间与状态都是真的
            rep.turns += 1
            t0 = time.time()
            try:
                # ⚠️ 这一步**不喂回放时间**：脑子里那轮对话是真花了秒级的。
                # 不喂，就不会出现“字在往外冒、它自己却老了 30 小时”。
                r = brain.chat(step.text)
                rep.latencies.append(time.time() - t0)
                if not (r.get("reply") or "").strip():
                    rep.empties += 1
            except Exception as e:
                rep.crashes += 1
                rep.last_error = f"{type(e).__name__}: {e}"
            rep.snapshot(drives, mood)
            if recorder is not None:
                recorder(step, drives, mood)
            if sleep_s > 0:
                time.sleep(sleep_s)
        rep.hours = (last - base) / 3600.0
        return rep
    finally:
        if ours:
            os.environ.pop("SAMMY_HOME", None)
            assert tmp is not None
            tmp.cleanup()
