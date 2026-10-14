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

11. **思考凝视**（自选小步·第十三次）：「想事情的时候，抬起头来」——
    你按下发送、它开始想（思考点转起来）的时候，视线抬到上方（像人在回忆 /
    盘算）；想完了把视线收回来（看回正中）。发送那一刻「看着你写」的阶段也
    随之结束（end_typing）。优先级垫底：被叫到先看你（光标 / 打字），看够了
    接着想；睡着 / 动画关都不做。

12. **摸摸头**（自选小步·第十四次）：「手停在脸上的时候，眯起眼呼噜一下」——
    桌面宠物的「手」就是鼠标：光标**停进脸框**够久 = 在摸它；停够（PET_DWELL_S）
    就慢慢眯起眼、配一层轻轻的呼噜起伏（比呼吸快的一上一下）；手拿开再慢慢
    睁开。路过不算（停够才算）；睡着 / 动画关 / 被搬着都不做。

13. **打个喷嚏**（自选小步·第十五次）：「偶尔呛一下」—— 老机器里的小家伙
    也会呛着：没来由地打个喷嚏 —— 脸先皱起来（压到七成）、猛地一缩闭上眼
    （压到 12%）、往上窜一点再慢慢松回来。它是**反射不是态度**：不躲着
    交互（跟人说着话照样打）；躲的只有睡着 / 被拎着 / 动画关。

14. **哼小曲**（自选小步·第十六次）：「心情好的时候，摇头晃脑哼两句」——
    心情到「很好」（和状态行同一档标签）的时候，隔一会儿轻轻晃两下脑袋
    （左右各摆 ±4px、约 1.7 秒一拍、晃 3 下），右上角冒一个像素小音符
    （和睡着的 Z 同一格位置、同一套画法）。它是第一条**只挂心情**的
    自发动作（叹气挂无聊、点头挂犯困、喷嚏是纯反射 —— 这条是「高兴」）；
    睡着 / 被拎着 / 正在看你写字的时候不哼。

15. **歪头**（自选小步·第十七次）：「被戳了，歪着脑袋看你（唔？）」——
    戳一戳的回应：脑袋绕脸中心轻转 ±5 度、停一小会、再直回来；方向一次
    一换（不掷随机数）。它是第一条**旋转**形变。

16. **好奇歪头**（自选小步·第十八次）：「你写的时候，歪着脑袋看你在写什么」——
    把第 15 条的旋转接进第 11 条的注视：写起来之后隔一会儿好奇地歪一下
    脑袋（第一下 1.5~3 秒内就来），停半秒再直回去继续看你写；停手 / 发送
    后排期作废，下一段重头起算。排期走它自己的随机流 —— 不占主随机流。

17. **入睡的一下**（自选小步·第十九次）：「撑不住了」—— 醒着→睡着的那一刻
    不再是瞬移：整脸慢慢往下沉、眼睛合上、屏一会儿（睡实了）、再松回睡姿，
    2.6 秒演完；它**就是进入 calm 的那一下**（只在睡着这一瞬演，醒着没有）。
    它是「睡着」的入口 —— 和哈欠（「醒来」的出口）对称。

18. **上电环顾**（自选小步·第二十次）：「自检播完，先看一圈」—— 开机自检
    交班那一刻先站定一下，抬着头把左右两边各看一眼、再回正中，然后才开始
    随机漂移；三条固定凝视指令，复用既有凝视盒与缓动（不掷随机数）；
    点一下跳过也看。

19. **欢迎回来**（自选小步·第二十一次）：「你回来啦」—— 光标静够久（= 你离开）
    之后第一次动 = 你回来：整脸抬起来一点（精神一振）、顺着光标看你一眼，
    再慢慢放回去；睡着时不排（醒来那条走哈欠），动画关也不做。

20. **蔫一会儿**（自选小步·第二十三次）：「心情有点蔫的时候，悄悄往下垂一垂」——
    哼小曲那条只讲「高兴」；这条讲对着的另一头：心情落进「有点蔫」的档里，
    隔一会儿没精神地往下垂一垂（头沉下去、眼皮也耷拉一点），停一段、自己
    再慢慢缓起来。它是第二条**只挂心情**的动作（和哼小曲一正一反）—— 慢、
    深、停得久：读的不是一口气，是一段情绪。

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

# 思考凝视（自选小步·第十三次）——「想事情的时候，抬起头来」：你按下发送、它开始
# 想（思考点转起来）的时候，视线抬到上方 —— 像人回忆 / 盘算时那样；想完了把视线
# 收回来（看回正中 = 看回你）。发送那一刻「在写」的阶段就结束了（end_typing）——
# 它开始想你写的东西，而不是继续盯着输入框。
# 优先级垫底（光标 > 打字 > 思考）：被叫到先看你，看够 / 你停手之后接着想。
THINKING_RETARGET_MIN_S = 0.35  # 想 / 收两次转视的最小间隔（秒；和光标/打字共用一条限速）
THINKING_GAZE_Y = -GAZE_MAX_Y  # 抬头的落点：纵向拉满凝视盒（负 = 看上方），对称于打字的「看正下方」

# ── 睡梦抽动：「睡着的时候，偶尔轻轻抽一下」────────────
# 睡着不只是"不动 + 一个 Z"：真的活物睡着会做梦 —— 偶尔轻轻抽一下（一激灵）。
# 这是第一条**只在睡着时**出现的通道；醒着的时候它一眼都不许有（只加不改）。
TWITCH_MIN_GAP = 25.0  # 两次抽动之间最短（秒）
TWITCH_MAX_GAP = 70.0  # 最长；两者之间随机 —— 别像节拍器
TWITCH_JOLT_S = 0.07  # 抽上去用时（秒）—— 快：肌肉一激灵
TWITCH_HOLD_S = 0.05  # 顶住的一瞬（秒）—— 让眼睛来得及看见
TWITCH_SETTLE_S = 0.28  # 松回来用时（秒）—— 比抽上去慢得多，像又睡过去了
TWITCH_SHIFT_PX = 3  # 横向一激灵的幅度（设备像素）—— 方向一左一右交替
TWITCH_DEFLATE = 0.91  # 抽到顶时纵向压到 91% —— 全身一缩

# ── 摸摸头：「手停在脸上的时候，眯起眼呼噜一下」────────────
# 桌面宠物的「手」就是鼠标：光标**停进脸框**、停够 PET_DWELL_S 秒 = 在摸它。
# 路过 / 划过去都不算 —— 手停下来才有「被摸」的意思。摸住就慢慢眯起眼（舒服）、
# 配一层轻轻的「呼噜」起伏；手拿开再慢慢睁开。和光标凝视的分工：光标凝视管
# 「手在动 → 看你一眼」；摸摸头管「手停在你脸上 → 眯起眼」。睡着 / 动画关 /
# 被搬着都不做（那时的手不是摸的手）。
PET_DWELL_S = 0.6  # 光标在脸上停这么久才算「在摸」——路过 / 划过去不算
PET_EASE_IN_S = 0.35  # 眯起来用时（秒）—— 停够之后慢慢眯，不是啪地合上
PET_EASE_OUT_S = 0.55  # 手拿开、慢慢睁开用时（秒）—— 比眯起来慢一点，像舍不得
PET_SQUINT_MIN = 0.55  # 眯到 55%（眨眼 14%、哈欠 30%、点头 50% —— 这是「舒服」，浅一点）
PET_PURR_PERIOD = 0.9  # 呼噜的一拍（秒）—— 比呼吸（4.5s）快、比说话（0.44s）慢
PET_PURR_PX = 2  # 呼噜的起伏（±设备像素）—— 和呼吸同幅，但节奏快

# ── 打个喷嚏：「偶尔呛一下的小家伙（哈啾）」────────────
# 第一条**没有前置情绪**的自发动作（不挂驱力 —— 谁都有没来由打个喷嚏的
# 时候）：先皱起脸（「哈——」的酝酿）、猛地一缩闭上眼并往上窜一点
# （「啾！」）、再慢慢松回来。它也是第一条**不躲着交互**的（喷嚏是反射
# 不是态度 —— 跟人说着话照样打）。躲的只有：睡着（梦里的抽动是另一条
# 通道）、被拎着的手上（搬运凝视在管那段）、动画关。
SNEEZE_MIN_GAP = 90.0  # 两次喷嚏之间最短（秒）
SNEEZE_MAX_GAP = 240.0  # 最长；两者之间随机 —— 别像节拍器
SNEEZE_WINDUP_S = 0.22  # 「哈——」：皱起脸、往上抬一点用时（秒）
SNEEZE_WINDUP = 0.35  # 酝酿段顶到满量的多少 —— 看得见的预兆，但不抢戏
SNEEZE_BURST_S = 0.07  # 「啾！」：闭眼一缩那一瞬用时（秒）—— 短，才是冲击感
SNEEZE_HOLD_S = 0.05  # 顶住的一瞬（秒）—— 让眼睛来得及看见
SNEEZE_SETTLE_S = 0.30  # 松回来用时（秒）—— 打完总要缓一下
SNEEZE_SQUINT_MIN = 0.12  # 爆发时压到 12%（眨眼 14% —— 喷嚏还要紧一点：用力闭）
SNEEZE_LIFT_PX = 3  # 爆发时整脸往上窜几像素（设备像素）
SNEEZE_JERK_PX = 2  # 爆发时横向一哆嗦的幅度（方向一次一换，不掷随机数）

# ── 哼小曲：「心情好的时候，摇头晃脑哼两句」────────────
# 第一条**只挂心情**的自发动作：心情到「很好」的时候，隔一会儿轻轻晃两下
# 脑袋（左右各摆 ±HUM_ROCK_PX、约 1.7 秒一拍、晃 HUM_ROCK_CYCLES 下），
# 右上角冒一个像素小音符（和睡着的 Z 同一套画法）。别的动作都在讲「状态」
# （无聊 / 困 / 睡着 / 醒来），这条讲「高兴」—— 状态要能被眼睛读出来，
# 好心情也一样。睡着 / 被拎着 / 正在看你写字的时候不哼。
HUM_MIN_GAP = 50.0  # 两次哼歌之间最短（秒）
HUM_MAX_GAP = 140.0  # 最长；两者之间随机 —— 别像节拍器
HUM_EASE_IN_S = 0.30  # 起手：包络从 0 涨到满、轻轻摆进去用时（秒）
HUM_ROCK_PERIOD = 0.60  # 摇晃的一拍（秒）—— 约 1.7 拍每秒，比呼吸快、比说话慢
HUM_ROCK_CYCLES = 3  # 满幅摇晃几个整周期 —— 晃三下就够，再多像甩头
HUM_EASE_OUT_S = 0.45  # 收尾：从当前摆动缓出去用时（秒）—— 不突然停
HUM_ROCK_PX = 4  # 左右摇摆幅度（±设备像素）—— 比呼吸 / 微动（±2）明显一档
HUM_NOTE_RISE_PX = 8  # 右上角小音符整个行程升起几像素（和 Z 的 9 一个量级）
HUM_ROCK_S = HUM_ROCK_PERIOD * HUM_ROCK_CYCLES  # 满幅摇晃的总时长（秒）—— 由「一拍 × 几下」推导

# ── 歪头：「被戳了，歪着脑袋看你（唔？）」────────────
# 戳一戳是最常用的互动，却一直没有身体语言（光标 / 打字 / 摸摸头 / 搬运全都有）。
# 歪头是最经典的「回应」姿态：被戳一下，脑袋一歪、看你一下，再直回来。
# 它是第一条**旋转**形变（此前全是平移 / 缩放）—— 5° 在宽脸上两角高差约 50px，
# 一眼读得出来；方向一次一换（不掷随机数 —— 理由同抽动 / 喷嚏）。
TILT_MAX_DEG = 5.0  # 歪到多少度（±）：读得清楚，又不像要把脑袋倒过来
TILT_RISE_S = 0.25  # 歪过去用时（秒）—— 轻快：是「唔？」不是「沉思」
TILT_HOLD_S = 0.55  # 歪着看你一下（秒）—— 停得够长，才看得出「在看你」
TILT_FALL_S = 0.45  # 直回来用时（秒）—— 比歪过去慢一点，像看完才收

# ── 好奇歪头：「你写的时候，歪着脑袋看你在写什么」────────────
# 歪头（第十七次）先挂上戳一戳 ——「被戳了（唔？）」；这一条把它接进
# 「看着你写」（第十一次）的整段：写起来了就隔一会儿好奇地歪一下脑袋，
# 停一下再直回去接着看你写。旋转语汇（±TILT_MAX_DEG 度、绕脸中心、
# 最近邻取样）半点新东西不加；几何预算也沿用（旋转已经折进 FACE_REGION_PAD）。
# 排期抽数走**自己的随机流**（_rng_tilt）—— 写字的时刻表由外部事件驱动，
# 不该把眨眼 / 凝视的主随机流带偏（写完字之后的世界要和没写过一样；
# 理由与判据见 tests/test_typing_tilt.py 的排期随机流用例）。
TYPING_TILT_FIRST_MIN_S = 1.5  # 写起来之后：第一下最短等多久（秒）—— 先看清你在写
TYPING_TILT_FIRST_MAX_S = 3.0  # 最长；两者之间随机 —— 别一敲字就弹
TYPING_TILT_MIN_GAP = 12.0  # 一直写：两下之间最短（秒）
TYPING_TILT_MAX_GAP = 24.0  # 最长；两者之间随机 —— 别像节拍器

# ── 入睡的一下：「撑不住了（头一沉，睡过去）」────────────
# 醒来有哈欠（第八次）、睡着有 Z 和抽动（第七 / 十二次）—— 唯独「真的睡过去」
# 那一下此前是瞬移：睡脸直接切过来（一次交叉淡化），没有过程。这一条把它补上：
# 撑不住 → 整脸慢慢往下沉、眼合上 → 屏一会儿（睡实了）→ 慢慢松回睡姿。
# 它只在「醒着 → 睡着」那一刻由窗口安排一次，**就是进入 calm 的那一下** ——
# 和抽动同一套规矩：calm 里运行，醒着一眼都不许有（calm 定生死）。
# 至此昼夜动作链闭合：困（点头）→ 睡着（这一下）→ 睡相（Z / 抽动）→ 醒（哈欠）。
DOZEOFF_SINK_S = 1.1  # 头沉下去用时（秒）—— 全家族里最慢的「塌」：撑不住了，不是点头
DOZEOFF_HOLD_S = 0.6  # 沉到底屏住的一小段（秒）—— 睡实了的那一瞬（比点头的 0.3 长）
DOZEOFF_SETTLE_S = 0.9  # 松回睡姿用时（秒）—— 放弃式的放松，比沉下去干脆
DOZEOFF_SINK_PX = 6  # 整脸往下沉几像素（比点头的 5 更深 —— 这一下是真的睡过去）
DOZEOFF_SQUINT_MIN = 0.45  # 沉到底压到 45%（点头 50% —— 同一族、再合一点：眼皮是真落下了）

# ── 上电环顾：「自检播完，先看一圈」────────────
# 开机自检（终端行滚完、画面淡入）之后，脸不是当场就开始发呆乱看：先站定一下，
# 抬着头把左右两边各看一眼、再回正中 —— 「刚上电，看看自己在哪儿」。它是凝视
# 时间表里的三条**固定目标**：复用既有凝视盒与缓动，半点新几何不加（横向扫到
# 满幅，好奇拉高自然到满 —— 探着头看）；也不掷随机数，同种子孪生对账靠它。
SURVEY_LEAD_S = 0.35  # 交班之后先站定多久才看第一眼（秒）—— 画面刚稳住
SURVEY_DWELL_S = 1.4  # 每一边停留到下一次转向（秒）；含 0.55 秒缓动，看定约占 0.85 秒
SURVEY_LIFT_PX = 2  # 两侧都比正中略抬眼（设备像素；负号方向 = 竖着往上）
SURVEY_TARGETS: tuple[tuple[int, int], ...] = (
    (-GAZE_MAX_X, -SURVEY_LIFT_PX),  # 先看左边（横到满幅，探头）
    (GAZE_MAX_X, -SURVEY_LIFT_PX),  # 再看右边
    (0, 0),  # 回正中 —— 之后交给随机漂移
)

# ── 欢迎回来：「你回来啦」────────────
# 光标（= 你能碰到的唯一全局信号）静够 WELCOME_AWAY_S 没人动 = 你离开了；
# 再动起来的第一下 = 你回来了 —— 它把脑袋抬起来（精神一振）、顺着光标看
# 你一眼，再慢慢放回去。它补的是「离开一会儿再回来」这条缝：长离开它是
# 睡着的（醒来走哈欠），短离开此前什么反应也没有 —— 你回来它都不知道，
# 那不像活物，像一台不在家的机器。宁可错迎（看电影四十分钟再动鼠标，它
# 也会欢迎一下 —— 那一下本来也读得通），不可漏迎。
WELCOME_AWAY_S = (
    600.0  # 光标静这么久没人碰 = 你走了（秒）—— 和 care.ACTIVE_WINDOW_MINUTES 同一把尺子
)
WELCOME_MOVE_MIN = 4  # 光标累计位移至少这么多设备像素算「有人在用鼠标」（贴手小抖不算）
WELCOME_RISE_S = 0.18  # 精神一振：抬起来用时（秒）—— 快：是「一下注意到」
WELCOME_HOLD_S = 0.30  # 顶着的一小段（秒）—— 让眼睛看清「它看见你了」
WELCOME_SETTLE_S = 0.55  # 放回去用时（秒）—— 比抬起来慢，劲头落下要有尾巴
WELCOME_LIFT_PX = 5  # 整脸往上抬几像素（负方向 = 上）—— 和叹气 / 点头的下沉同量级
WELCOME_STRETCH = 0.06  # 顺带纵向拉高 6%（和好奇同一个量级）——「精神起来」的那一下

# ── 蔫一会儿：「心情有点蔫的时候，悄悄往下垂一垂」────────────
# 哼小曲（第十六次）讲「高兴」；这条讲对着的另一头 —— 心情落进「有点蔫」
# 的档里（和心情标签同一档：低于 -0.05），隔一会儿没精神地往下垂一垂（头
# 沉下去、眼皮也耷拉一点），停一段、自己再慢慢缓起来。它是第二条**只挂
# 心情**的动作，和哼小曲一正一反；也是「会动的那一段」里把蔫演出来的那条：
# 再往下（低落档）它会直接呆住不动（calm 定格）—— 那是更重的状态，不叠动作。
DROOP_MIN_GAP = 60.0  # 两下之间最短（秒）
DROOP_MAX_GAP = 150.0  # 最长；两者之间随机 —— 别像节拍器
DROOP_SINK_S = 1.20  # 垂下去用时（秒）—— 慢：是「没精神」，不是「困」
DROOP_HOLD_S = 1.60  # 垂到底停住的一整段（秒）—— 最长的「屏住」：情绪不是一口气
DROOP_RISE_S = 1.10  # 缓起来用时（秒）—— 自己缓过来：不猛，也不拖
DROOP_SINK_PX = 6  # 整脸往下垂几像素：比叹气（4）深，和入睡的一下（6）同量级
# 蔫过头：蔫久了，自己缩一小圈·第二十五条的自选小步。
# 第二十四条补的是「垂」的那一下；这一条补垂与垂之间的那段。
# 心情从早到晚都是蔫的，光靠每 1 到 2 分钟垂一下，两个动作之间的它看起来
# 又正常了（动作是瞬时的，底色不是）。所以：心情在「有点蔫」这条线以下时，
# 让它的静止姿态自己收一小圈——不是变矮，是整个人小一号。
#
# 三个「不是」，免得后来的人改错方向：
# - 不是 squash 那种动态压扁：squash 只在动作里动；这一条改的是静止基线
#   （见 mood_shrink——空闲摆着的那张脸按心情缩一档）；
# - 不是第三个动作：不排期、不占随机流、不掷骰子——它一直在（只要
#   心情在线下面），像呼吸和微动一样属于底噪；
# - 不越界：收的是脸自己（在脸框内缩），不是整块屏幕——缩完一圈
#   仍然落在 FACE_REGION_PAD 那条几何守卫里。
MOOD_SHRINK_BELOW = -0.05
# 低于这条（= 心情标签的「有点蔫」）才开始收——和垂同一档，不另立一条线
MOOD_SHRINK_MIN = 0.94
# 收到底 = 缩到 94%（6% 是看得出的最小量级：再小没人看得见，再大就变形了）
MOOD_SHRINK_FLOOR = -0.45
# 心情的下限（mood.FLOOR 同一把尺）：到这里就收到底，再低也只是更蔫
DROOP_SQUINT_MIN = 0.72  # 垂到底压到 72%（眼皮轻轻耷拉着）—— 比点头 50% 浅：没到犯困那份上

# 绷住（第二十六次）
# 心情差到下面这条以下才开始绷，到心情下限绷到底
HUNCH_ABS_BELOW = -0.20  # 到「低落」档以下才绷（下限 -0.45）；上面那段是缓坡
HUNCH_RAMP = 0.25  # 上面那条线的「软硬」：小于它按比例缓入（不是开关）
HUNCH_SQUINT_PX = 2  # 横向也收一点（缩一圈不是一个方向的事）
HUNCH_SQUASH_MIN = 0.97  # 纵向压到 97%（和缩同一量级：读成「整个人小一号」）
HUNCH_STRETCH_ABS = 0.46  # 把好奇拉高的增益按这个量收掉：缩的时候不许再被拉高抵回去
HUNCH_MIN_GAP = 90.0  # 两次绷住之间最短（秒）
HUNCH_MAX_GAP = 210.0  # 最长；两者之间随机 —— 别像节拍器（宁可更稀：这是最重的一条）
# 几何守卫用（test_yawn）
HUNCH_SLACK_X = 2  # 几何守卫的横向净量（缩是收益，这是保守写法）

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
    tilt: float = 0.0  # 歪头：绕脸中心旋转的角度（度；正负 = 两个方向）
    shrink: float = 1.0  # 缩小起来：静止基线缩放（1.0 = 不收）

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
            and self.tilt == 0.0
            and self.shrink == 1.0
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


def twitch_amount(t_spent: float) -> float:
    """睡梦抽动的形状（0 → 1 → 0）：猛地一激灵 → 顶住一瞬 → 慢慢松回去。

    纯函数：三段的时间线在测试里逐点钉死 —— 抽上去比松回来快得多，
    快慢对比就是「一激灵」的读法；这是「睡着」这个状态第一次出现**专属**动作。
    `t_spent` = 距离这次抽动开始过了多久；负数 = 还没开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < TWITCH_JOLT_S:
        return _smooth01(t_spent / TWITCH_JOLT_S)
    if t_spent < TWITCH_JOLT_S + TWITCH_HOLD_S:
        return 1.0
    k = t_spent - TWITCH_JOLT_S - TWITCH_HOLD_S
    if k < TWITCH_SETTLE_S:
        return 1.0 - _smooth01(k / TWITCH_SETTLE_S)
    return 0.0


def twitch_total() -> float:
    """一次睡梦抽动从头到尾的时长（秒）。"""
    return TWITCH_JOLT_S + TWITCH_HOLD_S + TWITCH_SETTLE_S


def sneeze_amount(t_spent: float) -> float:
    """喷嚏的形状（0 → 1 → 0）：皱脸酝酿 → 骤然爆发 → 顶住 → 松回来。

    纯函数：四段的时间线在测试里逐点钉死 —— 酝酿段慢（「哈——」）、爆发段
    短（「啾！」），快慢对比就是「喷嚏」的读法；它不挂任何驱力（第一条没有
    前置情绪的自发动作）。`t_spent` = 距离这次喷嚏开始过了多久；负数 = 还没
    开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < SNEEZE_WINDUP_S:
        return SNEEZE_WINDUP * _smooth01(t_spent / SNEEZE_WINDUP_S)
    k = t_spent - SNEEZE_WINDUP_S
    if k < SNEEZE_BURST_S:
        return SNEEZE_WINDUP + (1.0 - SNEEZE_WINDUP) * _smooth01(k / SNEEZE_BURST_S)
    k -= SNEEZE_BURST_S
    if k < SNEEZE_HOLD_S:
        return 1.0
    k -= SNEEZE_HOLD_S
    if k < SNEEZE_SETTLE_S:
        return 1.0 - _smooth01(k / SNEEZE_SETTLE_S)
    return 0.0


def sneeze_total() -> float:
    """一次喷嚏从头到尾的时长（秒）。"""
    return SNEEZE_WINDUP_S + SNEEZE_BURST_S + SNEEZE_HOLD_S + SNEEZE_SETTLE_S


def hum_amount(t_spent: float) -> float:
    """哼小曲的包络（0 → 1 → 0）：起手 → 满幅摇晃 → 收尾 —— 三段拼一条时间线。

    纯函数：三段的时间线在测试里逐点钉死。摇晃本身（那条左右摆的正弦）在
    frame_at 里 —— 这里只管「摆多大劲」的包络：缓着摆进去、满幅晃几拍、
    缓着停下来（不突然停）。`t_spent` = 距离这次开哼过了多久；负数 = 还没
    开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < HUM_EASE_IN_S:
        return _smooth01(t_spent / HUM_EASE_IN_S)
    if t_spent < HUM_EASE_IN_S + HUM_ROCK_S:
        return 1.0
    k = t_spent - HUM_EASE_IN_S - HUM_ROCK_S
    if k < HUM_EASE_OUT_S:
        return 1.0 - _smooth01(k / HUM_EASE_OUT_S)
    return 0.0


def hum_total() -> float:
    """一次哼小曲从头到尾的时长（秒）。"""
    return HUM_EASE_IN_S + HUM_ROCK_S + HUM_EASE_OUT_S


def tilt_amount(t_spent: float) -> float:
    """歪头的形状（0 → 1 → 0）：歪过去 → 歪着看你一下 → 直回来 —— 三段一条线。

    纯函数：三段时间线在测试里逐点钉死。歪过去（RISE）比直回来（FALL）快 ——
    轻快的一歪是「唔？」，慢吞吞地歪像犯困。`t_spent` = 距离这次歪头开始过了
    多久；负数 = 还没开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < TILT_RISE_S:
        return _smooth01(t_spent / TILT_RISE_S)
    k = t_spent - TILT_RISE_S
    if k < TILT_HOLD_S:
        return 1.0
    k -= TILT_HOLD_S
    if k < TILT_FALL_S:
        return 1.0 - _smooth01(k / TILT_FALL_S)
    return 0.0


def tilt_total() -> float:
    """一次歪头从头到尾的时长（秒）。"""
    return TILT_RISE_S + TILT_HOLD_S + TILT_FALL_S


def dozeoff_amount(t_spent: float) -> float:
    """入睡的一下的形状（0 → 1 → 0）：沉下去 → 屏住（睡实了）→ 松回睡姿。

    纯函数：三段的时间线在测试里逐点钉死。沉下去（慢慢塌）比松回来慢 ——
    撑是慢的、放弃是干脆的；两头精确为 0。它不掷随机数、不占随机流。这是「睡着」这个状态第一次
    有**入口**（此前只有哈欠管出口）。`t_spent` = 距离这一下开始过了多久；
    负数 = 还没开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < DOZEOFF_SINK_S:
        return _smooth01(t_spent / DOZEOFF_SINK_S)
    k = t_spent - DOZEOFF_SINK_S
    if k < DOZEOFF_HOLD_S:
        return 1.0
    k -= DOZEOFF_HOLD_S
    if k < DOZEOFF_SETTLE_S:
        return 1.0 - _smooth01(k / DOZEOFF_SETTLE_S)
    return 0.0


def dozeoff_total() -> float:
    """一次入睡的一下从头到尾的时长（秒）。"""
    return DOZEOFF_SINK_S + DOZEOFF_HOLD_S + DOZEOFF_SETTLE_S


def welcome_amount(t_spent: float) -> float:
    """「你回来啦」的形状（0 → 1 → 0）：抬起来 → 顶住 → 放回去 —— 三段一条线。

    纯函数：三段时间线在测试里逐点钉死。抬起来（RISE）比放回去（SETTLE）快 ——
    注意到你是一瞬间的事，放松下来有个尾巴；两头精确为 0。
    `t_spent` = 距离这次「回来」过了多久；负数 = 还没发生（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < WELCOME_RISE_S:
        return _smooth01(t_spent / WELCOME_RISE_S)
    if t_spent < WELCOME_RISE_S + WELCOME_HOLD_S:
        return 1.0
    k = t_spent - WELCOME_RISE_S - WELCOME_HOLD_S
    if k < WELCOME_SETTLE_S:
        return 1.0 - _smooth01(k / WELCOME_SETTLE_S)
    return 0.0


def welcome_total() -> float:
    """一次「欢迎回来」从头到尾的时长（秒）。"""
    return WELCOME_RISE_S + WELCOME_HOLD_S + WELCOME_SETTLE_S


def droop_amount(t_spent: float) -> float:
    """蔫一会儿的形状（0 → 1 → 0）：慢慢垂下去 → 蔫着停住 → 自己缓起来。

    纯函数：三段时间线在测试里逐点钉死 —— 全程都慢（垂 1.2 秒、停 1.6 秒、
    缓 1.1 秒）：一口气的读法是叹气，这一条读的是「一段情绪」。这是「心情」
    第二次变成看得见的动作（第一次是哼小曲 —— 一正一反）。
    `t_spent` = 距离这一下开始过了多久；负数 = 还没开始（取 0）。
    """
    if t_spent < 0:
        return 0.0
    if t_spent < DROOP_SINK_S:
        return _smooth01(t_spent / DROOP_SINK_S)
    if t_spent < DROOP_SINK_S + DROOP_HOLD_S:
        return 1.0
    k = t_spent - DROOP_SINK_S - DROOP_HOLD_S
    if k < DROOP_RISE_S:
        return 1.0 - _smooth01(k / DROOP_RISE_S)
    return 0.0


def droop_total() -> float:
    """一次「蔫一会儿」从头到尾的时长（秒）。"""
    return DROOP_SINK_S + DROOP_HOLD_S + DROOP_RISE_S


def hunch_ok(anim_on: bool, asleep: bool) -> bool:
    """绷住的闸门：动画关着不绷（关就关彻底）、睡着不绷。
    睡着不绷：睡相归 calm（睡脸自己会安静下来），再叠一层缩就是两个状态抢同一个位置。
    """
    return bool(anim_on) and not asleep


def hunch_amount(valence: float) -> float:
    """心情 -> 绷的量（0 = 没绷，1 = 绷到底）。
    和蔫过头共用同一条曲线（同一个刻度、同一个下限），但晚一步：心情到「低落」
    （HUNCH_ABS_BELOW）以下才开始绷，再往下走 HUNCH_RAMP 这一段就绷到底。
    上头那段（-0.05 到 -0.20）不绷：那时它只是「有点蔫」，缩一圈就够读了。
    """
    if valence > HUNCH_ABS_BELOW:
        return 0.0
    k = (HUNCH_ABS_BELOW - valence) / max(1e-9, HUNCH_RAMP)
    return max(0.0, min(1.0, k))


def mood_shrink_ok(anim_on: bool, asleep: bool) -> bool:
    """静止缩一圈的闸门。

    动画关着不收：没有时间轴，就没有静止姿态这回事（关就该关彻底）；
    睡着不收：睡相是另一个状态——睡脸自己会安静下来（calm 定格），
    再叠一层缩放就是两个状态抢同一个位置。
    """
    return bool(anim_on) and not asleep


def mood_shrink(valence: float) -> float:
    """心情 -> 静止基线的缩放（1.0 = 一点都不收）。

    和动作曲线（0 -> 1 -> 0 那种）不一样：这条不随时间动，只随心情动。
    它回答的是「蔫到这个份上，它整个人该收多少」。也是全表第一次出现
    「心情直接改静止姿态」：以前心情只决定摆哪张脸（mood.idle_expression），
    现在连那张脸多大也归它管。

    - 没到「有点蔫」（高于 MOOD_SHRINK_BELOW）：1.0（一点都不收）；
    - 从线到心情下限（MOOD_SHRINK_FLOOR）之间：线性收到 MOOD_SHRINK_MIN；
    - 比下限还低时不更收（mood 自己在下限截断）。
    """
    if valence > MOOD_SHRINK_BELOW:
        return 1.0
    span = MOOD_SHRINK_BELOW - MOOD_SHRINK_FLOOR
    frac = min(1.0, (MOOD_SHRINK_BELOW - valence) / span)
    return round(1.0 - (1.0 - MOOD_SHRINK_MIN) * frac, 6)


def survey_total() -> float:
    """上电环顾整段时长：第一条指令到回中缓动结束（秒）。"""
    return SURVEY_LEAD_S + (len(SURVEY_TARGETS) - 1) * SURVEY_DWELL_S + GAZE_EASE


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
    _rng_tilt: random.Random = field(init=False, repr=False)  # 好奇歪头的排期专属随机流
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
    # 好奇歪头：这一段的排期（None = 没在排）；抽数走 _rng_tilt（不占主随机流）
    _typing_tilt_next_at: float | None = field(default=None, repr=False)
    # 凝视漂移被「打字 / 想事情」暂停过（恢复的第一次补排程要把锚点拨到当下，见 _ensure_gaze）
    _pause_was_active: bool = field(default=False, repr=False)
    # 思考凝视：这一轮「想」的开始时刻（-99 = 没在想）；「收视线」待办；这轮抬没抬过头
    _thinking_at: float = field(default=-99.0, repr=False)
    _thinking_active: bool = field(default=False, repr=False)
    _thinking_break: bool = field(default=False, repr=False)
    _thinking_up: bool = field(default=False, repr=False)
    # 睡梦抽动：这一下的开始时刻（-99 = 没有）；下一次的排期（None = 没睡着、没在排）；
    # 方向一左一右交替（不掷随机数 —— 见 twitch()）
    _twitch_at: float = field(default=-99.0, repr=False)
    _twitch_next_at: float | None = field(default=None, repr=False)
    _twitch_dir: int = field(default=1, repr=False)
    # 摸摸头：光标在不在脸上（电平）、手停上来的时刻（dwell 锚点）、立没立起
    # 「在摸」、手拿开那一刻的档位与时刻（缓出从这里出发）
    _pet_on: bool = field(default=False, repr=False)
    _pet_on_since: float | None = field(default=None, repr=False)
    _pet_active: bool = field(default=False, repr=False)
    _pet_stop_t: float | None = field(default=None, repr=False)
    _pet_stop_level: float = field(default=0.0, repr=False)
    # 打个喷嚏：这一次的开始时刻（-99 = 没有）；下一次的排期（None = 没在排）；
    # 方向一次一换（不掷随机数 —— 理由同 twitch）
    _sneeze_at: float = field(default=-99.0, repr=False)
    _sneeze_next_at: float | None = field(default=None, repr=False)
    _sneeze_dir: int = field(default=1, repr=False)
    # 哼小曲：这一次的开始时刻（-99 = 没有）；下一次的排期（None = 心情没到、没在排）
    _hum_at: float = field(default=-99.0, repr=False)
    _hum_next_at: float | None = field(default=None, repr=False)
    # 歪头：这一次的开始时刻（-99 = 没有）；方向一次一换（不掷随机数）
    _tilt_at: float = field(default=-99.0, repr=False)
    _tilt_dir: int = field(default=1, repr=False)
    # 入睡的一下：「醒着 → 睡着」那一刻的开始时刻（-99 = 没有）；一段睡觉只有一次
    _dozeoff_at: float = field(default=-99.0, repr=False)
    # 欢迎回来：这一次的开始时刻（-99 = 没有）—— 一次「回来」演一次
    _welcome_at: float = field(default=-99.0, repr=False)
    # 蔫一会儿：这一下的开始时刻（-99 = 没有）；下一次的排期（None = 心情没落、没在排）
    _mood_shrink: float = field(default=1.0, repr=False)
    _mood_valence: float = field(default=0.15, repr=False)
    _droop_at: float = field(default=-99.0, repr=False)
    _droop_next_at: float | None = field(default=None, repr=False)
    # 绷住：这一下的开始时刻（-99 = 没有）；排期（None = 心情没到线，没在排）
    _hunch_at: float = field(default=-99.0, repr=False)
    _hunch_next_at: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._rng_tilt = random.Random(self.seed)
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
        rebase = self._pause_was_active  # 刚被打字 / 想事情暂停过：这次补排程把锚点拨到当下
        while self._gaze[-1].t < t + 1.0:
            if self.typing_active(t) or self.thinking_active(t):
                self._pause_was_active = True
                return  # 打字 / 想事情中：漂移暂停 —— 别把「看别处」排进这段时间
            last = self._gaze[-1]
            # 正常顺排：从 last.t 往后。**唯一例外**是「暂停刚结束」的第一次：暂停期间
            # 不排程，时间表在它身上空了一段；要是还从暂停前顺排，会一次塞进好几条
            # 落在过去的指令，恢复的第一帧就往「早就该在的位置」跳一下。
            # 锚点取 max(last.t, t)：恢复后从当下重排（常规制造缺口的只有「打字 /
            # 思考」这两条暂停 —— 别的路径全部保持原行为，金色基线一个字节都不许动）。
            anchor = max(last.t, t) if rebase else last.t
            self._gaze.append(
                self._new_gaze(
                    anchor + self._rng.uniform(GAZE_MIN_GAP, GAZE_MAX_GAP), last.x, last.y
                )
            )
            rebase = False  # 只拨这一次，后面回到正常顺排
        self._pause_was_active = False

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

    # ── 上电环顾：「自检播完，先看一圈」──────────
    # 由窗口在 boot 交班那一刻（_finish_boot）安排一次：站定、左一眼、右一眼、
    # 回正中。固定目标、不掷随机数；之后光标 / 打字 / 思考 / 搬运这些互动照常
    # 抢占 —— 它只是凝视时间表里的三条普通指令，不设防。

    def survey(self, at: float) -> None:
        """安排一次上电环顾（at 时刻站定，随后左、右、回中）。

        清掉更晚的旧目标、从**当前实际位置**起步 —— 和 _retarget_gaze 同一条
        纪律（中途改向不跳）；动画关 / 睡着了不该走到这里（窗口那层挡）。
        """
        t0 = float(at)
        kept = [g for g in self._gaze if g.t <= t0]
        self._gaze = kept or [_Gaze(t=0.0, x=0, y=0, fx=0, fy=0)]
        fx, fy = _pos_from(self._gaze, t0)
        for i, (x, y) in enumerate(SURVEY_TARGETS):
            self._gaze.append(
                _Gaze(t=t0 + SURVEY_LEAD_S + i * SURVEY_DWELL_S, x=x, y=y, fx=fx, fy=fy)
            )
            fx, fy = x, y

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
        """打字凝视的逐帧决策：该把视线落到输入框时就落，落定了就不动。

        写起来的这段里顺手排「好奇歪头」（见 _typing_tilt_step）：停手了
        排期作废、下一段重头起算；光标（手）优先时连它一起让位。
        """
        if not self.typing_active(t):
            self._typing_tilt_next_at = None  # 停手了：排期作废，下一段重头起算
            return
        if t - self._cursor_active_t <= LOOK_HOLD_S:
            return  # 手刚指过（那一眼还没过期）：光标优先，打字垫底 —— 歪头也让位
        self._typing_tilt_step(t)
        last = self._gaze[-1]
        if last.t <= t and (last.x, last.y) == (0, TYPING_GAZE_Y):
            return  # 已经看着输入框：不重挂指令，让缓动自己走完
        if t < self._look_retarget_t + TYPING_RETARGET_MIN_S:
            return  # 刚转过视：隔一小会再轮到打字（和光标共用一条限速）
        self._look_retarget_t = t
        self._retarget_gaze(t, 0, TYPING_GAZE_Y)

    def end_typing(self, t: float) -> None:
        """「写完了、发出去了」—— 输入框清空（发送）时窗口调一次。

        发送那一刻，看输入框的意义就结束了（那句话已经交出去、开始被想）：
        把保持窗口作废，视线交给下一个阶段（思考凝视 / 漂移）。只作废**当前**
        这一笔；之后你又敲字，note_typing 会重新开始窗口。
        """
        t = float(t)
        if t >= self._typing_at:  # 有账才销；乱序的老时间戳不作数
            self._typing_at = float("-inf")

    def _typing_tilt_step(self, t: float) -> None:
        """好奇歪头的排期：写起来了 → 隔一会儿歪一下（第一下稍早）。

        和叹气 / 点头 / 哼小曲同一套排期规矩：第一下先等一个短窗口（先看清
        你在写，不是一敲字就弹）；一直写就一直排，间隔随机 —— 别像节拍器；
        停手 / 让位时由 _typing_step 管排期的清与留。抽数走 `_rng_tilt`：
        这个时刻表由外部事件（你敲字）驱动，不许占用眨眼 / 凝视的主随机流。
        """
        if self._typing_tilt_next_at is None:
            self._typing_tilt_next_at = t + self._rng_tilt.uniform(
                TYPING_TILT_FIRST_MIN_S, TYPING_TILT_FIRST_MAX_S
            )
            return
        if t >= self._typing_tilt_next_at:
            self.tilt(t)
            self._typing_tilt_next_at = t + self._rng_tilt.uniform(
                TYPING_TILT_MIN_GAP, TYPING_TILT_MAX_GAP
            )

    # ── 思考凝视：「想事情的时候，抬起头来」────────────
    # 你按下发送、它开始想（思考点转起来）的时候，视线抬到上方 —— 像人在回忆 /
    # 盘算；想完了把视线收回来（看回正中 = 看回你）。优先级垫底（光标 > 打字 >
    # 思考）：被叫到先看你，看够 / 你停手之后接着想；睡着 / 动画关都不做。

    def note_thinking(self, t: float, active: bool) -> None:
        """喂一次「现在在不在想事情」—— 窗口每帧调一次（和 note_talk 同一拍）。

        电平信号：升沿记下「开始想」，降沿把「把视线收回来」记成待办；
        又在升沿上清掉没收完的半拍（想 → 停 → 又想：收尾别跨两轮）。
        喂进来的只是状态；看不看、收不收，决策全在 _thinking_step 里。
        """
        t = float(t)
        active = bool(active)
        if active and not self._thinking_active:
            self._thinking_at = t  # 升沿：这一轮「想」从此刻开始
            self._thinking_break = False
        elif not active and self._thinking_active:
            self._thinking_break = True  # 降沿：想完了 —— 轮到「收视线」
        self._thinking_active = active

    def thinking_active(self, t: float) -> bool:
        """t 时刻算不算「正在想事情」（思考点转着的那段）。"""
        return self._thinking_active

    def _thinking_step(self, t: float) -> None:
        """思考凝视的逐帧决策：想事情时抬头；想完了把视线收回来。

        优先级垫底：光标（手在指东西）与你正写的话都优先 —— 让位不抢戏。
        收视线只在「确实抬过头、且视线还在上方」时进行（被别的通道拿走就算了）。
        """
        if self.thinking_active(t):
            if t - self._cursor_active_t <= LOOK_HOLD_S:
                return  # 手刚指过：那一眼先看够（光标优先）
            if self.typing_active(t):
                return  # 你正在写：看输入框优先（说话的人比它自己想什么要紧）
            self._thinking_up = True
            last = self._gaze[-1]
            if last.t <= t and (last.x, last.y) == (0, THINKING_GAZE_Y):
                return  # 已经看着上方：不重挂指令
            if t < self._look_retarget_t + THINKING_RETARGET_MIN_S:
                return  # 刚转过视：隔一小会（和光标 / 打字共用一条限速）
            self._look_retarget_t = t
            self._retarget_gaze(t, 0, THINKING_GAZE_Y)
            return
        if not self._thinking_break:
            return
        # 想完了：把视线收回来（缓动回正中 —— 看回你）
        if not self._thinking_up:
            self._thinking_break = False
            return  # 这轮一直没轮到抬头（都在让位）：没什么可收的
        if _pos_from(self._gaze, t) != (0, THINKING_GAZE_Y):
            self._thinking_break = False
            self._thinking_up = False
            return  # 视线已经被别的通道挪走：不是我们说了算，别抢
        if t - self._cursor_active_t <= LOOK_HOLD_S:
            return  # 手刚指过：等它看够再收
        if self.typing_active(t):
            return  # 你又在写：让路（看输入框要紧）
        if t < self._look_retarget_t + THINKING_RETARGET_MIN_S:
            return  # 刚转过视：隔一小会
        self._thinking_break = False
        self._thinking_up = False
        self._look_retarget_t = t
        self._retarget_gaze(t, 0, 0)

    # ── 睡梦抽动：「睡着的时候，偶尔轻轻抽一下」────────────
    # 睡着不是"关掉了"：真的活物睡着会做梦 —— 偶尔轻轻抽一下（一激灵）。
    # 这是第一条**只在睡着时**出现的通道：醒着 = 一眼都不许有（calm 定生死）。
    # 方向一左一右交替（不掷随机数）：抽动本身很稀疏，看不出交替；而且不占
    # 随机流，同种子的孪生对比（素材）才拼得上。

    def twitch(self, at: float) -> None:
        """安排一次睡梦抽动（at 时刻开始）—— 排期器（note_asleep）与测试走同一条。

        再来一次就重新从抽上去开始（实际时序里两下之间隔着几十秒，
        这条只是把语义写死、让测试能钉住）。方向每抽一下换一边。
        """
        self._twitch_at = float(at)
        self._twitch_dir = -self._twitch_dir

    def note_asleep(self, t: float, asleep: bool) -> None:
        """喂一次「现在睡没睡」—— 窗口每秒调一次（和驱力钟同一拍）。

        睡着时会**隔一会儿轻轻抽一下**（做梦了），间隔在
        TWITCH_MIN_GAP~TWITCH_MAX_GAP 秒之间随机 —— 均匀得像节拍器就不像活物了。
        - 刚睡着：先等一个间隔再抽第一下（立刻抽 = 肌肉痉挛，不是做梦）；
        - 一直睡着：抽完接着排下一下；
        - 醒了：排期清掉，**正在抽的那下也不再画**（醒了就有醒来该做的事，
          比如哈欠；抽动是梦的一部分，梦跟着醒一起结束）。
        """
        if not asleep:
            self._twitch_next_at = None
            return
        if self._twitch_next_at is None:
            self._twitch_next_at = t + self._rng.uniform(TWITCH_MIN_GAP, TWITCH_MAX_GAP)
            return
        if t >= self._twitch_next_at:
            self.twitch(t)
            self._twitch_next_at = t + self._rng.uniform(TWITCH_MIN_GAP, TWITCH_MAX_GAP)

    # ── 摸摸头：「手停在脸上的时候，眯起眼呼噜一下」────────────
    # 桌面宠物的「手」就是鼠标：光标停进脸框够久 = 在摸它。停够才眯（路过不算）；
    # 手拿开从当前档位缓出（不是啪地睁回）。睡着 / 动画关 / 被搬着由窗口那层挡。

    def note_pet(self, t: float, on: bool) -> None:
        """喂一次「光标在不在脸上」—— 窗口每帧调一次。

        电平信号：升沿记下「手停上来了」的时刻（dwell 从此起算）；降沿结算
        这一轮 —— 眯着的从**当前档位**缓出去，手还没停够的什么都不留。
        """
        t = float(t)
        on = bool(on)
        if on:
            if not self._pet_on:
                self._pet_on = True
                self._pet_on_since = t
            return
        if not self._pet_on:
            return
        level = self._pet_env(t)  # 先算再关：缓出从这一刻的档位出发
        self._pet_on = False
        self._pet_active = False
        self._pet_stop_t = t
        self._pet_stop_level = level

    def _pet_step(self, t: float) -> None:
        """摸摸头的逐帧决策：手停够 PET_DWELL_S 秒，就把「在摸」立起来。"""
        if self._pet_on and not self._pet_active:
            since = self._pet_on_since
            if since is not None and t - since >= PET_DWELL_S:
                self._pet_active = True

    def _pet_env(self, t: float) -> float:
        """摸摸头的包络（0 到 1）：停够之后缓入；手拿开从当时档位缓出。"""
        if self._pet_on and self._pet_active:
            engaged = (self._pet_on_since or 0.0) + PET_DWELL_S
            return _smooth01((t - engaged) / PET_EASE_IN_S)
        if self._pet_stop_t is None or self._pet_stop_level <= 0.0:
            return 0.0
        fade = (t - self._pet_stop_t) / PET_EASE_OUT_S
        if fade >= 1.0:
            return 0.0
        return self._pet_stop_level * (1.0 - _smooth01(fade))

    # ── 打个喷嚏：「偶尔呛一下的小家伙（哈啾）」────────────
    # 第一条没有前置情绪的自发动作：不挂驱力（谁都有没来由打个喷嚏的时候）；
    # 也是第一条**不躲着交互**的（喷嚏是反射不是态度 —— 跟人说着话照样打）。
    # 睡着 / 被拎着 / 动画关由窗口那层挡。

    def sneeze(self, at: float) -> None:
        """安排一次喷嚏（at 时刻开始）—— 排期器（note_sneeze）与测试走同一条。

        再来一次就重新从皱脸开始（实际时序里两下之间隔着几分钟，
        这条只是把语义写死、让测试能钉住）。方向每打一下换一边。
        """
        self._sneeze_at = float(at)
        self._sneeze_dir = -self._sneeze_dir

    def note_sneeze(self, t: float, ok: bool) -> None:
        """喂一次「现在可以呛一下不」—— 窗口每秒调一次（和驱力钟同一拍）。

        会**隔一会儿没来由地打一个喷嚏**，间隔在 SNEEZE_MIN_GAP~SNEEZE_MAX_GAP
        秒之间随机 —— 均匀得像节拍器就不像活物了。和叹气 / 点头同一套排期：
        - 刚能打（醒来 / 被放下）：先等一个间隔再打第一个（立刻打 = 反射弧
          太短，像被掐了一下）；
        - 一直醒着：打完接着排下一个；
        - 不能打了（睡着 / 被拎起来）：排期清掉（**正在打的那个让它打完** ——
          喷嚏打一半掐掉像噎住）。
        """
        if not ok:
            self._sneeze_next_at = None
            return
        if self._sneeze_next_at is None:
            self._sneeze_next_at = t + self._rng.uniform(SNEEZE_MIN_GAP, SNEEZE_MAX_GAP)
            return
        if t >= self._sneeze_next_at:
            self.sneeze(t)
            self._sneeze_next_at = t + self._rng.uniform(SNEEZE_MIN_GAP, SNEEZE_MAX_GAP)

    # ── 哼小曲：「心情好的时候，摇头晃脑哼两句」────────────

    def hum(self, at: float) -> None:
        """安排一次哼小曲（at 时刻开始）—— 排期器（note_hum）与测试走同一条。

        再来一次就重新从起手开始（实际时序里两段之间隔着一两分钟，
        这条只是把语义写死、让测试能钉住）。
        """
        self._hum_at = float(at)

    def note_hum(self, t: float, ok: bool) -> None:
        """喂一次「现在心情好不好、能不能哼」—— 窗口每秒调一次（和驱力钟同一拍）。

        心情到「很好」时会**隔一会儿没来由地哼一小段**（摇头晃脑 + 一个小音符），
        间隔在 HUM_MIN_GAP~HUM_MAX_GAP 秒之间随机 —— 均匀得像节拍器就不像活物了。
        和叹气 / 点头 / 喷嚏同一套排期：
        - 刚高兴起来：先等一个间隔再哼第一段（立刻哼 = 情绪还没走到脸上）；
        - 一直高兴：哼完接着排下一段；
        - 心情落回去了：排期清掉（**正在哼的那一段让它哼完** —— 半路掐掉像
          被捂住了嘴）。
        """
        if not ok:
            self._hum_next_at = None
            return
        if self._hum_next_at is None:
            self._hum_next_at = t + self._rng.uniform(HUM_MIN_GAP, HUM_MAX_GAP)
            return
        if t >= self._hum_next_at:
            self.hum(t)
            self._hum_next_at = t + self._rng.uniform(HUM_MIN_GAP, HUM_MAX_GAP)

    def hum_note(self, t: float) -> tuple[float, float]:
        """渲染层用：这一刻小音符的（包络, 已升起像素）。没在哼 = (0.0, 0.0)。

        位置那张像是在渲染层拼的（pet._draw_hum）；这里只给「画多亮、升多高」——
        和 Z 的 z_alpha / z_rise 一个分工。
        """
        spent = t - self._hum_at
        k = hum_amount(spent)
        if k <= 0.0:
            return 0.0, 0.0
        rise = HUM_NOTE_RISE_PX * min(1.0, max(0.0, spent / hum_total()))
        return k, rise

    # ── 说话动脸：「字在往外冒，脸跟着动」────────────

    # ── 歪头：「被戳了，歪着脑袋看你（唔？）」────────────
    # 戳一戳的回应：醒着被戳 → 轻快歪一下头、停一小会、再直回来。睡着被戳是
    # 「叫醒」（哈欠那条路）—— 两条不叠着演；累趴 / 动画关也不歪。窗口那层挡。

    def tilt(self, at: float) -> None:
        """安排一次歪头（at 时刻开始）——「戳一戳」与「好奇歪头」都走这一条。

        测试也走这一条。

        再来一次就重新从正位歪起（连着戳两下 = 歪两次）。方向每歪一下换一边
        （不掷随机数 —— 一右一左像轮流打量你）。
        """
        self._tilt_at = float(at)
        self._tilt_dir = -self._tilt_dir

    # ── 入睡的一下：「撑不住了（头一沉，睡过去）」────────────
    # 「醒着 → 睡着」那一刻：整脸慢慢往下沉、眼合上、屏一会儿，再松回睡姿。
    # 窗口（pet._tick）在驱力跨过睡着线的那一刻安排一次；calm 里运行（它
    # 就是进入 calm 的那一下）；抽动要 ≥25 秒才有第一下 —— 两条睡眠通道互斥。

    def dozeoff(self, at: float) -> None:
        """安排一次「撑不住了」（at 时刻开始）—— 窗口在睡着那一刻调。

        再来一次就重新从沉下去起步（实际时序里每段睡觉只来一次 —— 这条只把
        语义写死、让测试能钉住）。不掷随机数、不占随机流（理由同抽动）。
        """
        self._dozeoff_at = float(at)

    # ── 欢迎回来：「你回来啦」────────────
    # 光标静够久（= 你离开）之后第一次动 = 你回来 —— 窗口（pet._note_presence）
    # 在那一下调；醒着才有（睡着时安静的回来归哈欠那条边管）。

    def welcome(self, at: float) -> None:
        """安排一次「欢迎回来」（at 时刻开始）。

        再来一次就重新从抬起来起步（实际时序里两次回来隔着十分钟以上 ——
        这条只把语义写死、让测试能钉住）。不掷随机数、不占随机流。
        """
        self._welcome_at = float(at)

    # ── 蔫一会儿：「心情有点蔫的时候，悄悄往下垂一垂」────────────
    # 第二条只挂心情的动作（第一条是哼小曲 —— 一正一反）：心情落进「有点蔫」
    # 的档里，隔一会儿没精神地往下垂一垂，再自己缓起来。睡着 / 累趴 / 被拎着 /
    # 正在看你写字 / 刚交互完的 5 秒由窗口那层挡。

    def droop(self, at: float) -> None:
        """安排一次蔫一会儿（at 时刻开始）—— 排期器（note_droop）与测试走同一条。

        再来一次就重新从垂下去起步（实际时序里两下之间隔着一两分钟，
        这条只是把语义写死、让测试能钉住）。不掷随机数（理由同抽动 / 喷嚏）。
        """
        self._droop_at = float(at)

    def set_mood_shrink(self, value: float) -> None:
        """一直在的静止缩放（缩小圈）：窗口每秒喂一次。"""
        self._mood_shrink = round(float(value), 6)

    def set_mood_valence(self, value: float) -> None:
        """心情底色（越低越差）：窗口每秒喂一次 —— 绷住从它算，不从缩量反推。"""
        self._mood_valence = round(float(value), 6)

    def hunch(self, at: float) -> None:
        """安排一次绷住（at 时刻开始）。
        再来一次就重新从「绷起来」起步 —— 实际时序里两下之间隔着几十秒，
        这条只是把语义写死、让测试能钉住。不掷随机数（理由同抽动 / 喷嚏）。
        """
        self._hunch_at = float(at)

    def note_hunch(self, t: float, ok: bool) -> None:
        """喂一次「现在心情差不差、能不能绷一下」—— 窗口每秒调一次（和驱力钟同一拍）。
        心情压到「低落」以下时会隔一会儿**整个人缩一小圈**（不是单纯地往下垂 ——
        垂是蔫一会儿那条；这条是在垂与垂之间把「绷紧了」也交代出来），间隔在
        HUNCH_MIN_GAP ~ HUNCH_MAX_GAP 秒之间随机 —— 均匀得像节拍器就不像活物了。
        和别的排期器同一套规矩：刚压下去先等一个间隔、一直差接着排、
        心情缓回来排期清掉（正在绷的那下让它绷完 —— 半路掐掉像被拍了一下）。
        """
        if not ok:
            self._hunch_next_at = None
            return
        if self._hunch_next_at is None:
            self._hunch_next_at = t + self._rng.uniform(HUNCH_MIN_GAP, HUNCH_MAX_GAP)
            return
        if t >= self._hunch_next_at:
            self.hunch(t)
            self._hunch_next_at = t + self._rng.uniform(HUNCH_MIN_GAP, HUNCH_MAX_GAP)

    def note_droop(self, t: float, ok: bool) -> None:
        """喂一次「现在心情蔫不蔫、能不能垂一下」—— 窗口每秒调一次（和驱力钟同一拍）。

        心情落进「有点蔫」时会**隔一会儿没精神地往下垂一垂**，间隔在
        DROOP_MIN_GAP~DROOP_MAX_GAP 秒之间随机 —— 均匀得像节拍器就不像活物了。
        和叹气 / 点头 / 哼小曲同一套排期：
        - 刚蔫下去：先等一个间隔再垂第一下（立刻垂 = 情绪还没长出来）；
        - 一直蔫：垂完接着排下一下；
        - 心情缓回来了：排期清掉（**正在垂的那下让它垂完** —— 半路掐掉像
          打了个哆嗦）。
        """
        if not ok:
            self._droop_next_at = None
            return
        if self._droop_next_at is None:
            self._droop_next_at = t + self._rng.uniform(DROOP_MIN_GAP, DROOP_MAX_GAP)
            return
        if t >= self._droop_next_at:
            self.droop(t)
            self._droop_next_at = t + self._rng.uniform(DROOP_MIN_GAP, DROOP_MAX_GAP)

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
        self._typing_tilt_next_at = None  # 好奇歪头同理：拨过时间线，旧排期不作数
        self._pause_was_active = False  # 暂停标记同理（打字 / 思考共用）
        self._thinking_at = -99.0  # 思考同理：拨过时间线，旧的那轮不作数
        self._thinking_active = False
        self._thinking_break = False
        self._thinking_up = False
        self._twitch_at = -99.0  # 抽动同理：拨过时间线，旧的那下不作数
        self._twitch_next_at = None  # 排期也是（下一次 note_asleep 会重排）
        self._pet_on = False  # 摸摸头同理：拨过时间线，手放哪儿都不作数
        self._pet_on_since = None
        self._pet_active = False
        self._pet_stop_t = None
        self._pet_stop_level = 0.0
        self._sneeze_at = -99.0  # 喷嚏同理：拨过时间线，旧的那个不作数
        self._sneeze_next_at = None  # 排期也是（下一次 note_sneeze 会重排）
        self._hum_at = -99.0  # 哼小曲同理：拨过时间线，旧的那段不作数
        self._hum_next_at = None  # 排期也是（下一次 note_hum 会重排）
        self._tilt_at = -99.0  # 歪头同理：拨过时间线，旧的那下不作数
        self._dozeoff_at = -99.0  # 入睡的一下同理：拨过时间线，旧的那下不作数
        self._welcome_at = -99.0  # 欢迎回来同理：拨过时间线，旧的那次不作数
        self._droop_at = -99.0  # 蔫一会儿同理：拨过时间线，旧的那下不作数
        self._droop_next_at = None  # 排期也是（下一次 note_droop 会重排）
        self._hunch_at = -99.0  # 绷住同理：拨过时间线，旧的那下不作数
        self._hunch_next_at = None  # 排期也是（下一次 note_hunch 会重排）
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
        twitch = twitch_amount(t - self._twitch_at) if calm else 0.0
        sneeze = 0.0 if calm else sneeze_amount(t - self._sneeze_at)
        hum = 0.0 if calm else hum_amount(t - self._hum_at)
        tilt = 0.0 if calm else self._tilt_dir * TILT_MAX_DEG * tilt_amount(t - self._tilt_at)
        # 入睡的一下：只在 calm（睡着）里演 —— 它本来就是「进入 calm」的那一刻；
        # 醒着的时候一眼都不许有（和抽动同一套：calm 定生死）
        dozeoff = dozeoff_amount(t - self._dozeoff_at) if calm else 0.0
        # 欢迎回来：你回来那一刻把脸抬起来（醒着才有 —— 睡着走哈欠那条边）
        welcome = 0.0 if calm else welcome_amount(t - self._welcome_at)
        # 蔫一会儿：心情「有点蔫」时没精神地往下垂（醒着才有 —— calm 冻结一切）
        droop = 0.0 if calm else droop_amount(t - self._droop_at)
        # 绷住：心情压到「低落」以下时的静止关（醒着 / 睡着都在 —— 它不是动作，是姿态）
        hunch = hunch_amount(self._mood_valence)

        if not calm:  # 摸摸头：手停够时间就把「在摸」立起来（睡着不处理，calm 优先）
            self._pet_step(t)
        pet = 0.0 if calm else self._pet_env(t)

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
        if twitch > 0.0:  # 做梦的抽动：全身轻轻一缩（和别的压扁取最深的那个）
            squash = min(squash, 1.0 - (1.0 - TWITCH_DEFLATE) * twitch)
        if pet > 0.0:  # 摸摸头：舒服地半眯着（比点头浅一点，和别的压扁取更深的）
            squash = min(squash, 1.0 - (1.0 - PET_SQUINT_MIN) * pet)
        if sneeze > 0.0:  # 喷嚏：皱脸到用力闭上（比眨眼 14% 还紧一点）
            squash = min(squash, 1.0 - (1.0 - SNEEZE_SQUINT_MIN) * sneeze)
        if dozeoff > 0.0:  # 入睡的一下：眼睛合上（沉到底 20% —— 这一刻它是真闭上了）
            squash = min(squash, 1.0 - (1.0 - DOZEOFF_SQUINT_MIN) * dozeoff)
        if droop > 0.0:  # 蔫一会儿：眼皮耷拉下来（比点头浅、比叹气深 —— 「没精神」）
            squash = min(squash, 1.0 - (1.0 - DROOP_SQUINT_MIN) * droop)

        if hunch > 0.0:  # 绷住：整个人缩一小圈（和别的压扁取更紧的那个）
            squash = min(squash, 1.0 - (1.0 - HUNCH_SQUASH_MIN) * hunch)

        amp = CALM_FACTOR if calm else 1.0
        dy = round(amp * BREATH_AMPLITUDE * math.sin(2 * math.pi * t / BREATH_PERIOD))
        if yawn > 0.0:
            dy -= round(YAWN_LIFT_PX * yawn)  # 伸懒腰：整脸往上顶一点（负 = 上）
        if sigh > 0.0:
            dy += round(SIGH_SINK_PX * sigh)  # 叹气：整脸往下沉一点（正 = 下）
        if nod > 0.0:
            dy += round(NOD_SINK_PX * nod)  # 点头：整脸往下沉一点（正 = 下）
        if pet > 0.0:  # 呼噜：轻轻一上一下（和呼吸同幅、节奏更快 —— 读成「呼噜」）
            dy -= round(PET_PURR_PX * pet * math.sin(2 * math.pi * t / PET_PURR_PERIOD))
        if sneeze > 0.0:  # 喷嚏：整脸往上窜一点（负 = 上）——「啾」的那一下
            dy -= round(SNEEZE_LIFT_PX * sneeze)
        if dozeoff > 0.0:  # 入睡的一下：整脸往下沉（撑不住的「塌」—— 比点头更深）
            dy += round(DOZEOFF_SINK_PX * dozeoff)
        if welcome > 0.0:  # 欢迎回来：整脸往上抬一点（负 = 上）——「精神一振」
            dy -= round(WELCOME_LIFT_PX * welcome)
        if droop > 0.0:  # 蔫一会儿：整脸往下垂一垂（正 = 下）——「没精神」的重量
            dy += round(DROOP_SINK_PX * droop)
        dx = round(amp * SWAY_AMPLITUDE * math.sin(2 * math.pi * t / SWAY_PERIOD))
        if twitch > 0.0:  # 横向一激灵：方向一左一右交替（不占随机流）
            dx += self._twitch_dir * round(TWITCH_SHIFT_PX * twitch)
        if sneeze > 0.0:  # 喷嚏：横向一哆嗦（方向一次一换，不占随机流）
            dx += self._sneeze_dir * round(SNEEZE_JERK_PX * sneeze)
        if hunch > 0.0:  # 绷住：横向也收一点（缩一圈不是一个方向的事）
            dx += round(HUNCH_SQUINT_PX * hunch)
        if hum > 0.0:  # 哼小曲：左右摇摆 —— 正弦摆乘包络，摆幅到得了 ±HUM_ROCK_PX
            dx += round(
                HUM_ROCK_PX * hum * math.sin(2 * math.pi * (t - self._hum_at) / HUM_ROCK_PERIOD)
            )

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
            self._thinking_step(t)
            gx, gy = self._gaze_pos(t)

        # 好奇：越靠左右边缘，脸越"探"（只拉高，不拉宽）
        edge = min(1.0, abs(gx) / GAZE_MAX_X)
        stretch = (
            (1.0 + CURIOSITY_STRETCH * edge * edge)
            * (1.0 + YAWN_STRETCH * yawn)
            * (1.0 + WELCOME_STRETCH * welcome)
            * (1.0 - HUNCH_STRETCH_ABS * hunch)
        )

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
            tilt=tilt,
            shrink=self._mood_shrink,
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
    "DOZEOFF_HOLD_S",
    "DOZEOFF_SETTLE_S",
    "DOZEOFF_SINK_PX",
    "DOZEOFF_SINK_S",
    "DOZEOFF_SQUINT_MIN",
    "DROOP_HOLD_S",
    "DROOP_MAX_GAP",
    "DROOP_MIN_GAP",
    "DROOP_RISE_S",
    "DROOP_SINK_PX",
    "DROOP_SINK_S",
    "DROOP_SQUINT_MIN",
    "FADE_DURATION",
    "GAZE_EASE",
    "GAZE_MAX_GAP",
    "GAZE_MAX_X",
    "GAZE_MAX_Y",
    "GAZE_MIN_GAP",
    "HUM_EASE_IN_S",
    "HUM_EASE_OUT_S",
    "HUM_MAX_GAP",
    "HUM_MIN_GAP",
    "HUM_NOTE_RISE_PX",
    "HUM_ROCK_CYCLES",
    "HUM_ROCK_PERIOD",
    "HUM_ROCK_PX",
    "HUM_ROCK_S",
    "HUNCH_ABS_BELOW",
    "HUNCH_MAX_GAP",
    "HUNCH_MIN_GAP",
    "HUNCH_RAMP",
    "HUNCH_SLACK_X",
    "HUNCH_SQUASH_MIN",
    "HUNCH_SQUINT_PX",
    "HUNCH_STRETCH_ABS",
    "LOOK_HOLD_S",
    "LOOK_MOVE_MIN",
    "LOOK_RETARGET_MIN_S",
    "MOOD_SHRINK_BELOW",
    "MOOD_SHRINK_FLOOR",
    "MOOD_SHRINK_MIN",
    "NOD_HOLD_S",
    "NOD_MAX_GAP",
    "NOD_MIN_GAP",
    "NOD_SAG_S",
    "NOD_SINK_PX",
    "NOD_SNAP_S",
    "NOD_SQUINT_MIN",
    "PET_DWELL_S",
    "PET_EASE_IN_S",
    "PET_EASE_OUT_S",
    "PET_PURR_PERIOD",
    "PET_PURR_PX",
    "PET_SQUINT_MIN",
    "POP_DURATION",
    "SIGH_DEFLATE",
    "SIGH_HOLD_S",
    "SIGH_MAX_GAP",
    "SIGH_MIN_GAP",
    "SIGH_RISE_S",
    "SIGH_SINK_PX",
    "SIGH_SINK_S",
    "SNEEZE_BURST_S",
    "SNEEZE_HOLD_S",
    "SNEEZE_JERK_PX",
    "SNEEZE_LIFT_PX",
    "SNEEZE_MAX_GAP",
    "SNEEZE_MIN_GAP",
    "SNEEZE_SETTLE_S",
    "SNEEZE_SQUINT_MIN",
    "SNEEZE_WINDUP",
    "SNEEZE_WINDUP_S",
    "SURVEY_DWELL_S",
    "SURVEY_LEAD_S",
    "SURVEY_LIFT_PX",
    "SURVEY_TARGETS",
    "SWAY_AMPLITUDE",
    "TALK_BOB_Y",
    "TALK_EASE_IN",
    "TALK_EASE_OUT",
    "TALK_PERIOD",
    "TALK_SQUASH",
    "THINKING_GAZE_Y",
    "THINKING_RETARGET_MIN_S",
    "TILT_FALL_S",
    "TILT_HOLD_S",
    "TILT_MAX_DEG",
    "TILT_RISE_S",
    "TWITCH_DEFLATE",
    "TWITCH_HOLD_S",
    "TWITCH_JOLT_S",
    "TWITCH_MAX_GAP",
    "TWITCH_MIN_GAP",
    "TWITCH_SETTLE_S",
    "TWITCH_SHIFT_PX",
    "TYPING_GAZE_Y",
    "TYPING_HOLD_S",
    "TYPING_RETARGET_MIN_S",
    "TYPING_TILT_FIRST_MAX_S",
    "TYPING_TILT_FIRST_MIN_S",
    "TYPING_TILT_MAX_GAP",
    "TYPING_TILT_MIN_GAP",
    "WELCOME_AWAY_S",
    "WELCOME_HOLD_S",
    "WELCOME_LIFT_PX",
    "WELCOME_MOVE_MIN",
    "WELCOME_RISE_S",
    "WELCOME_SETTLE_S",
    "WELCOME_STRETCH",
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
    "dozeoff_amount",
    "dozeoff_total",
    "droop_amount",
    "droop_total",
    "hum_amount",
    "hum_total",
    "hunch_amount",
    "hunch_ok",
    "mood_shrink",
    "nod_amount",
    "nod_total",
    "sigh_amount",
    "sigh_total",
    "sneeze_amount",
    "sneeze_total",
    "survey_total",
    "tilt_amount",
    "tilt_total",
    "twitch_amount",
    "twitch_total",
    "welcome_amount",
    "welcome_total",
    "yawn_amount",
    "yawn_squint",
    "yawn_total",
]
