"""脸的动画 —— 让它像个活的东西，而不是一张贴图。

静态像素脸看起来"死"，缺的是三件事（按重要性排）：

1. **眨眼**（最强的"活"信号）：2.5~6 秒一次，偶尔连眨两下；
   上下压扁到 14%，约 110 毫秒。
2. **呼吸**：整体缓慢上下浮动，**±2 设备像素**，周期 ~4.5 秒。
   幅度必须小 —— 大了就变成"飘"，不是"呼吸"。
3. **微动/偷看**：慢慢左右偏一点（像在看别处），±2 像素，周期 ~11 秒（和呼吸不同频，
   否则两条正弦会同步成一种机械的摆动）。

另外：**换表情时弹一下**（0.22 秒内放大 6% 再回来），否则表情是"啪"地切断的。

## 为什么是纯函数

动画对不对，取决于"几秒内发生了什么" —— 盯着屏幕看不出来（尤其眨眼只有 110ms）。
所以这里把状态写成 `frame_at(t)` 的纯函数，测试就能钉住：
该眨的时候眨、不该眨的时候不眨、幅度不越界、睡着时别乱动。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# ── 参数（都可以调，但调完要跑测试）──
BLINK_MIN_GAP = 2.5  # 两次眨眼之间最短（秒）
BLINK_MAX_GAP = 6.0
BLINK_DURATION = 0.11  # 一次眨眼多久
BLINK_MIN_SQUASH = 0.14  # 压到多少（0=完全闭合）
DOUBLE_BLINK_CHANCE = 0.12  # 偶尔连眨两下
DOUBLE_BLINK_GAP = 0.18

BREATH_PERIOD = 4.5  # 呼吸周期（秒）
BREATH_AMPLITUDE = 2  # 设备像素（±）
SWAY_PERIOD = 11.3  # 微动周期 —— 特意和呼吸不同频，免得两条正弦同步
SWAY_AMPLITUDE = 2

POP_DURATION = 0.22  # 换表情时弹一下
POP_AMPLITUDE = 0.06  # 放大 6%

CALM_FACTOR = 0.25  # 睡着/休息时位移缩到多少
ANIM_DT = 0.033  # 驱动频率（~30fps）


@dataclass(frozen=True)
class Frame:
    """这一帧脸的形变量。"""

    squash: float = 1.0  # 1.0 = 正常；<1 = 正在眨眼
    dx: int = 0  # 左右微动（设备像素）
    dy: int = 0  # 呼吸位移（设备像素）
    pop: float = 1.0  # 换表情时的弹（1.0 = 无）

    @property
    def idle(self) -> bool:
        return self.squash == 1.0 and self.dx == 0 and self.dy == 0 and self.pop == 1.0


def _envelope(frac: float) -> float:
    """0→1→0 的平滑包络（眨眼用它，别用方波 —— 方波看着像故障）。"""
    if frac <= 0.0 or frac >= 1.0:
        return 0.0
    return 0.5 * (1.0 - math.cos(2 * math.pi * frac))


@dataclass
class Animator:
    """按时间给出脸部形变。自己安排眨眼时间表。"""

    seed: int | None = None
    blink_gap: tuple[float, float] = (BLINK_MIN_GAP, BLINK_MAX_GAP)
    _rng: random.Random = field(init=False, repr=False)
    _blinks: list[tuple[float, float]] = field(default_factory=list, repr=False)
    _next_at: float = field(default=0.0, repr=False)
    _pop_at: float = field(default=-99.0, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._next_at = self._rng.uniform(*self.blink_gap)

    # ── 眨眼时间表 ──────────────────────────────

    def _ensure(self, t: float) -> None:
        """把时间表推到 t 之后（至少 1 秒）。"""
        while self._next_at <= t + 1.0:
            self._blinks.append((self._next_at, BLINK_DURATION))
            self._next_at += self._rng.uniform(*self.blink_gap)
            if self._rng.random() < DOUBLE_BLINK_CHANCE:
                self._blinks.append((self._next_at - DOUBLE_BLINK_GAP, BLINK_DURATION))

    def blink_times(self, until: float) -> list[float]:
        """已安排 / 将要安排的眨眼起点（测试与调试用）。"""
        self._ensure(until)
        return [s for s, _ in self._blinks if s <= until]

    def reset(self, t: float = 0.0) -> None:
        """时间被拨动/重置时重新安排（别把旧时间表留在身上）。"""
        self._blinks = [b for b in self._blinks if b[0] > t]
        self._next_at = max(self._next_at, t) + self._rng.uniform(*self.blink_gap)

    # ── 换表情的"弹" ────────────────────────────

    def pop(self, at: float) -> None:
        self._pop_at = at

    # ── 这一帧 ──────────────────────────────────

    def frame_at(self, t: float, calm: bool = False) -> Frame:
        """时间 → 形变。

        `calm=True`（睡着/发呆）时位移大幅收敛 —— **睡着还晃来晃去就不像睡着了**。
        """
        t = max(0.0, float(t))  # 坏时间自愈：负数会让 sin 出怪值
        self._ensure(t)

        squash = 1.0
        if not calm:  # 睡着时闭着眼，不该再眨
            for start, dur in self._blinks:
                if start <= t <= start + dur:
                    squash = min(
                        squash, 1.0 - (1.0 - BLINK_MIN_SQUASH) * _envelope((t - start) / dur)
                    )

        amp = CALM_FACTOR if calm else 1.0
        dy = round(amp * BREATH_AMPLITUDE * math.sin(2 * math.pi * t / BREATH_PERIOD))
        dx = round(amp * SWAY_AMPLITUDE * math.sin(2 * math.pi * t / SWAY_PERIOD))

        pop = 1.0
        spent = t - self._pop_at
        if 0.0 <= spent <= POP_DURATION:
            pop = 1.0 + POP_AMPLITUDE * _envelope(spent / POP_DURATION)

        return Frame(squash=squash, dx=dx, dy=dy, pop=pop)


__all__ = [
    "ANIM_DT",
    "BLINK_DURATION",
    "BLINK_MIN_SQUASH",
    "BREATH_AMPLITUDE",
    "POP_DURATION",
    "SWAY_AMPLITUDE",
    "Animator",
    "Frame",
]
