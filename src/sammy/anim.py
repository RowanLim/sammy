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
7. **醒来的哈欠**（自选小步·第八次）：睡醒那一刻打一个哈欠 ——
   整脸缓慢拉高（伸懒腰）、眼睛眯起来撑住（呵——）、再慢慢收回去；
   睡着时不做（calm 优先），只在「睡着 → 醒着」那一刻由窗口安排一次。
8. **无聊的叹气**（自选小步·第九次）：没人理、闷了的时候，隔一会儿叹一口气 ——
   脸缓缓沉下去（往下 SIGH_SINK_PX）、瘪一点（压到 SIGH_DEFLATE）、屏住一下，
   再慢慢回起来；不无聊了就停（排期在 note_bored 里）。和 Z（睡着）、
   哈欠（醒来）同一条思路：**状态要能被眼睛读出来**。

9. **困得点头**（自选小步·第十次）：犯困、还没睡着的时候，隔一会儿小鸡啄米 ——
   脸慢慢沉下去、眼皮掉下来、撑住一下，再猛地弹回来；不困了就停（排期在
   note_sleepy 里）。和 Z（睡着）、哈欠（醒来）、叹气（无聊）同一条思路：
   **状态要能被眼睛读出来** —— 这条补上「困」。

10. **打字凝视**（自选小步·第十一次）：「看着你写」—— 你在输入框里敲字
    （= 在跟它说话、还没说完）的时候，它把四处看的视线收回来，落到输入框上；
    你停手 TYPING_HOLD_S 秒，它才回去发自己的呆。优先级：光标（手在指东西）
    与搬运在前，打字垫底；睡着 / 动画关都不做。

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

# ── 睡相：睡着时脸边那个 Z（2026-10-12）────────────────
# 为什么要有：睡着时脸是静的。**静的脸和死机的脸在屏幕上长得一样** ——
# 有个东西在慢慢冒，才一眼看出"是它睡着了"，而不是"它卡住了"。
Z_PERIOD = 2.6  # 一个 Z 从冒出来到消失（秒）
Z_RISE_PX = 9  # 这期间升起多少设备像素（慢，才像呼吸）
Z_SHOW_FRAC = 0.62  # 周期里它可见的比例；其余时间空着，才有"一个一个冒"的节奏


def z_alpha(t: float) -> float:
    """睡着时那个 Z 的不透明度（0 = 这一帧不画）。纯函数，好在测试里钉死周期。"""
    phase = (t % Z_PERIOD) / Z_PERIOD
    if phase >= Z_SHOW_FRAC:
        return 0.0
    return math.sin(math.pi * (phase / Z_SHOW_FRAC))  # 淡入淡出，别"啪"地闪


def z_rise(t: float) -> float:
    """这个 Z 已经升起了多少设备像素（0 → Z_RISE_PX，跟 alpha 同一条时间线）。"""
    phase = (t % Z_PERIOD) / Z_PERIOD
    if phase >= Z_SHOW_FRAC:
        return 0.0
    return Z_RISE_PX * (phase / Z_SHOW_FRAC)


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

# 醒来的哈欠（自选小步·第八次）——「睡醒了先伸个懒腰、打个哈欠」
# 睡相（第七次）解决了「睡着看得出来」，可**醒**是瞬间的：睡脸直接切回暖脸，
# 读起来像换了张贴纸。哈欠把「醒来」变成一个过程：先抻起来（伸懒腰）→
# 眼睛眯上撑一小会（呵——）→ 慢慢松开、落回常态（清醒了）。
# 两条曲线各管一摊：拉高曲线（RISE/HOLD/SETTLE）管「抻 + 拔高」；
# 眯眼曲线（SQUINT_*）比它晚一拍起步 —— 先抻后眯才像哈欠，
# 两条一起开始会像被从中间捏住（第一版就是这么翻车的，DEVLOG 有记）。
YAWN_RISE_S = 0.45  # 拉高曲线：撑起来用时（秒）
YAWN_HOLD_S = 0.45  # 拉高曲线：撑住的那一小段（秒）—— 要够长，先让人看清「抻起来了」再眯眼
YAWN_SETTLE_S = 0.70  # 拉高曲线：收回去用时（秒）
YAWN_STRETCH = 0.10  # 纵向拉高上限（10%）：比好奇的 7% 更明显 —— 这是全身的劲
YAWN_LIFT_PX = 3  # 整脸往上顶几像素：伸懒腰的「拔高」
YAWN_SQUINT_DELAY_S = 0.55  # 眯眼曲线：比拉高晚多久起步（秒）：先抻后眯
YAWN_SQUINT_RISE_S = 0.35  # 眯眼曲线：合上用时（秒）
YAWN_SQUINT_FALL_S = 0.70  # 眯眼曲线：松开用时（秒）—— 比合上慢，像慢慢睁开
YAWN_SQUINT_MIN = 0.30  # 眯到原来的 30%（眨眼是 14% —— 哈欠的眯眼浅一点、慢一点）

# 无聊的叹气（自选小步·第九次）——「没人理的时候，隔一会儿叹一口气」
# 无聊（boredom 驱力）原先只写在状态行和一张静态脸里；一个真的活物闲着发闷
# 会把气叹出来：脸**缓缓沉下去、瘪一点、屏住一下、再慢慢回起来**。
# 和 Z（睡着）、哈欠（醒来）同一条思路：状态要能被眼睛读出来。
SIGH_MIN_GAP = 20.0  # 两次叹气之间最短（秒）
SIGH_MAX_GAP = 60.0  # 最长；两者之间随机 —— 别像节拍器
SIGH_SINK_S = 0.60  # 沉下去用时（秒）
SIGH_HOLD_S = 0.30  # 沉住的那一小段（秒）——「……」的停顿
SIGH_RISE_S = 1.10  # 慢慢回起来用时（秒）—— 比沉下去慢：撒气快、缓回来
SIGH_DEFLATE = 0.94  # 沉到底时纵向压到 94%（撒气那一下的「瘪」）
SIGH_SINK_PX = 4  # 整脸往下沉几像素（设备像素）：和压扁叠在一起读成「塌下来」

# 困得点头（自选小步·第十次）——「困了的时候，一点一点地打盹」
# 犯困（energy 低于驱力的犯困线）原先只写在状态行和一张静态脸里；一个真的
# 活物快扛不住睡意时会**小鸡啄米**：脸慢慢沉下去、眼皮掉下来、撑住一下，
# 再猛地弹回来。和 Z（睡着）、哈欠（醒来）、叹气（无聊）同一条思路：
# 状态要能被眼睛读出来 —— 这条补上「困」。
NOD_MIN_GAP = 35.0  # 两次点头之间最短（秒）
NOD_MAX_GAP = 90.0  # 最长；两者之间随机 —— 别像节拍器
NOD_SAG_S = 1.40  # 沉下去用时（秒）—— 慢：是「扛不住」，不是「点头称是」
NOD_HOLD_S = 0.30  # 沉住的那一小段（秒）——「睡着了一瞬」
NOD_SNAP_S = 0.28  # 弹回来用时（秒）—— 猛地惊醒，比沉下去快一个量级
NOD_SQUINT_MIN = 0.50  # 沉到底时压到 50%（眼皮快合上；眨眼 14%、哈欠眯眼 30%）
NOD_SINK_PX = 5  # 整脸往下沉几像素：和压扁叠在一起读成「头一点」

# 打字凝视（自选小步·第十一次）——「看着你写」：你在输入框里敲字 = 在跟它说话
# （还没说完），此刻它不再四处看，视线落到输入框上 —— 和「点一下输入框瞥一眼」
# 同向，但你在写多久它就守多久；你停手 TYPING_HOLD_S 秒，它才回去发自己的呆。
# 光标（手在指东西）优先：刚指过的那一眼先看够（LOOK_HOLD_S），打字垫底。
TYPING_HOLD_S = 4.0  # 最后一个键之后还看多久（秒）—— 和「刚交互 5 秒」一个量级
TYPING_RETARGET_MIN_S = 0.35  # 发现你在写后的转视最小间隔（秒；别一敲字就弹）
TYPING_GAZE_Y = GAZE_MAX_Y  # 输入框在脸的正下方：视线纵向拉满 = 看到最底下那行

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


def yawn_amount(t_spent: float) -> float:
    """哈欠的形状（0 → 1 → 0）：撑起来、撑住、收回去 —— 三段拼成一条时间线。

    纯函数：每段多长、峰值在哪，测试里逐点钉死。
    `t_spent` = 距离这次哈欠开始过了多久；负数 = 还没开始（0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < YAWN_RISE_S:
        return _smooth01(t_spent / YAWN_RISE_S)
    if t_spent < YAWN_RISE_S + YAWN_HOLD_S:
        return 1.0
    k = t_spent - YAWN_RISE_S - YAWN_HOLD_S
    if k < YAWN_SETTLE_S:
        return 1.0 - _smooth01(k / YAWN_SETTLE_S)
    return 0.0


def yawn_squint(t_spent: float) -> float:
    """哈欠里「眯眼」那一口（0 → 1 → 0）—— 比拉高晚一拍起步。

    先抻后眯：两条曲线一起动会像被从中间捏住（第一版实测），
    分开动才是「伸懒腰伸到位了、眼睛跟着眯上」的顺序。
    峰值落在拉高的撑住段尾巴上（0.55 + 0.35 = 0.90 ∈ [0.45, 0.90]）。
    """
    t = t_spent - YAWN_SQUINT_DELAY_S
    if t < 0:
        return 0.0
    if t < YAWN_SQUINT_RISE_S:
        return _smooth01(t / YAWN_SQUINT_RISE_S)
    k = t - YAWN_SQUINT_RISE_S
    if k < YAWN_SQUINT_FALL_S:
        return 1.0 - _smooth01(k / YAWN_SQUINT_FALL_S)
    return 0.0


def yawn_total() -> float:
    """一次哈欠从头到尾的时长（秒）。"""
    return YAWN_RISE_S + YAWN_HOLD_S + YAWN_SETTLE_S


def sigh_amount(t_spent: float) -> float:
    """叹气的形状（0 → 1 → 0）：沉下去 → 屏住 → 慢慢回起来。

    纯函数：三段的时间线在测试里逐点钉死 —— 比眨眼慢、比哈欠轻，
    这是「无聊」这个状态第一次变成**看得见的动作**。
    `t_spent` = 距离这次叹气开始过了多久；负数 = 还没开始（0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < SIGH_SINK_S:
        return _smooth01(t_spent / SIGH_SINK_S)
    if t_spent < SIGH_SINK_S + SIGH_HOLD_S:
        return 1.0
    k = t_spent - SIGH_SINK_S - SIGH_HOLD_S
    if k < SIGH_RISE_S:
        return 1.0 - _smooth01(k / SIGH_RISE_S)
    return 0.0


def sigh_total() -> float:
    """一次叹气从头到尾的时长（秒）。"""
    return SIGH_SINK_S + SIGH_HOLD_S + SIGH_RISE_S


def nod_amount(t_spent: float) -> float:
    """点头打盹的形状（0 → 1 → 0）：沉下去 → 撑住 → 猛地弹回来。

    纯函数：三段的时间线在测试里逐点钉死 —— 前两段慢、最后一段快，
    快慢对比就是「惊醒」的读法；这是「困」这个状态第一次变成看得见的动作。
    `t_spent` = 距离这次点头开始过了多久；负数 = 还没开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < NOD_SAG_S:
        return _smooth01(t_spent / NOD_SAG_S)
    if t_spent < NOD_SAG_S + NOD_HOLD_S:
        return 1.0
    k = t_spent - NOD_SAG_S - NOD_HOLD_S
    if k < NOD_SNAP_S:
        return 1.0 - _smooth01(k / NOD_SNAP_S)
    return 0.0


def nod_total() -> float:
    """一次点头打盹从头到尾的时长（秒）。"""
    return NOD_SAG_S + NOD_HOLD_S + NOD_SNAP_S


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
    # 醒来的哈欠：开始时刻；-99 = 没有（很远的过去，不会碰巧命中）
    _yawn_at: float = field(default=-99.0, repr=False)
    # 无聊的叹气：这一口的开始时刻（-99 = 没有）；下一次的排期（None = 不无聊、没在排）
    _sigh_at: float = field(default=-99.0, repr=False)
    _sigh_next_at: float | None = field(default=None, repr=False)
    # 困得点头：这一下的开始时刻（-99 = 没有）；下一次的排期（None = 不困、没在排）
    _nod_at: float = field(default=-99.0, repr=False)
    _nod_next_at: float | None = field(default=None, repr=False)
    # 打字凝视：最后一次按键的时刻（-inf = 没在写）
    _typing_at: float = field(default=float("-inf"), repr=False)
    # 打字暂停是否发生过（恢复的第一次补排程要把锚点拨到当下，见 _ensure_gaze）
    _typing_was_active: bool = field(default=False, repr=False)

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
        rebase = self._typing_was_active  # 刚打完字：这次补排程把锚点拨到当下
        while self._gaze[-1].t < t + 1.0:
            if self.typing_active(t):
                self._typing_was_active = True
                return  # 打字中：漂移暂停 —— 别把「看别处」排进写字这段时间
            last = self._gaze[-1]
            # 正常顺排：从 last.t 往后。**唯一例外**是「打字暂停刚结束」的第一次：
            # 暂停期间不排程，时间表在它身上空了一段；要是还从暂停前顺排，会一次
            # 塞进好几条落在过去的指令，恢复的第一帧就往「早就该在的位置」跳一下。
            # 锚点取 max(last.t, t)：恢复后从当下重排（这条缺口只有打字暂停会常规
            # 地制造 —— 别的路径全部保持原行为，金色基线一个字节都不许动）。
            anchor = max(last.t, t) if rebase else last.t
            self._gaze.append(
                self._new_gaze(
                    anchor + self._rng.uniform(GAZE_MIN_GAP, GAZE_MAX_GAP), last.x, last.y
                )
            )
            rebase = False  # 只拨这一次，后面回到正常顺排
        self._typing_was_active = False

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

    # ── 打字凝视：「看着你写」────────────────────────
    # 你在输入框里敲字 = 在跟它说话（还没说完）。此刻把「四处看」收掉，视线落到
    # 输入框上 —— 和「点一下输入框瞥一眼」（光标凝视）同向，但你在写多久它就守多久。
    # 优先级：先看手 —— 刚指过的先看够（光标），正被搬的让路（共用限速），打字垫底。

    def note_typing(self, t: float) -> None:
        """喂一次「刚敲了个键」（窗口在输入框 textChanged 时调）。

        只记时间（单调不减）；看不看、看多久全在 _typing_step 里定 ——
        和 note_cursor 一样，喂进来的是原始事件，决策是纯函数。
        """
        t = float(t)
        if t > self._typing_at:
            self._typing_at = t

    def typing_active(self, t: float) -> bool:
        """t 时刻算不算「正在写」（最后一次按键之后 TYPING_HOLD_S 秒内）。"""
        return float(t) - self._typing_at <= TYPING_HOLD_S

    def _typing_step(self, t: float) -> None:
        """打字凝视的逐帧决策：该把视线落到输入框时就落，落定了就不动。"""
        if not self.typing_active(t):
            return
        if t - self._cursor_active_t <= LOOK_HOLD_S:
            return  # 手刚指过（那一眼还没过期）：光标优先，打字垫底
        last = self._gaze[-1]
        if last.t <= t and (last.x, last.y) == (0, TYPING_GAZE_Y):
            return  # 已经看着输入框：不重挂指令，让缓动自己走完
        if t < self._look_retarget_t + TYPING_RETARGET_MIN_S:
            return  # 刚转过视：隔一小会再轮到打字（和光标共用一条限速）
        self._look_retarget_t = t
        self._retarget_gaze(t, 0, TYPING_GAZE_Y)

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

    # ── 醒来的哈欠：「睡醒了先伸个懒腰」──────────────

    def yawn(self, at: float) -> None:
        """安排一次哈欠（at 时刻开始）—— 窗口在它从睡着变回醒着那一刻调用。

        再来一次就重新从撑起来开始；实际时序里两次醒来隔着几小时，
        这条只是把语义写死、让测试能钉住。
        """
        self._yawn_at = float(at)

    # ── 无聊的叹气：「没人理的时候，隔一会儿叹一口气」────────

    def sigh(self, at: float) -> None:
        """安排一次叹气（at 时刻开始）—— 排期器（note_bored）与测试走同一条。

        再来一次就重新从沉下去开始（实际时序里两次叹气隔着几十秒，
        这条只是把语义写死、让测试能钉住）。
        """
        self._sigh_at = float(at)

    def note_bored(self, t: float, bored: bool) -> None:
        """喂一次「现在无聊不无聊」—— 窗口每秒调一次（和驱力钟同一拍）。

        无聊时会**隔一会儿叹一口气**，间隔在 SIGH_MIN_GAP~SIGH_MAX_GAP 秒
        之间随机 —— 均匀得像节拍器就不像活物了。
        - 刚进入无聊：先等一个间隔再叹第一口（立刻叹 = 反射，不是情绪）；
        - 一直无聊：叹完接着排下一口；
        - 不无聊了：排期清掉（**正在叹的那口让它叹完** —— 半路掐掉像噎住）。
        """
        if not bored:
            self._sigh_next_at = None
            return
        if self._sigh_next_at is None:
            self._sigh_next_at = t + self._rng.uniform(SIGH_MIN_GAP, SIGH_MAX_GAP)
            return
        if t >= self._sigh_next_at:
            self.sigh(t)
            self._sigh_next_at = t + self._rng.uniform(SIGH_MIN_GAP, SIGH_MAX_GAP)

    # ── 困得点头：「困了的时候，一点一点地打盹」──────────

    def nod(self, at: float) -> None:
        """安排一次点头打盹（at 时刻开始）—— 排期器（note_sleepy）与测试走同一条。

        再来一次就重新从沉下去开始（实际时序里两下之间隔着几十秒，
        这条只是把语义写死、让测试能钉住）。
        """
        self._nod_at = float(at)

    def note_sleepy(self, t: float, sleepy: bool) -> None:
        """喂一次「现在困不困」—— 窗口每秒调一次（和驱力钟同一拍）。

        困了会**隔一会儿点一下头**（连着点 = 小鸡啄米），间隔在
        NOD_MIN_GAP~NOD_MAX_GAP 秒之间随机 —— 均匀得像节拍器就不像活物了。
        - 刚犯困：先等一个间隔再点第一下（立刻点 = 抽搐，不是打盹）；
        - 一直困：点完接着排下一下；
        - 不困了：排期清掉（**正在点的那下让它点完** —— 半路掐掉像被抽了一下）。
        """
        if not sleepy:
            self._nod_next_at = None
            return
        if self._nod_next_at is None:
            self._nod_next_at = t + self._rng.uniform(NOD_MIN_GAP, NOD_MAX_GAP)
            return
        if t >= self._nod_next_at:
            self.nod(t)
            self._nod_next_at = t + self._rng.uniform(NOD_MIN_GAP, NOD_MAX_GAP)

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
        self._yawn_at = -99.0  # 哈欠同理：拨过时间线，旧的那一次不作数
        self._sigh_at = -99.0  # 叹气同理：旧的那口不作数
        self._sigh_next_at = None  # 排期也是（下一次 note_bored 会重排）
        self._nod_at = -99.0  # 点头同理：拨过时间线，旧的那下不作数
        self._nod_next_at = None  # 排期也是（下一次 note_sleepy 会重排）
        self._typing_at = float("-inf")  # 打字同理：拨过时间线，旧的「在写」不作数
        self._typing_was_active = False  # 暂停标记同理
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

        # 醒来的哈欠：抻起来 / 眯上眼两条曲线。睡着时不做（calm 冻结一切）。
        yawn_spent = t - self._yawn_at
        yawn = 0.0 if calm else yawn_amount(yawn_spent)
        squint = 0.0 if calm else yawn_squint(yawn_spent)
        sigh = 0.0 if calm else sigh_amount(t - self._sigh_at)
        nod = 0.0 if calm else nod_amount(t - self._nod_at)

        squash = 1.0
        if not calm:  # 睡着时闭着眼，不该再眨
            for start, dur in self._blinks:
                if start <= t <= start + dur:
                    squash = min(
                        squash, 1.0 - (1.0 - BLINK_MIN_SQUASH) * _envelope((t - start) / dur)
                    )
        if squint > 0.0:  # 哈欠里的眯眼：和眨眼取更眯的那个（同一时刻也画得对）
            squash = min(squash, 1.0 - (1.0 - YAWN_SQUINT_MIN) * squint)
        if sigh > 0.0:  # 叹气的瘪：轻轻压一下 —— 看得见，又不会读成眨眼
            squash = min(squash, 1.0 - (1.0 - SIGH_DEFLATE) * sigh)
        if nod > 0.0:  # 点头的闭眼：沉到底时压到一半 —— 眼皮快合上
            squash = min(squash, 1.0 - (1.0 - NOD_SQUINT_MIN) * nod)

        amp = CALM_FACTOR if calm else 1.0
        dy = round(amp * BREATH_AMPLITUDE * math.sin(2 * math.pi * t / BREATH_PERIOD))
        if yawn > 0.0:
            dy -= round(YAWN_LIFT_PX * yawn)  # 伸懒腰：整脸往上顶一点（负 = 上）
        if sigh > 0.0:
            dy += round(SIGH_SINK_PX * sigh)  # 叹气：整脸往下沉一点（正 = 下）
        if nod > 0.0:
            dy += round(NOD_SINK_PX * nod)  # 点头：整脸往下沉一点（正 = 下）
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
            self._typing_step(t)
            gx, gy = self._gaze_pos(t)

        # 好奇：越靠左右边缘，脸越"探"（只拉高，不拉宽）
        edge = min(1.0, abs(gx) / GAZE_MAX_X)
        stretch = (1.0 + CURIOSITY_STRETCH * edge * edge) * (1.0 + YAWN_STRETCH * yawn)

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
    "NOD_HOLD_S",
    "NOD_MAX_GAP",
    "NOD_MIN_GAP",
    "NOD_SAG_S",
    "NOD_SINK_PX",
    "NOD_SNAP_S",
    "NOD_SQUINT_MIN",
    "POP_DURATION",
    "SIGH_DEFLATE",
    "SIGH_HOLD_S",
    "SIGH_MAX_GAP",
    "SIGH_MIN_GAP",
    "SIGH_RISE_S",
    "SIGH_SINK_PX",
    "SIGH_SINK_S",
    "SWAY_AMPLITUDE",
    "TALK_BOB_Y",
    "TALK_EASE_IN",
    "TALK_EASE_OUT",
    "TALK_PERIOD",
    "TALK_SQUASH",
    "TYPING_GAZE_Y",
    "TYPING_HOLD_S",
    "TYPING_RETARGET_MIN_S",
    "YAWN_HOLD_S",
    "YAWN_LIFT_PX",
    "YAWN_RISE_S",
    "YAWN_SETTLE_S",
    "YAWN_SQUINT_DELAY_S",
    "YAWN_SQUINT_FALL_S",
    "YAWN_SQUINT_MIN",
    "YAWN_SQUINT_RISE_S",
    "YAWN_STRETCH",
    "Animator",
    "Frame",
    "carry_target",
    "cursor_target",
    "nod_amount",
    "nod_total",
    "sigh_amount",
    "sigh_total",
    "yawn_amount",
    "yawn_squint",
    "yawn_total",
]
