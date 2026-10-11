"""开机自检序列（自选小步）—— 上电扫掠、自检行、唤醒淡入。

为什么做这个：第二轮把界面做成了一台老机器（像素字 / CRT 质感），
但"开机"这一刻还是"啪"地出现 —— 一台老机器上电该有它自己的样子。
它还带着真信息：记忆多少条、外挂工具几个、大脑通了没，开机几秒里报一遍。

设计（时间常数都在速查表第 12 节里钉着）：

- 上电扫掠 POWER_DUR 秒：一条亮线从中间向上下展开（老 CRT 的栅格动作），
  展开的同时变暗，最后落回干净的面板底色；
- 自检行每 LINE_STEP 秒出现一行，末行之后 LOG_TAIL 秒进入唤醒；
- 唤醒 WAKE_DUR 秒：日志整屏让位，正常画面（面板 + 脸 + 状态行）整体淡入，
  淡入结束的那一刻和正常绘画**逐像素接上**（tests/test_boot.py 对账）；
- 光标每 CURSOR_PERIOD 秒亮灭一轮（不闪的光标看着像卡死）；
- 整层可关：SAMMY_BOOT=off（语义和 SAMMY_ANIM / SAMMY_CRT 一套）。

为什么时间形状要写成**纯函数**：快慢、跳行、闪不闪，盯着屏幕都说不准；
只有把 t 换算成"第几阶段、亮到几分、第几行、光标在不在"的纯函数能钉住。
画面层只问 frame_at(t) 要这一帧的参数 —— 和打字机（typewriter.py）同一套思路。

怎么触发：真启动路径（__main__ 的 run 分支）在起窗后调窗口的 begin_boot() 方法；
快照 / 自检 / 其它素材脚本都不调，所以它们拍到的永远是稳态。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QRectF

# ── 时间表（速查表第 12 节）────────────────────────
POWER_DUR = 0.55  # 上电扫掠时长（秒）
LOG_LEAD = 0.12  # 扫掠结束到第一行出现的间隔（秒）
LINE_STEP = 0.3  # 两行之间的间隔（秒）
LOG_TAIL = 0.4  # 最后一行出现后停留多久进入唤醒（秒）
WAKE_DUR = 0.65  # 正常画面淡入时长（秒）
CURSOR_PERIOD = 0.5  # 光标亮灭一个整周期（秒，前一半亮）

# ── 自检块几何（设备单位；渲染与判据共用）────────────
TEXT_LEFT = 48  # 自检块距面板左边的边距
LINE_H = 34  # 行高
CURSOR_W = 12  # 光标宽
CURSOR_H = 24  # 光标高
CURSOR_GAP = 8  # 光标跟在文字后面的空隙


@dataclass(frozen=True)
class Frame:
    """开机序列某一刻的全部参数（画面层照这个画，不做任何再推算）。"""

    phase: str  # power | log | wake | done
    power: float  # 0 → 1，上电亮带的展开进度
    lines: int  # 已出现的自检行数
    cursor: bool  # 光标这一刻亮不亮
    wake: float  # 0 → 1，正常画面的淡入进度


def boot_enabled(env: dict | None = None) -> bool:
    """开关（`SAMMY_BOOT=off` 关掉）—— 语义和 SAMMY_ANIM / SAMMY_CRT 一套。"""
    if env is not None:
        raw = env.get("SAMMY_BOOT", "on")
    else:
        from .voice import config

        raw = config("SAMMY_BOOT", "on")
    return str(raw or "on").strip().lower() not in {"off", "0", "false", "no"}


def log_start() -> float:
    """第一行出现的时刻。"""
    return POWER_DUR + LOG_LEAD


def wake_start(n_lines: int) -> float:
    """唤醒（正常画面开始淡入）的时刻。"""
    n = max(1, n_lines)
    return log_start() + (n - 1) * LINE_STEP + LOG_TAIL


def total_seconds(n_lines: int) -> float:
    """整段序列的时长 —— 过了这个点画面层就该交班给正常绘画。"""
    return wake_start(n_lines) + WAKE_DUR


def cursor_on(t: float) -> bool:
    """光标这一刻亮不亮（锚在 t=0，每 CURSOR_PERIOD 秒一个完整亮灭）。"""
    return (t % CURSOR_PERIOD) < (CURSOR_PERIOD / 2)


def _smooth(p: float) -> float:
    """0 → 1 的平滑缓动（两端速度为 0）—— 与脸部动画那条曲线同一个形状。"""
    p = min(1.0, max(0.0, p))
    return 0.5 * (1.0 - math.cos(math.pi * p))


def frame_at(t: float, n_lines: int) -> Frame:
    """t 时刻这一帧的参数（纯函数 —— 全部时间判据钉的就是它）。"""
    n = max(1, n_lines)
    if t < POWER_DUR:
        return Frame(
            phase="power", power=min(1.0, max(0.0, t / POWER_DUR)), lines=0, cursor=False, wake=0.0
        )
    ws = wake_start(n)
    if t < ws:
        appear = log_start()
        lines = 0
        for i in range(n):
            if appear + i * LINE_STEP <= t + 1e-9:
                lines = i + 1
        return Frame(phase="log", power=1.0, lines=lines, cursor=cursor_on(t), wake=0.0)
    total = ws + WAKE_DUR
    if t < total:
        return Frame(
            phase="wake", power=1.0, lines=n, cursor=False, wake=_smooth((t - ws) / WAKE_DUR)
        )
    return Frame(phase="done", power=1.0, lines=n, cursor=False, wake=1.0)


# ── 关机序列（收束成一条线、一个点、熄灭）──────────────
# 开机是"上电"，关机就是它的反面：栅格断电、画面往中缝收，
# 收成一条亮线、再收成一个光点，最后没了 —— 老显示器的退场。
# 和开机放在同一个模块：都是"电源时刻"的纯时间轴，共用同一个开关
# （SAMMY_BOOT=off 时两段都不播）。
COLLAPSE_DUR = 0.40  # 画面纵向压扁的时长，秒
LINE_DUR = 0.22  # 亮线横向收束的时长，秒
DOT_DUR = 0.30  # 光点熄灭的时长，秒
SQUEEZE_MIN = 0.02  # 纵向压扁终点的系数（相对面板高）
SHRINK_MIN = 0.04  # 横向收束终点的系数（相对面板宽）
DOT_SHRINK = 0.01  # 熄灭段继续收窄到的系数（约等于一个点）
CORE_H = 5  # 中心亮线的高度，设计单位


@dataclass(frozen=True)
class ShutdownFrame:
    """关机序列某一刻的全部参数（画面层照这个画，不做任何再推算）。"""

    phase: str  # collapse / line / dot / done
    sx: float  # 横向收缩，从 1 收到 DOT_SHRINK
    sy: float  # 纵向压扁，从 1 压到 SQUEEZE_MIN
    core: float  # 中心亮线的亮度，0 涨到 1
    alpha: float  # 整体透明度，熄灭段从 1 暗到 0


def shutdown_total_seconds() -> float:
    """整段关机序列的时长 —— 过了这个点，窗口就该把退出交出去。"""
    return COLLAPSE_DUR + LINE_DUR + DOT_DUR


def shutdown_frame_at(t: float) -> ShutdownFrame:
    """t 时刻这一帧的参数（纯函数 —— 关机的时间判据钉的就是它）。

    形状的由来：断电时场偏转先塌（纵向快起慢收，缓入一条线），然后行偏转塌
    （横向往中心收成一点），最后剩的光点自己暗掉。t=0 就是稳态本身 ——
    起手不许跳帧，收尾落在全黑上。
    """
    if t <= 0.0:
        return ShutdownFrame(phase="collapse", sx=1.0, sy=1.0, core=0.0, alpha=1.0)
    if t < COLLAPSE_DUR:
        p = t / COLLAPSE_DUR
        # (1-p) 平方的形状：一断电就往中缝掉、最后缓入一条线
        sy = SQUEEZE_MIN + (1.0 - SQUEEZE_MIN) * (1.0 - p) ** 2
        return ShutdownFrame(phase="collapse", sx=1.0, sy=sy, core=_smooth(p), alpha=1.0)
    t1 = t - COLLAPSE_DUR
    if t1 < LINE_DUR:
        q = t1 / LINE_DUR
        sx = SHRINK_MIN + (1.0 - SHRINK_MIN) * (1.0 - q) ** 2
        return ShutdownFrame(phase="line", sx=sx, sy=SQUEEZE_MIN, core=1.0, alpha=1.0)
    t2 = t1 - LINE_DUR
    if t2 < DOT_DUR:
        r = t2 / DOT_DUR
        sx = SHRINK_MIN - (SHRINK_MIN - DOT_SHRINK) * r
        return ShutdownFrame(phase="dot", sx=sx, sy=SQUEEZE_MIN, core=1.0, alpha=1.0 - _smooth(r))
    return ShutdownFrame(phase="done", sx=DOT_SHRINK, sy=SQUEEZE_MIN, core=1.0, alpha=0.0)


def self_check_lines(
    *, memories: int | None, expressions: int | None, tools: int | None, brain: bool
) -> tuple[str, ...]:
    """自检行的内容：真实数据，拿不到的写实话（宁可说"未打开"，不说假话）。

    - 记忆条数 = 槽位 + 日记（和 `make memory` 的口径一致；摘要不重复计数）；
    - 表情张数 = 表情目录里的张数（随仓库走，基本恒定）；
    - 外挂工具 = data/mcp.json 里启用的服务数（没配就是"无"，读不动就是"未就绪"）；
    - 大脑 = 接没接通（对象在不在；真正的连通性第一次对话才知道）。
    """
    lines = ["SAMMY 个人终端"]
    lines.append("记忆库 · 未打开" if memories is None else f"记忆库 {memories} 条 · 就绪")
    lines.append("表情库 · 缺失" if expressions is None else f"表情库 {expressions} 张 · 就绪")
    if tools is None:
        lines.append("外挂工具 · 未就绪")
    elif tools == 0:
        lines.append("外挂工具 · 无")
    else:
        lines.append(f"外挂工具 {tools} 个 · 就绪")
    lines.append("大脑 · 就绪" if brain else "大脑 · 未接通")
    lines.append("自检完成")
    return tuple(lines)


def block_rect(panel: QRectF, n_lines: int) -> QRectF:
    """自检块（所有行合起来）在面板里的位置：左右留边、垂直居中。"""
    n = max(1, n_lines)
    top = panel.center().y() - (n * LINE_H) / 2.0
    return QRectF(panel.left() + TEXT_LEFT, top, panel.width() - 2 * TEXT_LEFT, n * LINE_H)


def line_rect(block: QRectF, i: int) -> QRectF:
    """第 i 行（0 起）的绘制矩形。"""
    return QRectF(block.left(), block.top() + i * LINE_H, block.width(), LINE_H)


def cursor_rect(line: QRectF, text_w: float) -> QRectF:
    """光标：跟在某一行文字的右端（text_w 是这行文字的实际宽度）。"""
    return QRectF(
        line.left() + text_w + CURSOR_GAP,
        line.center().y() - CURSOR_H / 2.0,
        CURSOR_W,
        CURSOR_H,
    )
