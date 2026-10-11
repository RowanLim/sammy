"""脸的动画 —— 让它像个活的东西，而不是一张贴图。

静态像素脸看起来"死"，缺的是这几件事（按重要性排）：

1. **眨眼**（最强的"活"信号）：2.5~6 秒一次，偶尔连眨两下；
   上下压扁到 14%，约 110 毫秒。
2. **呼吸**：整体缓慢上下浮动，**±2 设备像素**，周期 ~4.5 秒。
   幅度必须小 —— 大了就变成"飘"，不是"呼吸"。
3. **微动/偷看**：慢慢左右偏一点（像在看别处），±2 像素，周期 ~11 秒（和呼吸不同频，
   否则两条正弦会同步成一种机械的摆动）。
4. **凝视漂移**（U2）：每 2.6~7.4 秒把脸缓动（0.55 秒）到新的随机方向 ——
   眼睛"会看"了，不再只是原地微微晃。看向左右边缘时脸被**纵向轻拉**（好奇：探着头看）。
   ⚠️ 位图脸没法只动眼睛，用"整脸的定向偏移 + 拉高"来表达"在看哪儿"。
   这是从 RoboEyes（FluxGarage，GPL-3.0）借的**行为想法**，实现一行没抄。
5. **换表情交叉淡化**（U2）：0.38 秒老脸淡出、新脸淡入 —— 换情绪是"缓过去"的，
   不是"啪"地切断（原先只有一个 0.22 秒的弹跳）。
6. **说话动脸**（自选小步·第六次）：打字机在吐字时，脸按说话节奏轻轻起伏
   （上下弹 ±2.6 设备像素 + 极轻的一鼓一收 ±2%）—— 「字在往外冒，脸跟着动」；
   字停了脸也停（缓入 0.18 秒、收口 0.26 秒）。

睡觉（calm）时：不眨眼、位移收敛、**凝视定格**在睡前方向 —— 睡着还四处看、
还晃来晃去就不像睡着了；醒来从定格处接着缓动，不跳。

## 为什么是纯函数

动画对不对，取决于"几秒内发生了什么" —— 盯着屏幕看不出来（尤其眨眼只有 110ms）。
这里把状态写成 `frame_at(t)` 的纯函数，测试就能钉住：该眨的时候眨、不该眨的时候不眨、
幅度不越界、睡着时别乱动、凝视别瞬移。凝视/淡化带一点内部状态（目标表、上一张脸），
对**单调前进的 t** 是确定的；同种子完全可复现。
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

# 凝视漂移（U2）—— 幅度单位是设备像素（800×480 坐标系）
GAZE_MIN_GAP = 2.6  # 两次"看向新方向"之间最短（秒）
GAZE_MAX_GAP = 7.4
GAZE_EASE = 0.55  # 一次转眼的缓动时长：够"看过去"，又不拖泥带水
GAZE_MAX_X = 10  # 横向摆幅 ±：脸的格子很宽，再大就读成"滑出去"了
GAZE_MAX_Y = 6  # 纵向摆幅 ±：比横向收着点，上下动太多读起来像点头
CURIOSITY_STRETCH = 0.07  # 看向左右边缘时纵向拉高的上限（7%）

FADE_DURATION = 0.38  # 换表情的交叉淡化时长（老脸退场、新脸进场）

# 光标凝视（自选小步·第三次）——「它在看着你」：光标当第二个"值得看的东西"
LOOK_MOVE_MIN = 6  # 光标累计动这么多设备像素才算"在动"（贴身手抖不算）
LOOK_HOLD_S = 2.5  # 光标停下后还朝它看多久（秒）；之后回去发自己的呆
LOOK_RETARGET_MIN_S = 0.45  # 追光标时两次转视的最小间隔（再快就像扫视机器）

# 搬运凝视（自选小步·第五次）——「被带去哪儿就看哪儿」：拖动窗口 = 被搬走
CARRY_GAIN = 0.08  # 搬动位移 → 凝视目标的增益（慢挪只瞥一眼，快搬直接贴边）
CARRY_MOVE_MIN = 12  # 累计动这么多设备像素才值得转一次视线（贴手小抖不算）
CARRY_RETARGET_MIN_S = 0.35  # 搬运时两次转视的最小间隔（秒）

# 说话动脸（自选小步·第六次）——「字在往外冒，脸跟着动」：打字机在吐字时，
# 脸按说话节奏轻轻起伏（上下弹 + 极轻的一鼓一收）；字停了，脸也停。
TALK_PERIOD = 0.44  # 说话「嘴动」的一拍多长（秒）—— 约 2.3 拍每秒
TALK_BOB_Y = 2.6  # 上下弹幅（设备像素，正负）：比呼吸稍大，比凝视小一个量级
TALK_SQUASH = 0.02  # 一鼓一收（正负 2 个百分点）：整脸没有嘴，靠它补「在发音」
TALK_EASE_IN = 0.18  # 开口：包络从 0 涨到满用多久（秒）
TALK_EASE_OUT = 0.26  # 收口：从停下到完全静下来用多久（秒）—— 比开口慢一点，像松开

CALM_FACTOR = 0.25  # 睡着/休息时位移缩到多少
ANIM_DT = 0.033  # 驱动频率（~30fps）


@dataclass(frozen=True)
class Frame:
    """这一帧脸的形变量。"""

    squash: float = 1.0  # 1.0 = 正常；<1 = 正在眨眼
    dx: int = 0  # 左右微动（设备像素）
    dy: int = 0  # 呼吸位移（设备像素）
    pop: float = 1.0  # 换表情时的弹（1.0 = 无）
    gx: int = 0  # 凝视偏移：脸正往哪边"看"
    gy: int = 0
    stretch: float = 1.0  # 好奇：看向边缘时纵向拉高（1.0 = 无）
    talk_y: int = 0  # 说话：上下弹（设备像素；0 = 不在说话）
    talk_sq: float = 1.0  # 说话：一鼓一收（1.0 = 不在说话）

    @property
    def idle(self) -> bool:
        return (
            self.squash == 1.0
            and self.dx == 0
            and self.dy == 0
            and self.pop == 1.0
            and self.gx == 0
            and self.gy == 0
            and self.stretch == 1.0
            and self.talk_y == 0
            and self.talk_sq == 1.0
        )


def _envelope(frac: float) -> float:
    """0→1→0 的平滑包络（眨眼用它，别用方波 —— 方波看着像故障）。"""
    if frac <= 0.0 or frac >= 1.0:
        return 0.0
    return 0.5 * (1.0 - math.cos(2 * math.pi * frac))


def _smooth01(p: float) -> float:
    """0→1 的平滑缓动（两端速度为 0）—— 凝视转场与交叉淡化共用这一条曲线。"""
    p = min(1.0, max(0.0, p))
    return 0.5 * (1.0 - math.cos(math.pi * p))


def cursor_target(dx: float, dy: float) -> tuple[int, int]:
    """光标方向 → 凝视目标：按比例压进凝视盒。

    规则：方向不扭曲（x / y 同比例收）；很近时**如实映射**（不许放大 ——
    光标就在脸跟前，脸不该探到满幅）；够远就贴边（仍在盒内）。
    """
    k = 1.0
    if dx:
        k = min(k, GAZE_MAX_X / abs(dx))
    if dy:
        k = min(k, GAZE_MAX_Y / abs(dy))
    return round(dx * k), round(dy * k)


def carry_target(dx: float, dy: float) -> tuple[int, int]:
    """搬动位移 → 凝视目标：先按 CARRY_GAIN 放大，再走光标那套「压进凝视盒」。

    慢挪（每段一小截）只有小小一瞥；一阵快搬把盒填满、直接贴边看（配好奇拉高）。
    映射本身不新加任何规则 —— 方向不扭曲、近了如实、远了贴边，全和光标共用一条。
    """
    return cursor_target(dx * CARRY_GAIN, dy * CARRY_GAIN)


def _pos_from(commands: list[_Gaze], t: float) -> tuple[int, int]:
    """凝视指令表在 t 时刻的位置：缓动过去（GAZE_EASE 秒），然后定格。"""
    cur = commands[0]
    for g in commands:
        if g.t <= t:
            cur = g
        else:
            break
    p = _smooth01((t - cur.t) / GAZE_EASE)  # 还没出发（p<0）会被夹到 0
    return (
        round(cur.fx + (cur.x - cur.fx) * p),
        round(cur.fy + (cur.y - cur.fy) * p),
    )


@dataclass(frozen=True)
class _Gaze:
    """一次"看向某处"的指令：t 时刻出发，从 (fx, fy) 缓动到 (x, y)。"""

    t: float
    x: int
    y: int
    fx: int
    fy: int


@dataclass
class Animator:
    """按时间给出脸部形变。自己安排眨眼与凝视的时间表。"""

    seed: int | None = None
    blink_gap: tuple[float, float] = (BLINK_MIN_GAP, BLINK_MAX_GAP)
    _rng: random.Random = field(init=False, repr=False)
    _blinks: list[tuple[float, float]] = field(default_factory=list, repr=False)
    _next_at: float = field(default=0.0, repr=False)
    _pop_at: float = field(default=-99.0, repr=False)
    _gaze: list[_Gaze] = field(default_factory=list, repr=False)
    _frozen: tuple[int, int] | None = field(default=None, repr=False)
    _expr: int | None = field(default=None, repr=False)
    _fade_from: int | None = field(default=None, repr=False)
    _fade_at: float = field(default=-99.0, repr=False)
    # 光标凝视：最近一次光标位置（相对脸中心，设备像素）与"想看"状态
    _cursor: tuple[float, float] | None = field(default=None, repr=False)
    _cursor_ref: tuple[float, float] | None = field(default=None, repr=False)
    _cursor_active_t: float = field(default=float("-inf"), repr=False)
    _look_dirty: bool = field(default=False, repr=False)
    _look_retarget_t: float = field(default=float("-inf"), repr=False)
    # 搬运凝视：自上次转视以来攒下的搬动位移（设备像素）
    _carry_acc: tuple[float, float] = field(default=(0.0, 0.0), repr=False)
    # 说话动脸：开口起点 / 收口起点与音量（None = 没有在收口）
    _talk_active: bool = field(default=False, repr=False)
    _talk_t0: float = field(default=0.0, repr=False)
    _talk_stop_t: float | None = field(default=None, repr=False)
    _talk_stop_level: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._next_at = self._rng.uniform(*self.blink_gap)
        # 开场：从正中出发，1 秒多之后看第一眼
        self._gaze = [self._new_gaze(1.0 + self._rng.uniform(0.0, 1.5), 0, 0)]

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

    # ── 凝视时间表 ──────────────────────────────

    def _new_gaze(self, at: float, fx: int, fy: int) -> _Gaze:
        return _Gaze(
            t=at,
            x=self._rng.randint(-GAZE_MAX_X, GAZE_MAX_X),
            y=self._rng.randint(-GAZE_MAX_Y, GAZE_MAX_Y),
            fx=fx,
            fy=fy,
        )

    def _ensure_gaze(self, t: float) -> None:
        while self._gaze[-1].t < t + 1.0:
            last = self._gaze[-1]
            self._gaze.append(
                self._new_gaze(
                    last.t + self._rng.uniform(GAZE_MIN_GAP, GAZE_MAX_GAP), last.x, last.y
                )
            )

    def gaze_times(self, until: float) -> list[float]:
        """已安排 / 将要安排的凝视起点（测试与调试用）。"""
        self._ensure_gaze(until)
        return [g.t for g in self._gaze if g.t <= until]

    def _gaze_pos(self, t: float) -> tuple[int, int]:
        """t 时刻的凝视偏移：缓动过去（GAZE_EASE 秒），然后定格。

        定格段不要再抖 —— "看定"本身就是一个信号（有机的微动另有 sway/breath）。
        """
        self._ensure_gaze(t)
        return _pos_from(self._gaze, t)

    # ── 光标凝视：「它在看着你」────────────────────

    def note_cursor(self, dx: float, dy: float, t: float) -> None:
        """喂一次"当前光标在哪"（相对脸中心，设备像素）—— 窗口每帧调一次。

        判"在动"用**累计位移**：慢速拖动攒够 LOOK_MOVE_MIN 像素也算动；
        贴身手抖（幅度总小于阈值）不算 —— 光标自己都没动，脸不该乱看。
        """
        if self._cursor_ref is None:
            self._cursor_ref = (dx, dy)  # 第一笔只建立参照（"之前在哪"）
        self._cursor = (dx, dy)
        rx, ry = self._cursor_ref
        if math.hypot(dx - rx, dy - ry) >= LOOK_MOVE_MIN:
            self._cursor_ref = (dx, dy)
            self._cursor_active_t = t
            self._look_dirty = True

    def _look_step(self, t: float) -> None:
        """光标凝视的逐帧决策：该转就转，过期的"想看"作废（不会突然补看）。"""
        if not self._look_dirty:
            return
        if t - self._cursor_active_t > LOOK_HOLD_S:
            self._look_dirty = False  # 光标早停了：这条"想看"过期作废
            return
        if t < self._look_retarget_t + LOOK_RETARGET_MIN_S:
            return  # 追得太密会像扫视机器：隔一小会再转
        self._look_dirty = False
        self._look_retarget_t = t
        if self._cursor is None:
            return
        x, y = cursor_target(*self._cursor)
        self._retarget_gaze(t, x, y)
        self._carry_acc = (0.0, 0.0)  # 光标赢了：搬运方向作废（手才是新目标）

    def _retarget_gaze(self, t: float, x: int, y: int) -> None:
        """挂一条"此刻就转过去看"的凝视指令。

        清掉更晚的旧目标（光标优先），从**当前实际位置**起步 —— 中途改向也不跳。
        已经在看那儿且缓动已经完成，就不挂空指令。
        """
        kept = [g for g in self._gaze if g.t <= t]
        self._gaze = kept or [_Gaze(t=0.0, x=0, y=0, fx=0, fy=0)]
        fx, fy = _pos_from(self._gaze, t)
        last = self._gaze[-1]
        if (x, y) == (last.x, last.y) and t >= last.t + GAZE_EASE:
            return
        self._gaze.append(_Gaze(t=t, x=x, y=y, fx=fx, fy=fy))

    # ── 搬运凝视：「被带去哪儿就看哪儿」────────────

    def begin_carry(self) -> None:
        """鼠标按住窗口（=被拎起来）：光标凝视作废、旧搬运累积清零。

        「手是拿着它的手，不是指东西的手」—— 抓起来的一瞬，那条还没执行的
        「去看光标」就不作数了；上一程的零头也不带进这一次搬运。
        """
        self._carry_acc = (0.0, 0.0)
        self._look_dirty = False

    def note_carry(self, dx: float, dy: float) -> None:
        """喂一次搬运位移（设备像素）：窗口每动一步调一次。

        方向判断在 _carry_step 里做（攒够 CARRY_MOVE_MIN 才转视线）——
        贴着手的小抖动正负抵消，攒不起来。
        """
        ax, ay = self._carry_acc
        self._carry_acc = (ax + dx, ay + dy)

    def end_carry(self) -> None:
        """放手：零头作废 —— 收尾不许从满幅往回泄一截（像泄气）。"""
        self._carry_acc = (0.0, 0.0)

    def _carry_step(self, t: float) -> None:
        """搬运凝视的逐帧决策：攒够了、也过了限速窗口，就转过去看行进方向。"""
        ax, ay = self._carry_acc
        if math.hypot(ax, ay) < CARRY_MOVE_MIN:
            return
        if t < self._look_retarget_t + CARRY_RETARGET_MIN_S:
            return
        self._carry_acc = (0.0, 0.0)
        self._look_retarget_t = t
        self._retarget_gaze(t, *carry_target(ax, ay))

    # ── 说话动脸：「字在往外冒，脸跟着动」────────────

    def note_talk(self, t: float, active: bool) -> None:
        """喂一次「现在在不在说话」（打字机在不在吐字）—— 窗口每帧调一次。

        变 True：开口，从静息出发（包络从 0 长到满）；
        变 False：收口，从**停下这一刻的音量**缓出去（不是啪地掐断）。
        重开一段时不再追溯旧相位 —— 实际时序里两段说话之间隔着模型延迟，
        接缝（至多半像素、一帧）看不见；真实打断走的是「话赶话」，自有新的开场。
        """
        if active:
            if not self._talk_active:
                self._talk_active = True
                self._talk_t0 = t
                self._talk_stop_t = None
                self._talk_stop_level = 0.0
            return
        if self._talk_active:
            level = self._talk_env(t)  # 停下这一刻的音量（先算再关）
            self._talk_active = False
            self._talk_stop_t = t
            self._talk_stop_level = level

    def _talk_env(self, t: float) -> float:
        """说话包络（0 到 1）：开口渐入、收口渐出；完全停下之后是 0。"""
        if self._talk_active:
            return _smooth01((t - self._talk_t0) / TALK_EASE_IN)
        if self._talk_stop_t is None or self._talk_stop_level <= 0.0:
            return 0.0
        fade = (t - self._talk_stop_t) / TALK_EASE_OUT
        if fade >= 1.0:
            return 0.0
        return self._talk_stop_level * (1.0 - _smooth01(fade))

    def _unfreeze(self, t: float, frozen: tuple[int, int]) -> None:
        """醒来：清掉睡着期间的未来目标，从定格处缓动到原计划方向（不跳）。"""
        kept = [g for g in self._gaze if g.t <= t]
        if kept:
            self._gaze = kept
        target = self._gaze[-1]
        self._gaze.append(_Gaze(t=t, x=target.x, y=target.y, fx=frozen[0], fy=frozen[1]))

    def reset(self, t: float = 0.0) -> None:
        """时间被拨动/重置时重新安排（别把旧时间表留在身上）。"""
        self._blinks = [b for b in self._blinks if b[0] > t]
        self._next_at = max(self._next_at, t) + self._rng.uniform(*self.blink_gap)
        self._frozen = None
        self._look_dirty = False  # 时间线被拨动：别把旧的"想看"带过去
        self._carry_acc = (0.0, 0.0)  # 搬运累积同理：拨过时间线就不作数
        self._talk_active = False  # 说话状态同理：时间线被拨动，别抱着旧包络
        self._talk_stop_t = None
        self._talk_stop_level = 0.0
        self._gaze = [g for g in self._gaze if g.t > t]
        if not self._gaze:
            self._gaze = [self._new_gaze(t + 1.2, 0, 0)]

    # ── 换表情的"弹"与交叉淡化 ────────────────────

    def pop(self, at: float) -> None:
        self._pop_at = at

    def set_expression(self, index: int, at: float | None) -> None:
        """界面换表情时告诉动画层，好记住"上一张脸"用于交叉淡化。

        `at=None`（动画关着、没有时间轴）→ 瞬间切，不留淡化状态。
        """
        if at is None or self._expr is None:
            self._expr = index
            self._fade_from = None
            return
        if index == self._expr:
            return
        self._fade_from = self._expr
        self._fade_at = float(at)
        self._expr = index
        self.pop(at)  # 顺手弹一下：淡化的同时还有个小小的"应答"

    def expr_fade(self, t: float) -> tuple[int | None, float]:
        """淡化进度 → (要退场的表情编号 | None, 新脸的不透明度 0~1)。

        没有淡化在跑时返回 (None, 1.0)：渲染层按"直接画当前脸"处理。
        """
        if self._fade_from is None or t >= self._fade_at + FADE_DURATION:
            return None, 1.0
        if t <= self._fade_at:
            return self._fade_from, 0.0
        return self._fade_from, _smooth01((t - self._fade_at) / FADE_DURATION)

    # ── 这一帧 ──────────────────────────────────

    def frame_at(self, t: float, calm: bool = False) -> Frame:
        """时间 → 形变。

        `calm=True`（睡着/发呆）时：不眨眼、位移收敛、凝视**冻住** ——
        睡着还四处看、还晃来晃去，就不像睡着了。
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

        # 凝视：睡着时定格在睡前看向的方向（不是跳回正中），醒来从定格处接上
        if calm:
            if self._frozen is None:
                self._frozen = self._gaze_pos(t)
            gx, gy = self._frozen
        else:
            if self._frozen is not None:
                frozen, self._frozen = self._frozen, None
                self._unfreeze(t, frozen)
            self._look_step(t)
            self._carry_step(t)
            gx, gy = self._gaze_pos(t)

        # 好奇：越靠左右边缘，脸越"探"（只拉高，不拉宽）
        edge = min(1.0, abs(gx) / GAZE_MAX_X)
        stretch = 1.0 + CURIOSITY_STRETCH * edge * edge

        pop = 1.0
        spent = t - self._pop_at
        if 0.0 <= spent <= POP_DURATION:
            pop = 1.0 + POP_AMPLITUDE * _envelope(spent / POP_DURATION)

        # 说话动脸：字在冒的时候按说话节奏轻轻起伏；睡着不弹（定格优先）
        talk_y = 0
        talk_sq = 1.0
        if not calm:
            env = self._talk_env(t)
            if env > 0.0:
                wave = math.sin(2 * math.pi * (t - self._talk_t0) / TALK_PERIOD)
                talk_y = round(TALK_BOB_Y * env * wave)
                talk_sq = 1.0 + TALK_SQUASH * env * wave

        return Frame(
            squash=squash,
            dx=dx,
            dy=dy,
            pop=pop,
            gx=gx,
            gy=gy,
            stretch=stretch,
            talk_y=talk_y,
            talk_sq=talk_sq,
        )


__all__ = [
    "ANIM_DT",
    "BLINK_DURATION",
    "BLINK_MIN_SQUASH",
    "BREATH_AMPLITUDE",
    "CARRY_GAIN",
    "CARRY_MOVE_MIN",
    "CARRY_RETARGET_MIN_S",
    "CURIOSITY_STRETCH",
    "FADE_DURATION",
    "GAZE_EASE",
    "GAZE_MAX_GAP",
    "GAZE_MAX_X",
    "GAZE_MAX_Y",
    "GAZE_MIN_GAP",
    "LOOK_HOLD_S",
    "LOOK_MOVE_MIN",
    "LOOK_RETARGET_MIN_S",
    "POP_DURATION",
    "SWAY_AMPLITUDE",
    "TALK_BOB_Y",
    "TALK_EASE_IN",
    "TALK_EASE_OUT",
    "TALK_PERIOD",
    "TALK_SQUASH",
    "Animator",
    "Frame",
    "carry_target",
    "cursor_target",
]
