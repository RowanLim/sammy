"""打字机显示 + 思考指示（U3）—— 回复逐字出现、等待时点会动。

界面这一角想解决两件事：

1. **回复别一下子全砸出来**：一句一句「打」出来，读起来有节奏，
   等模型那几秒也被这段节奏垫着（"降低等待感"是这轮 UI 的既定方向）。
   速度是数字不是感觉：每字 **40 毫秒**（25 字/秒），标点后多停 **90 毫秒**
   （断句感），整段超过 **4.5 秒**就**整体等比加速** —— 打字机是氛围，
   不许变成让人多等的理由。
2. **思考时用会动的点**：干等一个省略号看着像卡死；让点长起来
   （三个点一帧一帧地加，每 0.4 秒一帧）就是"它还在想"的全部信号。

## 为什么是纯函数

打字机对不对，是**时间形状**对不对 —— 快慢、停顿、上限、翻页节点。
盯着屏幕看不出来（40 毫秒一字的差别肉眼根本数不清），必须写下来算：
`char_times` / `visible_count` 是 O(n) 的纯函数，测试直接钉数字。
翻页与循环合成一张时间表 `TypePlan`（第一遍逐字打、第二遍起整页给），
画面层只问它"第 t 秒显示什么"。

首字**立刻出现**（t=0 就有一个字），不留"空一拍" —— 回复一到就有东西看。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

# ── 参数（都可以调，但调完要跑测试）──
TYPE_CPS = 25.0  # 每秒打出几个字（40 毫秒一字）
TYPE_PAUSE = 0.09  # 标点后的额外停顿（秒）
TYPE_CAP = 4.5  # 一页最长打多久；超了整体等比加速（等待感优先于仪式感）
PAUSE_CHARS = "。！？；：，、…—!?;:,.~"  # 会触发停顿的标点（中英都收）

DOT_PERIOD = 0.4  # 思考点每 0.4 秒变一帧
# 两套点共用同一条时间轴：回复区用**大点**（填充圆，空荡荡一块地方一眼看得见）；
# 正文行（状态行 / face-only 那一行）用**小点**（和文字同一套字距感）。
# 循环三帧；每帧都非空（不许有"什么都不显示"的瞬间）。
DOT_FRAMES = ("●", "●●", "●●●")
DOT_FRAMES_TEXT = ("·", "··", "···")

PAGE_HOLD = 3.6  # 每页打完后停留多久再翻页（与 layout.PAGE_SECONDS 对账，测试钉住）


def char_times(
    text: str,
    *,
    cps: float = TYPE_CPS,
    pause: float = TYPE_PAUSE,
    cap: float = TYPE_CAP,
) -> list[float]:
    """每个字符出现的时刻（升序；第 0 个在 0.0 —— 第一个字立刻出现）。

    每字 1/cps 秒；标点**之后**多停 pause 秒（断句感）。
    整段打不完（超过 cap 秒）→ 两项**等比压缩**，恰好卡在 cap 上。
    """
    n = len(text)
    if n == 0:
        return []
    pauses = sum(1 for ch in text[:-1] if ch in PAUSE_CHARS)  # 最后一个字后面的停顿没人等
    span = (n - 1) / cps + pauses * pause
    k = max(1.0, span / cap)  # 加速因子：k > 1 表示要压缩
    step = 1.0 / (cps * k)
    wait = pause / k
    out = [0.0]
    for ch in text[:-1]:
        out.append(out[-1] + step + (wait if ch in PAUSE_CHARS else 0.0))
    return out


def reveal_seconds(
    text: str,
    *,
    cps: float = TYPE_CPS,
    pause: float = TYPE_PAUSE,
    cap: float = TYPE_CAP,
) -> float:
    """整段打完要多久（= 最后一个字出现的时刻）。空串 = 0。"""
    times = char_times(text, cps=cps, pause=pause, cap=cap)
    return times[-1] if times else 0.0


def visible_count(
    text: str,
    t: float,
    *,
    cps: float = TYPE_CPS,
    pause: float = TYPE_PAUSE,
    cap: float = TYPE_CAP,
) -> int:
    """t 时刻已经露出几个字。

    +1e-9 的容差只修浮点边界：累积出来的"最后一个字的时刻"会跟 cap 差
    几百亿分之一，正好卡在边界上的调用（t == cap）该看到"全打完了"。
    """
    if not text:
        return 0
    return bisect_right(char_times(text, cps=cps, pause=pause, cap=cap), max(0.0, float(t)) + 1e-9)


def reveal(
    text: str,
    t: float,
    *,
    cps: float = TYPE_CPS,
    pause: float = TYPE_PAUSE,
    cap: float = TYPE_CAP,
) -> str:
    """t 时刻已经打出来的那一段（永远是 text 的前缀）。"""
    return text[: visible_count(text, t, cps=cps, pause=pause, cap=cap)]


def dots(t: float, frames: tuple[str, ...] = DOT_FRAMES) -> str:
    """思考点的当前帧（一个点长到三个点再循环，每 DOT_PERIOD 秒一帧）。

    加一点 epsilon 再取整：1.2 / 0.4 在浮点里是 2.9999…，不修会卡在第三帧。
    """
    frame = int(max(0.0, float(t)) / DOT_PERIOD + 1e-6)
    return frames[frame % len(frames)]


def grow_dots(base: str, t: float) -> str:
    """把句尾的那个省略号换成会动的小点；没有省略号就直接接上。"""
    stem = base[:-1] if base.endswith("…") else base
    return stem + dots(t, DOT_FRAMES_TEXT)


@dataclass
class TypePlan:
    """一条回复的「打字机时间表」（纯计算，不碰 Qt）。

    时间轴：

    - **第一遍**：每页先逐字打出来，打完后停 `hold` 秒再翻下一页；
    - **第二遍起**：按同样的节奏循环，但每页**直接整页显示** —— 已经看过的
      内容再一个字一个字蹦一遍只是浪费注意力（节奏稳定，内容不重复演出）。

    下游只调 `view_at(t)`：t 从「这条回复第一眼被画出来」算起。
    """

    pages: tuple[str, ...]
    hold: float = PAGE_HOLD
    cps: float = TYPE_CPS
    pause: float = TYPE_PAUSE
    cap: float = TYPE_CAP

    def __post_init__(self) -> None:
        starts: list[float] = []
        acc = 0.0
        for page in self.pages:
            starts.append(acc)
            acc += reveal_seconds(page, cps=self.cps, pause=self.pause, cap=self.cap) + self.hold
        self._starts = tuple(starts)
        self._loop = acc

    @property
    def loop(self) -> float:
        """一圈（第一遍）的总时长，秒。"""
        return self._loop

    def view_at(self, t: float) -> tuple[int, str]:
        """t 时刻显示什么：(第几页, 文本)。"""
        if not self.pages:
            return 0, ""
        if self._loop <= 0.0:  # 理论到不了（hold > 0）；兜底别除零
            return 0, self.pages[0]
        t = max(0.0, float(t))
        first_pass = t < self._loop
        lt = t if first_pass else t % self._loop  # 循环重放的本地时刻
        i = 0
        for k, start in enumerate(self._starts):
            if lt >= start:
                i = k
            else:
                break
        if not first_pass:
            return i, self.pages[i]
        return i, reveal(
            self.pages[i], lt - self._starts[i], cps=self.cps, pause=self.pause, cap=self.cap
        )


__all__ = [
    "DOT_FRAMES",
    "DOT_FRAMES_TEXT",
    "DOT_PERIOD",
    "PAGE_HOLD",
    "TYPE_CAP",
    "TYPE_CPS",
    "TYPE_PAUSE",
    "TypePlan",
    "char_times",
    "dots",
    "grow_dots",
    "reveal",
    "reveal_seconds",
    "visible_count",
]
