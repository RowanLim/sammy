"""作息与睡相（2026-10-12）—— 「它该有自己的日夜」+「睡着的脸要看得出来是睡着」。

两块都是**看起来小、读起来全是坑**的东西，所以判据要硬：

作息（drives.night_factor）：夜里掉精力快 1.6 倍。错一档就是"大白天蔫着"或
"后半夜精神得像早上"，所以边界（23:00 整 / 07:00 整）逐个钉。

睡相（anim.z_alpha / pet._draw_z）：那个 Z 有一半的坑在**位置**上 ——
画在脸框（局部重绘区域）外面的话，动画帧不会来刷新它：它要么不出现，
要么卡在屏幕上不动。所以除了"睡着有 Z、醒着没 Z"，还要钉：
它落在重绘区域里、而且**每一帧真的在动**（同一个 Z 挪位置 = 活着）。
"""

from __future__ import annotations

import itertools
import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sammy import anim, drives
from sammy.pet import FG, SammyWindow

# ── 作息：夜里掉得更快 ────────────────────────────────


@pytest.mark.parametrize(
    "hour,night",
    [(23, True), (0, True), (3, True), (6, True), (7, False), (12, False), (22, False)],
)
def test_night_window_boundaries(hour, night):
    got = drives.night_factor(hour)
    assert (got > 1.0) is night, f"{hour} 点的夜度是 {got}"


def test_night_drain_is_actually_faster():
    """同一小时，凌晨掉的精力必须比下午多 —— 而且倍数对得上。"""
    t_night = time.mktime(time.strptime("2026-10-12 03:00", "%Y-%m-%d %H:%M"))
    t_day = time.mktime(time.strptime("2026-10-12 15:00", "%Y-%m-%d %H:%M"))
    d_night = drives.Drives(energy=0.8, last_update=t_night)
    d_day = drives.Drives(energy=0.8, last_update=t_day)
    d_night.tick(t_night + 3600)
    d_day.tick(t_day + 3600)
    lost_night = 0.8 - d_night.energy
    lost_day = 0.8 - d_day.energy
    assert lost_night > lost_day, f"夜里掉了 {lost_night:.4f}，白天 {lost_day:.4f} —— 作息没生效"
    assert lost_night == pytest.approx(lost_day * drives.NIGHT_DRAIN_FACTOR, rel=1e-6)


def test_night_does_not_speed_up_sleep_recovery():
    """睡觉是回血 —— 回血不该被"夜里"再放大一次（那是两件不同的事）。"""
    t_night = time.mktime(time.strptime("2026-10-12 03:00", "%Y-%m-%d %H:%M"))
    t_day = time.mktime(time.strptime("2026-10-12 15:00", "%Y-%m-%d %H:%M"))
    a = drives.Drives(energy=0.3, asleep=True, last_update=t_night)
    b = drives.Drives(energy=0.3, asleep=True, last_update=t_day)
    a.tick(t_night + 3600)
    b.tick(t_day + 3600)
    assert a.energy == pytest.approx(b.energy), "回血被作息影响了"


def test_night_makes_it_fall_asleep_sooner_than_day():
    """端到端：同样 3 小时、同样起点的精力，凌晨那 3 小时该把它放倒，白天不该。

    数字是按常数算的（不是拍脑袋）：ENERGY_PER_HOUR_AWAKE = 0.10/h，
    白天 3 小时 -0.30 → 0.20（醒着）；夜里 ×1.6 → -0.48 → 0.02 < 0.12（睡着）。
    """
    t_night = time.mktime(time.strptime("2026-10-12 02:00", "%Y-%m-%d %H:%M"))
    t_day = time.mktime(time.strptime("2026-10-12 11:00", "%Y-%m-%d %H:%M"))
    d_night = drives.Drives(energy=0.50, last_update=t_night)
    d_day = drives.Drives(energy=0.50, last_update=t_day)
    d_night.tick(t_night + 3 * 3600)
    d_day.tick(t_day + 3 * 3600)
    assert d_day.asleep is False, f"白天 3 小时就睡了？掉太快了（剩 {d_day.energy:.2f}）"
    assert d_night.asleep is True, f"凌晨熬 3 小时还没睡？作息没生效（剩 {d_night.energy:.2f}）"


# ── 睡相：Z 的时间线（纯函数） ────────────────────────


def test_z_is_periodic_and_bounded():
    assert anim.z_alpha(0.0) == pytest.approx(anim.z_alpha(anim.Z_PERIOD), abs=1e-9), "不是周期的"
    samples = [anim.z_alpha(i * anim.Z_PERIOD / 40) for i in range(40)]
    assert all(0.0 <= a <= 1.0 for a in samples), "透明度跑到 0..1 外面了"
    assert max(samples) > 0.9, "最亮的时候也亮不起来"
    assert min(samples) < 0.01, "从来没灭过 —— 那就不是'一个一个冒'"


def test_z_fades_in_and_out_within_one_showing():
    """一个 Z 的可见期里：两头暗、中间亮（淡入淡出，不是"啪"地闪）。"""
    n = 12
    span = anim.Z_PERIOD * anim.Z_SHOW_FRAC
    alphas = [anim.z_alpha(span * i / n) for i in range(n)]
    assert alphas[0] < alphas[n // 2] and alphas[n // 2] > alphas[-1], alphas


def test_z_rises_monotonically_then_resets():
    span = anim.Z_PERIOD * anim.Z_SHOW_FRAC
    rises = [anim.z_rise(span * i / 10) for i in range(10)]
    assert all(b >= a for a, b in itertools.pairwise(rises)), f"升得不单调：{rises}"
    assert rises[-1] <= anim.Z_RISE_PX + 1e-9
    assert anim.z_rise(anim.Z_PERIOD * 0.9) == 0.0, "下一个周期之前该归零"


# ── 睡相：真的画在脸上，而且真的在动 ──────────────────


def _win(**kw) -> SammyWindow:
    win = SammyWindow(autoconnect=False, **kw)
    win.resize(800, 480)
    win.scale = 1.0
    win._relayout()
    win.show()
    return win


def _lit_pixels(win: SammyWindow, rect) -> list[tuple[int, int]]:
    """矩形里的"亮像素"（判据从配色常量读，不写死色相）。"""
    from PySide6.QtGui import QImage

    img = win.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    fr, fg, fb = FG.red(), FG.green(), FG.blue()
    pts = []
    for y in range(max(0, rect.top()), min(img.height() - 1, rect.bottom()) + 1):
        for x in range(max(0, rect.left()), min(img.width() - 1, rect.right()) + 1):
            i = y * stride + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]
            if abs(r - fr) < 90 and abs(g - fg) < 90 and abs(b - fb) < 90:
                pts.append((x, y))
    return pts


def _z_box(win: SammyWindow):
    """按 _draw_z 的算法算出 Z 会落在哪（和实现同一条算式，故意不 import 私有方法）。"""
    from PySide6.QtCore import QRect

    box = win.lay.face
    s = win.scale
    size = 36
    w = int(48 * s)
    h = int(size * 1.4 * s)
    x = box.right() - w - int(14 * s)
    y = box.top() + int(8 * s) - int(anim.Z_RISE_PX * s)  # 取最高的那一帧，把整个行程都圈进来
    return QRect(x, y, w, h + int(anim.Z_RISE_PX * s))


def test_z_appears_only_when_asleep(qapp):
    win = _win()
    win.anim_t = anim.Z_PERIOD * 0.25  # 一个 Z 最亮的时刻
    awake = _lit_pixels(win, _z_box(win))
    win.drives.asleep = True
    win.set_expression(1)  # 睡眠脸
    win.anim_t = anim.Z_PERIOD * 0.25
    asleep = _lit_pixels(win, _z_box(win))
    assert len(asleep) > len(awake) + 20, f"睡着没多出 Z：醒 {len(awake)} / 睡 {len(asleep)}"
    win.close()
    assert len(awake) == 0, f"醒着的时候右上角本来就不该有东西（{len(awake)} 像素）"


def test_z_stays_inside_the_repainted_region(qapp):
    """画在重绘区域外面 = 动画帧不会刷新它 = 卡住不动。这条专门钉位置。"""
    win = _win()
    win.drives.asleep = True
    zbox = _z_box(win)
    region = win._face_region()
    assert region.contains(zbox), f"Z 的行程 {zbox} 跑出了重绘区域 {region} —— 它会卡住"
    win.close()


def test_z_actually_moves_between_frames(qapp):
    """同一个 Z 在两帧之间换了位置 —— 证明它真的在被刷新，而不是画上去就不动了。

    采样点选**最亮的两个时刻**（0.22 / 0.40）：淡入淡出期（alpha≈0.5）的像素
    本来就只值半亮，亮像素判据（±90）抓不到它 —— 那是判据的正常边界，不是没画。
    """
    win = _win()
    win.drives.asleep = True
    win.set_expression(1)
    out = []
    for frac in (0.22, 0.40):
        win.anim_t = anim.Z_PERIOD * frac
        out.append(set(_lit_pixels(win, _z_box(win))))
    assert out[0] and out[1], f"两帧都没画出来（{len(out[0])} / {len(out[1])} 像素）"
    moved = len(out[0] ^ out[1])  # 对称差 = 变了多少像素
    assert moved > 10, f"两帧只差 {moved} 像素 —— 它没在动"
    win.close()


def test_anim_off_means_no_z(qapp, monkeypatch):
    """动画总开关关掉时，Z 也不许出现（关就该关彻底）。"""
    monkeypatch.setenv("SAMMY_ANIM", "off")
    win = _win()
    win.anim_on = False  # 环境变量在建窗时读取，这里同时钉住行为
    win.drives.asleep = True
    win.anim_t = anim.Z_PERIOD * 0.25
    assert _lit_pixels(win, _z_box(win)) == [], "动画关着还画 Z"
    win.close()


def test_z_disappears_after_waking(qapp):
    """醒了 Z 就该走 —— 别留在屏幕上（那会变成"卡住"的观感）。"""
    win = _win()
    win.drives.asleep = True
    win.set_expression(1)
    win.anim_t = anim.Z_PERIOD * 0.25
    assert _lit_pixels(win, _z_box(win)), "前提没成立：睡着时没 Z"
    win.drives.asleep = False
    win.set_expression(2)
    assert _lit_pixels(win, _z_box(win)) == [], "醒了 Z 还在"
    win.close()


# ── 纪律与素材 ────────────────────────────────────


def test_doze_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "doze_preview.py").is_file()
    assert "doze-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("doze-strip.png", "doze-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
