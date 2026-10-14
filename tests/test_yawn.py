"""醒来的哈欠（自选小步·第八次）——「睡醒了先伸个懒腰、打个哈欠」。

动机：睡相（第七次）让「睡着」看得出来（那个慢慢冒的 Z）；可**醒**是瞬间的 ——
睡脸直接切回暖脸，读起来像换了张贴纸。哈欠把「醒来」变成一个过程：
先抻起来（伸懒腰）→ 眼睛眯上撑一小会（呵——）→ 慢慢松开、落回常态。

两条曲线（第一版把眯眼和拉高揉在同一条曲线上，实测翻车：整脸被压成
一条小横杠 —— 因为 bitmap 脸的「眯眼」就是整脸压扁，DEVLOG 有记）：
- 拉高曲线 yawn_amount：撑起来 → 撑住 → 收回去，管纵向拉高 + 拔高；
- 眯眼曲线 yawn_squint：晚一拍起步（先抻后眯），管压扁（眼睛合上）。

四层判据：
1. 纯函数：两条曲线的时间线逐点对账、峰谷锟死、只加不改、睡着不哈欠、
   中途重开 / reset 都换新；
2. 几何：全 35 张脸在最坏形变组合下也不冒出重绘区（冒出去那圈动画帧
   不会刷新 —— 脸会花，和 Z 位置那条坑同源）；真渲染再验一遍；
3. 渲染（真窗口离屏抓图，scale 1.0 双胞胎）：先抻（高 +8px 以上、顶沿上抬）、
   再眯（压到一半以下）、收完与孪生逐字节一致；
4. 链路：三条唤醒路（自己睡饱 / 被戳 / 被叫）各触发一次哈欠；醒着不排、
   动画关着谁都不打。

（设计数字：九个 YAWN_* 常量都在 anim.py 顶部；调参速查表第 18 节也有。）
"""

from __future__ import annotations

import math
import pathlib
import sys
import time
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim, drives
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

T0 = 30.0  # 热身后的时刻（初始凝视 / 眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_talk 同一套隔离）。"""
    from sammy import attention, care

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05):
    """走时间轴，返回 [(t, frame)]，步长固定、确定性。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        out.append((t, a.frame_at(t)))
    return out


def _blink_squash(a: Animator, t: float) -> float:
    """按眨眼时间表复算这一刻的 squash（没有哈欠成分）—— 对账用。"""
    s = 1.0
    for start in a.blink_times(t):
        if start <= t <= start + anim.BLINK_DURATION:
            s = min(
                s,
                1.0
                - (1.0 - anim.BLINK_MIN_SQUASH) * anim._envelope((t - start) / anim.BLINK_DURATION),
            )
    return s


# ── 纯函数层：时间线与峰谷 ────────────────────────


def test_yawn_constants_stay_subtle():
    """常量必须停在「轻微」量级，而且两条曲线的先后关系得成立（先抻后眯）。"""
    total = anim.yawn_total()
    assert 1.0 <= total <= 2.5, f"整段 {total}s —— 太短看不见过程，太长像慢动作"
    assert 0.2 <= anim.YAWN_RISE_S <= 1.0
    assert 0.0 <= anim.YAWN_HOLD_S <= 0.8
    assert 0.3 <= anim.YAWN_SETTLE_S <= 1.5
    assert 0.05 <= anim.YAWN_STRETCH <= 0.15, "拉高要看得见，又不能把脸扯变形"
    assert 1 <= anim.YAWN_LIFT_PX <= 6, "拔高是像素级的小动作"
    assert 0.2 <= anim.YAWN_SQUINT_DELAY_S <= 1.0, "眯眼晚一拍可以，晚太多就不是一个动作了"
    assert 0.1 <= anim.YAWN_SQUINT_RISE_S <= 0.8
    assert 0.2 <= anim.YAWN_SQUINT_FALL_S <= 1.2, "松开比合上慢 —— 像慢慢睁眼"
    assert 0.15 <= anim.YAWN_SQUINT_MIN <= 0.6, "哈欠的眯眼比眨眼浅（眨眼到 0.14）"
    # 先抻后眯：眯眼起步要晚于拉高；满眯时拉高已经到位（撑住段或紧跟着的尾巴）
    assert anim.YAWN_SQUINT_DELAY_S >= anim.YAWN_RISE_S * 0.8
    peak = anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S
    assert anim.YAWN_RISE_S <= peak <= anim.YAWN_RISE_S + anim.YAWN_HOLD_S + 0.25
    # 两条曲线同一条终点：眯眼松开和拉高收完都落在总时长里
    end = anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S + anim.YAWN_SQUINT_FALL_S
    assert abs(end - total) <= 0.2, f"眯眼曲线到 {end}s，拉高到 {total}s —— 两条腿不一样长"


def test_yawn_shape_opens_holds_and_settles():
    """拉高曲线三段拼一条时间线：撑起来 → 撑住 → 收回去；两头精确为 0。"""
    assert anim.yawn_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.yawn_amount(0.0) == 0.0, "从静息起步"
    assert anim.yawn_amount(anim.YAWN_RISE_S / 2) == pytest.approx(0.5), "撑到一半正好一半"
    assert anim.yawn_amount(anim.YAWN_RISE_S) == pytest.approx(1.0)
    assert anim.yawn_amount(anim.YAWN_RISE_S + anim.YAWN_HOLD_S / 2) == 1.0, "撑住段是满的"
    k = anim.YAWN_RISE_S + anim.YAWN_HOLD_S
    assert anim.yawn_amount(k + anim.YAWN_SETTLE_S / 2) == pytest.approx(0.5)
    assert anim.yawn_amount(anim.yawn_total()) == 0.0, "收完就该是零"
    assert anim.yawn_amount(anim.yawn_total() + 5.0) == 0.0
    up = [anim.yawn_amount(anim.YAWN_RISE_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "撑起来段不单调"
    down = [anim.yawn_amount(k + anim.YAWN_SETTLE_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(down)), "收回去段不单调"


def test_yawn_squint_shape_is_staggered():
    """眯眼曲线：晚一拍起步、合上、松开；两头精确为 0，升 / 降段单调。"""
    d, r, f = anim.YAWN_SQUINT_DELAY_S, anim.YAWN_SQUINT_RISE_S, anim.YAWN_SQUINT_FALL_S
    assert anim.yawn_squint(d - 0.01) == 0.0, "起步之前不该眯"
    assert anim.yawn_squint(0.0) == 0.0
    assert anim.yawn_squint(d + r / 2) == pytest.approx(0.5), "合到一半正好一半"
    assert anim.yawn_squint(d + r) == pytest.approx(1.0), "该满眯的那一刻没满"
    assert anim.yawn_squint(d + r + f / 2) == pytest.approx(0.5)
    assert anim.yawn_squint(d + r + f + 0.5) == 0.0, "松开走完就该是零"
    up = [anim.yawn_squint(d + r * i / 12) for i in range(13)]
    assert all(b >= a for a, b in pairwise(up)), "合上段不单调"
    down = [anim.yawn_squint(d + r + f * i / 12) for i in range(13)]
    assert all(b <= a for a, b in pairwise(down)), "松开段不单调"


def test_yawn_starts_from_rest_and_peak_is_pinned():
    """起点零形变（静息起步）；拉高峰值 / 满眯时刻的通道值逐个锟死。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.yawn(T0)
    f0 = a.frame_at(T0)
    e0 = min(1.0, abs(f0.gx) / anim.GAZE_MAX_X)
    assert f0.stretch == pytest.approx(1.0 + anim.CURIOSITY_STRETCH * e0 * e0), "起点不该有拉高"
    assert f0.dy == round(
        anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * T0 / anim.BREATH_PERIOD)
    ), "起点不该有拔高"

    tall = T0 + anim.YAWN_RISE_S  # 刚抻满、眯眼还没上来
    f = a.frame_at(tall)
    e = min(1.0, abs(f.gx) / anim.GAZE_MAX_X)
    assert f.stretch == pytest.approx(
        (1.0 + anim.CURIOSITY_STRETCH * e * e) * (1.0 + anim.YAWN_STRETCH)
    )
    assert f.dy == round(
        anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * tall / anim.BREATH_PERIOD)
    ) - (anim.YAWN_LIFT_PX)
    assert f.squash == pytest.approx(_blink_squash(a, tall)), "这下还没轮到眯眼"

    shut = T0 + anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S  # 满眯
    fs = a.frame_at(shut)
    assert fs.squash == pytest.approx(min(_blink_squash(a, shut), anim.YAWN_SQUINT_MIN)), (
        "满眯不是满的"
    )
    assert fs.stretch == pytest.approx(
        (1.0 + anim.CURIOSITY_STRETCH * min(1.0, abs(fs.gx) / anim.GAZE_MAX_X) ** 2)
        * (1.0 + anim.YAWN_STRETCH * anim.yawn_amount(shut - T0))
    ), "满眯时拉高不该提前收了"


def test_yawn_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：两条曲线的三个通道都按公式对齐。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.yawn(T0)
    live_tall = live_squint = 0
    for i in range(131):
        t = round(T0 + i * 0.02, 6)
        tau = t - T0
        f = a.frame_at(t)
        m = anim.yawn_amount(tau)
        q = anim.yawn_squint(tau)
        e = min(1.0, abs(f.gx) / anim.GAZE_MAX_X)
        assert f.stretch == pytest.approx(
            (1.0 + anim.CURIOSITY_STRETCH * e * e) * (1.0 + anim.YAWN_STRETCH * m)
        ), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) - round(anim.YAWN_LIFT_PX * m), t
        assert f.squash == pytest.approx(
            min(_blink_squash(a, t), 1.0 - (1.0 - anim.YAWN_SQUINT_MIN) * q)
        ), t
        if m > 0:
            live_tall += 1
        if q > 0:
            live_squint += 1
    assert live_tall >= 60, f"拉高窗口里只有 {live_tall} 帧在动"
    assert live_squint >= 40, f"眯眼窗口里只有 {live_squint} 帧在动"


def test_yawn_only_adds_other_channels_do_not_move():
    """只打了哈欠的一方与完全没打的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.yawn(T0)
    live = 0
    for i in range(1, 141):
        t = round(T0 + i * 0.02, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.dx, fa.pop, fa.gx, fa.gy, fa.talk_y, fa.talk_sq) == (
            fb.dx,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.talk_y,
            fb.talk_sq,
        ), f"{t} 时别的通道被哈欠带偏了"
        if t < T0 + anim.yawn_total():
            if (fa.squash, fa.dy, fa.stretch) != (fb.squash, fb.dy, fb.stretch):
                live += 1
        else:
            assert (fa.squash, fa.dy, fa.stretch) == (
                fb.squash,
                fb.dy,
                fb.stretch,
            ), f"{t} 收完之后还没回到常态"
    assert live >= 30, f"窗口里只有 {live} 帧真的变了 —— 哈欠没打起来"


def test_yawn_is_suppressed_when_calm():
    """睡着不哈欠（定格优先）：calm 期间三个通道与孪生逐点全等；醒来接着打。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.yawn(T0)
    for i in range(1, 41):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.squash, fa.dy, fa.stretch) == (fb.squash, fb.dy, fb.stretch), (
            f"{t} 睡着时哈欠漏出来了"
        )
    tall = T0 + anim.YAWN_RISE_S
    woke = [a.frame_at(round(tall + i * 0.02, 6)) for i in range(6)]
    assert any(f.stretch > 1.0 + anim.CURIOSITY_STRETCH for f in woke), "醒了不接着打，哈欠就哑了"


def test_yawn_restart_starts_fresh():
    """中途再排一次：从撑起来重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, d = Animator(seed=13), Animator(seed=13)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.yawn(T0)
    fa = a.frame_at(T0 + 0.3)
    fd = d.frame_at(T0 + 0.3)
    assert fa.stretch != fd.stretch, "前提不成立：a 没有在打"
    t2 = T0 + 0.5
    a.yawn(t2)  # 中途重开
    d.yawn(t2)  # 只在这一刻开始打
    for tau in (0.0, 0.1, 0.35, 0.7, 1.0, 1.55, 2.0):
        t = round(t2 + tau, 6)
        fa, fd = a.frame_at(t), d.frame_at(t)
        assert (fa.squash, fa.dy, fa.stretch) == (fd.squash, fd.dy, fd.stretch), (
            f"{t} 重开后没有从头起步"
        )


def test_yawn_reset_clears_state():
    """时间线被拨动（reset）：旧的那次哈欠不作数，与从未打过的一方全等。"""
    a, b = Animator(seed=16), Animator(seed=16)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.yawn(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.1, 0.4, 0.9, 1.4):
        t = round(T0 + 0.2 + tau, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.squash, fa.dy, fa.stretch) == (fb.squash, fb.dy, fb.stretch), (
            f"{t} reset 之后旧哈欠还在"
        )


def test_yawn_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=17)
        out = []
        for i in range(1, 141):
            t = round(i * 0.05, 6)
            if i == 40:
                a.yawn(t)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


# ── 几何：最坏形变不许冒出重绘区 ──────────────────


def test_worst_case_geometry_fits_the_repaint_pad(qapp):
    """几何契约：所有形变同时顶格，脸内容也不冒出重绘区（否则那圈不刷新 → 脸会花）。

    算法：脸的位图内容在框里本来留着一圈空边（量出来的）；最坏情况 =
    「好奇拉高 × 哈欠拉高 × 弹一下 × 说话鼓收 × 叹气压扁 / 点头压扁」乘在
    内容到中心的距离上，再加上几种平移（呼吸 / 说话 / 凝视 / 哈欠拔高 /
    叹气下沉 / 点头下沉）。叹气与点头的「压扁」与「下沉」都是同一条曲线上的
    成对项：对下沿的净增按两端取最大（小脸是净增、大脸是净减），都算进来。
    睡梦抽动（睡时横向一激灵）单独一条：它只在睡着时出现，那时没有 sway / 弹 /
    淡化 —— 与清醒的组合互斥，硬叠是假需求（详见下面那条注释）。
    摸摸头的呼噜（±PET_PURR_PX）和呼吸同型、是清醒时的纵向平移，与上面所有项
    都可能叠加 —— 并进 move_y 一起算（它的眯眼是「压扁」，往下只会更安全）。
    喷嚏（上窜 + 用力闭上同刻）成对算：压扁把顶沿收回来的收益远大于上窜
    3px 的风险，所以上窜按满量、压扁按 SNEEZE_SQUINT_MIN 拼一条（对顶沿），
    横向哆嗦并进左右两条 —— 和叹息 / 点头同一套「成对」写法。
    哼小曲的摇摆（±HUM_ROCK_PX）也并进左右两条 —— 它和呼吸一样是清醒时的
    横向平移，和上面所有项都可能叠加（喷嚏是反射，可能在哼着的时候打）。
    歪头（±TILT_MAX_DEG）是第一条**旋转**形变：把每张脸的内容外框四角按 ±θ
    绕中心转一圈、取旋转后的外接范围，再替掉 top / bottom / left / right 折进
    上面每条公式（戳一戳可能撞上呼吸 / 叹气 / 喷嚏任何一刻 —— 叠着算，不设
    互斥）。唯一的例外是睡时的抽动项：歪头只在醒着，两者互斥，用原框。
    入睡的一下（撑不住了）在 **calm 里**演（「醒着 → 睡着」那一刻）——
    和抽动一样是睡时通道、与清醒项互斥，但它叠得上「定格凝视 + 换表情的弹
    + 好奇拉高」：下沉（加 DOZEOFF_SINK_PX）与压合（压到 DOZEOFF_SQUINT_MIN 倍）
    成对算净量（和叹气 / 点头 / 喷嚏同一套）；纵向另加定格凝视的纵向偏移。
    抽动至少 25 秒才有第一下、这一下 3 秒以内就演完 —— 两条互斥，各自算。
    蔫一会儿（心情低时的下垂）与叹气 / 点头同一族（压扁 + 下沉成对）：和
    叹气真的会同时刻撞上（两首都挂空闲时段）—— 单算一条之外，再叠一条
    「与叹气同刻」的最坏（保守一点，值不大）。
    欢迎回来（精神一振）是清醒时的「上抬 + 拉高」：拉高并进 v、上抬按满量
    加在顶沿那条上 —— 和哈欠 / 喷嚏同一套写法（它和任何清醒动作都可能撞上，
    叠着算、不设互斥）。
    这是**全局预算守卫**：调大任何一道形变常数（YAWN_STRETCH / SIGH_SINK_PX /
    SIGH_DEFLATE / NOD_SINK_PX / NOD_SQUINT_MIN / TWITCH_SHIFT_PX /
    SNEEZE_LIFT_PX / SNEEZE_JERK_PX / HUM_ROCK_PX / TILT_MAX_DEG /
    DOZEOFF_SINK_PX / DOZEOFF_SQUINT_MIN / DROOP_SINK_PX / DROOP_SQUINT_MIN /
    CURIOSITY_STRETCH / PET_PURR_PX /
    TALK_* …），先看这条测试。
    """
    from PySide6.QtCore import QSize

    from sammy import faces, layout
    from sammy.pet import FACE_REGION_PAD

    box = layout.layout_dev(800, 480).face
    W, H = box.width(), box.height()
    cx, cy = W / 2.0, H / 2.0

    def _rot_extents(L, T, R, B):
        """内容外框四角按 ±TILT_MAX_DEG 绕中心转一圈后的外接范围。"""
        th = math.radians(anim.TILT_MAX_DEG)
        cth, sth = math.cos(th), math.sin(th)
        xs, ys = [], []
        for x in (L, R):
            for y in (T, B):
                dx, dy = x - cx, y - cy
                xs += [cx + dx * cth - dy * sth, cx + dx * cth + dy * sth]
                ys += [cy + dx * sth + dy * cth, cy - dx * sth + dy * cth]
        return min(xs), min(ys), max(xs), max(ys)

    # 蔫过头（心情躺平时静止姿态自己收一小圈）：缩放绕着脸中心，对上 / 下 / 左右
    # 四条边都是**收益**（收进来），不会把任何一条顶出去 —— 并列在这里是为了让
    # 「预算里算过这一条」有据可查（常量名钉在下面这条等式里）。
    v = (
        (1.0 + anim.CURIOSITY_STRETCH)
        * (1.0 + anim.YAWN_STRETCH)
        * (1.0 + anim.POP_AMPLITUDE)
        * (1.0 + anim.TALK_SQUASH)
        * (1.0 + anim.WELCOME_STRETCH)
        * anim.MOOD_SHRINK_MIN  # 蔫过头的静止收一圈（乘上去 = 保守；真值是收）
    )
    # 入睡的一下在 calm 里演：那一刻的队友 = 定格凝视 + 换表情的弹 + 好奇拉高
    # （哈欠 / 说话 / 微动都被 calm 关掉；抽动至少 25 秒才有第一下 —— 互斥）。
    v_sleep = (1.0 + anim.CURIOSITY_STRETCH) * (1.0 + anim.POP_AMPLITUDE)
    worst = (0.0, "")
    for idx in sorted(faces.EXPR_NAMES):
        img = faces.face_pixmap(idx, QSize(W, H)).toImage()
        ys = [
            y
            for y in range(0, H, 2)
            if any(img.pixelColor(x, y).alpha() > 8 for x in range(0, W, 2))
        ]
        xs = [
            x
            for x in range(0, W, 2)
            if any(img.pixelColor(x, y).alpha() > 8 for y in range(0, H, 2))
        ]
        assert ys and xs, f"第 {idx} 张脸是空的？"
        top, bottom, left, right = min(ys), max(ys), min(xs), max(xs)
        # 歪头是旋转形变：下面所有清醒项都用**旋转后**的外接框；睡时
        # 抽动项（最后两条）用原框 —— 歪头只在醒着，两者互斥。
        left0, top0, right0, bottom0 = left, top, right, bottom
        left, top, right, bottom = _rot_extents(left0, top0, right0, bottom0)
        # 摸摸头的呼噜与呼吸同型（纵向 ±PET_PURR_PX），会叠加 —— 并进来
        move_y = (
            anim.GAZE_MAX_Y + anim.BREATH_AMPLITUDE + math.ceil(anim.TALK_BOB_Y) + anim.PET_PURR_PX
        )
        # 叹气：下沉（+SIGH_SINK_PX）与压扁（×SIGH_DEFLATE）同一时刻到顶 ——
        # 对下沿的净增按两端取最大；上沿只需要「不下沉」的那一支（下沉是往下
        # 推的，对上沿只会更安全）。
        need = max(
            (cy - top) * (v - 1) + anim.YAWN_LIFT_PX + move_y - top,
            # 欢迎回来：上抬按满量（拉高已经并进 v —— 和喷嚏 / 叹气同一套
            # 写法：每行走一个通道的最坏组合，不把它们相加）
            (cy - top) * (v - 1) + anim.WELCOME_LIFT_PX + move_y - top,
            (bottom - cy) * (v - 1) + move_y - (H - 1 - bottom),
            (bottom - cy) * (v * anim.SIGH_DEFLATE - 1.0)
            + move_y
            + anim.SIGH_SINK_PX
            - (H - 1 - bottom),
            # 点头同理（压到一半 + 下沉）：净量按两端取最大成对算进来
            (bottom - cy) * (v * anim.NOD_SQUINT_MIN - 1.0)
            + move_y
            + anim.NOD_SINK_PX
            - (H - 1 - bottom),
            # 蔫一会儿（心情「有点蔫」时往下垂）：和叹气 / 点头同一套成对写法；
            # 它和叹气真的可能同刻（都挂空闲时段）—— 再叠一条两条相叠的最坏
            # （压扁取更深的那个 —— 两条取 min 是保守写法）。
            (bottom - cy) * (v * anim.DROOP_SQUINT_MIN - 1.0)
            + move_y
            + anim.DROOP_SINK_PX
            - (H - 1 - bottom),
            (bottom - cy) * (v * min(anim.SIGH_DEFLATE, anim.DROOP_SQUINT_MIN) - 1.0)
            + move_y
            + anim.SIGH_SINK_PX
            + anim.DROOP_SINK_PX
            - (H - 1 - bottom),
            # 喷嚏（上窜 + 用力闭上同刻）：压扁把上下都收进来的收益远大于
            # 上窜的风险 —— 上窜按满量、压扁按 SNEEZE_SQUINT_MIN 成对
            # 算（对顶沿）。（下沿只有收益：上窜往上走、不动下边。）
            (cy - top) * (v * anim.SNEEZE_SQUINT_MIN - 1.0) + anim.SNEEZE_LIFT_PX + move_y - top,
            (cx - left) * anim.POP_AMPLITUDE
            + anim.GAZE_MAX_X
            + anim.SWAY_AMPLITUDE
            + anim.SNEEZE_JERK_PX
            + anim.HUM_ROCK_PX
            - left,
            (right - cx) * anim.POP_AMPLITUDE
            + anim.GAZE_MAX_X
            + anim.SWAY_AMPLITUDE
            + anim.SNEEZE_JERK_PX
            + anim.HUM_ROCK_PX
            - (W - 1 - right),
            # 睡梦抽动只在**睡着**时出现：那时微动近乎静止（CALM_FACTOR）、表情也不
            # 再变化（没有弹/淡化 —— 抽动自己 ≥25 秒才有一下，远晚于睡着的瞬间）。
            # 最坏组合 = 定格凝视 + 一激灵，单独一条；不与清醒的 sway/pop 叠加
            # （两者互斥，叠出来是假需求 —— 但若把抽动并进清醒项，那条会超预算）。
            anim.GAZE_MAX_X + anim.TWITCH_SHIFT_PX - left0,
            anim.GAZE_MAX_X + anim.TWITCH_SHIFT_PX - (W - 1 - right0),
            # 入睡的一下同理用原框（旋转只在醒着，与睡时互斥）：下沉与压合
            # 成对算 —— 对下沿取两端的最大净增（满压合 + 满下沉同刻，另加定格
            # 凝视的纵向偏移）；上沿按压合收益 + 定格凝视可能的上抬拼一条。
            (cy - top0) * (v_sleep * anim.DOZEOFF_SQUINT_MIN - 1.0) + anim.GAZE_MAX_Y - top0,
            (bottom0 - cy) * (v_sleep * anim.DOZEOFF_SQUINT_MIN - 1.0)
            + anim.GAZE_MAX_Y
            + anim.DOZEOFF_SINK_PX
            - (H - 1 - bottom0),
        )
        if need > worst[0]:
            worst = (need, f"第 {idx} 张")
    assert worst[0] <= FACE_REGION_PAD, (
        f"最坏形变需要 {worst[0]:.1f}px（{worst[1]}脸），重绘区只留了 {FACE_REGION_PAD}px —— "
        "把 YAWN_STRETCH / SIGH_SINK_PX / NOD_SINK_PX / TWITCH_SHIFT_PX / TILT_MAX_DEG / "
        "WELCOME_LIFT_PX / WELCOME_STRETCH / "
        "SNEEZE_LIFT_PX / HUM_ROCK_PX / DOZEOFF_SINK_PX / DROOP_SINK_PX 调小，"
        "或把 pet.FACE_REGION_PAD 调大"
    )


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_YAWN = 7


def _mk(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留哈欠这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    w.anim = anim.Animator(seed=SEED_YAWN)
    w.look_on = False  # 光标不参与（盯的是哈欠这一件事）
    w.set_expression(9)  # 吐舌：没有动图，画面里动的只有脸自己
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框。

    两条件缺一不可：颜色接近 faces.LIT（从常量读，换配色不用改测试）
    且 **不透明**（alpha ≥ 200）—— 面板描边是半透明白，只看颜色会把它
    当成脸（第一版就栽在这：量到的是整圈边框）。
    """
    from sammy import faces

    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            if a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
    assert x1 >= 0, "clip 里一个亮像素都没有 —— 区域搞错了？"
    return x0, y0, x1, y1


def test_yawn_stretches_the_face_and_settles_back(qapp):
    """scale 1.0 双胞胎：先抻（高 +8px 以上、顶沿上抬），再眯（压到一半以下），收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.yawn(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)

        def look(w: SammyWindow, t: float):
            w.anim_t = t
            return _lit_bbox(w, clip)

        _, y0b, _, y1b = look(b, 8.3)
        _, y0a0, _, y1a0 = look(a, 8.3)
        assert (y0a0, y1a0) == (y0b, y1b), "哈欠开始前两边就该一模一样"
        mid = round(8.5 + anim.YAWN_RISE_S * 0.5, 6)
        _, y0m, _, y1m = look(a, mid)
        tall = round(8.5 + anim.YAWN_RISE_S, 6)  # 刚抻满、还没眯
        x0t, y0t, x1t, y1t = look(a, tall)
        x0bt, y0bt, x1bt, y1bt = look(b, tall)
        shut = round(8.5 + anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S, 6)
        x0s, y0s, x1s, y1s = look(a, shut)
        x0bs, _, x1bs, _ = look(b, shut)  # 只比宽度：高度那两格用不上
        h_mid, h_tall, h_shut = y1m - y0m, y1t - y0t, y1s - y0s
        h_b = y1bt - y0bt
        assert h_tall - h_b >= 8, f"抻起来只高了 {h_tall - h_b}px —— 拉高太小"
        assert h_b < h_mid < h_tall, "抻起来不是渐进的"
        assert y0bt - y0t >= 4, f"顶沿没抬起来：{y0bt - y0t}px"
        assert h_shut <= h_b * 0.5, f"眯眼没眯下去：{h_shut} vs {h_b}"
        assert h_shut >= 25, f"眯得只剩 {h_shut}px —— 这是把脸画没了？"
        assert (x1t - x0t) - (x1bt - x0bt) <= 2, "抻高不该改变宽度（变宽是「飘」不是哈欠）"
        assert (x1s - x0s) - (x1bs - x0bs) <= 2, "眯眼也该只动高度"
        after = round(8.5 + anim.yawn_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "哈欠收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_yawn_key_moments_stay_inside_the_repainted_region(qapp):
    """哈欠的关键两帧（抻最满 / 眯到底）必须落在局部重绘区里 —— 在外面那圈不刷新（会花）。"""
    w = _mk()
    try:
        w.anim.yawn(8.5)
        box = w.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        region = w._face_region()
        for label, t in (
            ("抻最满", round(8.5 + anim.YAWN_RISE_S, 6)),
            ("眯到底", round(8.5 + anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S, 6)),
        ):
            w.anim_t = t
            x0, y0, x1, y1 = _lit_bbox(w, clip)
            deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            assert region.contains(deformed), f"{label} 时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：三条唤醒路各打一次哈欠 ──────────────────


def test_wake_by_itself_schedules_one_yawn(qapp):
    """自己睡饱了醒（_tick 里的作息结算）：醒来那一刻排一次哈欠。"""
    w = _mk()
    try:
        w.drives.asleep = True
        w.drives.energy = 0.9
        w.drives.last_update = time.time() - 2 * 3600  # 睡了两小时 → 自己醒了
        w.anim_t = 33.0
        w._tick()
        assert w.drives.asleep is False, "前提：它该睡饱自己醒"
        assert w.anim._yawn_at == 33.0, "醒来没排哈欠"
    finally:
        w.close()


def test_woken_by_poke_or_message_schedules_one_yawn(qapp):
    """被戳醒 / 被叫醒：同样在醒来那一刻排一次哈欠。"""
    a = _mk()
    try:
        a.drives.asleep = True
        a.drives.energy = 0.5
        a.anim_t = 12.0
        a.poke()
        assert a.drives.asleep is False
        assert a.anim._yawn_at == 12.0, "被戳醒没排哈欠"
    finally:
        a.close()
    b = _mk()
    try:
        b.drives.asleep = True
        b.drives.energy = 0.5
        b.anim_t = 20.0
        b.input.setText("早啊")
        b.send()
        assert b.drives.asleep is False
        assert b.anim._yawn_at == 20.0, "被叫醒没排哈欠"
    finally:
        b.close()


def test_no_yawn_when_awake_or_anim_off(qapp):
    """醒着被戳不排哈欠；动画关着（没有时间轴）连醒来都不打。"""
    a = _mk()
    try:
        a.anim_t = 5.0
        a.poke()
        assert a.anim._yawn_at == -99.0, "醒着被戳也打哈欠？"
    finally:
        a.close()
    b = _mk()
    try:
        b.anim_on = False
        b.drives.asleep = True
        b.drives.energy = 0.9
        b.drives.last_update = time.time() - 2 * 3600
        b.anim_t = 7.0
        b._tick()
        assert b.drives.asleep is False
        assert b.anim._yawn_at == -99.0, "动画关着还排哈欠"
    finally:
        b.close()


# ── 纪律与素材 ────────────────────────────────────


def test_yawn_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "yawn_preview.py").is_file()
    assert "yawn-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("yawn-strip.png", "yawn-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
