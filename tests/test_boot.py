"""开机自检序列（自选小步）的判据 —— 上电扫掠、自检行、唤醒淡入。

为什么这些必须变成数字：

- 时间形状眼睛量不出来：0.55 秒上电、每 0.3 秒一行、0.65 秒淡入。
  快了慢了、少了哪段，只有纯函数能钉住；
- 光标必须真的在闪 —— 一个不闪的光标看着像卡死；
- 整层可关（SAMMY_BOOT=off）：开关语义要和 SAMMY_ANIM / SAMMY_CRT 一套；
- 序列播完得**精确交班**给正常画面：交班后和"从没开过机"的孪生窗口
  逐像素对账（差 0 像素），否则会出现肉眼可见的一跳；
- 自检行里的每个字都必须在像素字体里 —— 屏幕上出现方块就是事故，
  这里拿字体 cmap 逐字审计；
- 开机能被**敲一下跳过**，且这一跳必须落在同一个稳态上。
"""

from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

pytestmark = pytest.mark.usefixtures("qapp")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402

from sammy import boot  # noqa: E402

# ── 夹具 ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _steady(seed=7, face_only=False):
    """稳态窗口：固定种子 + 固定时刻 + 打字机拨到尾（U2/U3 同款做法）。"""
    from sammy import anim
    from sammy.pet import SammyWindow

    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=seed)
    w.set_expression(3)
    w.anim_t = 1.0
    w.finish_typing()
    return w


def _booted(monkeypatch, face_only=False):
    """开了机的窗口（开关显式打开，免得开发机 .env 影响判据）。"""
    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    w = _steady(face_only=face_only)
    assert w.begin_boot() is True
    return w


def _img(w):
    return w.grab().toImage().convertToFormat(QImage.Format_ARGB32)


def _bytes(img):
    return bytes(img.constBits()), img.bytesPerLine()


def _mean_g(img, x0, y0, x1, y1):
    """区域绿通道均值（G 在字节序里是第 2 个：B G R A）。"""
    buf, stride = _bytes(img)
    tot = cnt = 0
    for y in range(y0, y1):
        base = y * stride
        for x in range(x0, x1):
            tot += buf[base + x * 4 + 1]
            cnt += 1
    return tot / cnt


def _lit(img, x0, y0, x1, y1, thr=45):
    """区域内亮绿像素数（游戏规则：绿 channel 超过 thr 算亮）。"""
    buf, stride = _bytes(img)
    n = 0
    for y in range(y0, y1):
        base = y * stride
        for x in range(x0, x1):
            if buf[base + x * 4 + 1] > thr:
                n += 1
    return n


def _lit_rows(img, xc, thr=45):
    """中列带（xc 左右各 4 像素）里亮着的行号（去掉上下边框的描线）。"""
    buf, stride = _bytes(img)
    rows = []
    for y in range(5, img.height() - 5):
        base = y * stride
        tot = 0
        for x in range(xc - 4, xc + 5):
            tot += buf[base + x * 4 + 1]
        if tot / 9.0 > thr:
            rows.append(y)
    return rows


def _diff_where(a, b):
    """两张同尺寸图不一样的像素坐标表。"""
    (ba, sa), (bb, sb) = _bytes(a), _bytes(b)
    out = []
    for y in range(a.height()):
        ra = ba[y * sa : y * sa + a.width() * 4]
        rb = bb[y * sb : y * sb + b.width() * 4]
        for x in range(0, len(ra), 4):
            if ra[x : x + 4] != rb[x : x + 4]:
                out.append((x // 4, y))
    return out


def _diff_count(a, b):
    return len(_diff_where(a, b))


# ── 纯函数层 ───────────────────────────────────────


def test_switch_reads_like_the_other_switches():
    assert boot.boot_enabled({}) is True
    for raw in ("off", "0", "false", "no", "OFF", " off "):
        assert boot.boot_enabled({"SAMMY_BOOT": raw}) is False, raw
    for raw in ("on", "1", "true", "yes", ""):
        assert boot.boot_enabled({"SAMMY_BOOT": raw}) is True, raw


def test_timeline_is_exact():
    n = 6
    assert boot.POWER_DUR == 0.55
    assert boot.LOG_LEAD == 0.12
    assert boot.LINE_STEP == 0.3
    assert boot.LOG_TAIL == 0.4
    assert boot.WAKE_DUR == 0.65
    assert boot.CURSOR_PERIOD == 0.5
    assert boot.log_start() == pytest.approx(0.67)
    assert boot.wake_start(n) == pytest.approx(2.57)
    assert boot.total_seconds(n) == pytest.approx(3.22)
    assert boot.frame_at(0.0, n).phase == "power"
    assert boot.frame_at(boot.POWER_DUR - 1e-6, n).phase == "power"
    assert boot.frame_at(boot.POWER_DUR, n).phase == "log"
    assert boot.frame_at(boot.wake_start(n) - 1e-6, n).phase == "log"
    assert boot.frame_at(boot.wake_start(n), n).phase == "wake"
    assert boot.frame_at(boot.total_seconds(n) - 1e-6, n).phase == "wake"
    assert boot.frame_at(boot.total_seconds(n), n).phase == "done"


def test_power_ramps_from_0_to_1_monotonically():
    vals = [boot.frame_at(t / 50.0 * boot.POWER_DUR, 6).power for t in range(51)]
    assert vals[0] == 0.0
    assert vals[-1] == 1.0
    assert all(b >= a for a, b in pairwise(vals))


def test_lines_appear_one_by_one_and_never_go_back():
    n = 6
    s = boot.log_start()
    assert boot.frame_at(s - 1e-6, n).lines == 0
    assert boot.frame_at(s, n).lines == 1
    assert boot.frame_at(s + boot.LINE_STEP, n).lines == 2
    assert boot.frame_at(boot.wake_start(n) - 1e-6, n).lines == n
    seen = [boot.frame_at(s + i * 0.03, n).lines for i in range(60)]
    assert all(b >= a for a, b in pairwise(seen))


def test_cursor_blinks_on_a_fixed_period():
    assert boot.cursor_on(0.10) is True
    assert boot.cursor_on(0.30) is False
    assert boot.cursor_on(0.60) is True
    assert boot.cursor_on(0.90) is False


def test_wake_fades_in_smoothly():
    n = 6
    ws, tot = boot.wake_start(n), boot.total_seconds(n)
    assert boot.frame_at(ws, n).wake == 0.0
    mid = boot.frame_at((ws + tot) / 2.0, n).wake
    assert 0.45 < mid < 0.55
    assert boot.frame_at(tot - 1e-9, n).wake == pytest.approx(1.0, abs=1e-6)
    assert boot.frame_at(tot, n).wake == 1.0


def test_self_check_lines_report_the_real_numbers():
    lines = boot.self_check_lines(memories=12, expressions=35, tools=3, brain=True)
    assert lines == (
        "SAMMY 个人终端",
        "记忆库 12 条 · 就绪",
        "表情库 35 张 · 就绪",
        "外挂工具 3 个 · 就绪",
        "大脑 · 就绪",
        "自检完成",
    )


def test_self_check_lines_say_what_is_missing_instead_of_lying():
    lines = boot.self_check_lines(memories=None, expressions=35, tools=0, brain=False)
    assert "记忆库 · 未打开" in lines
    assert "外挂工具 · 无" in lines
    assert "大脑 · 未接通" in lines
    lines2 = boot.self_check_lines(memories=0, expressions=35, tools=None, brain=True)
    assert "记忆库 0 条 · 就绪" in lines2
    assert "外挂工具 · 未就绪" in lines2


def test_every_self_check_glyph_is_in_the_pixel_font():
    from fontTools.ttLib import TTFont

    from sammy import layout
    from sammy.paths import fonts_dir

    cmap = TTFont(str(fonts_dir() / layout.PIXEL_FONT_NAME)).getBestCmap()
    variants: list[str] = []
    for mem in (None, 0, 12):
        for tools in (None, 0, 3):
            for brain in (False, True):
                variants.extend(
                    boot.self_check_lines(memories=mem, expressions=35, tools=tools, brain=brain)
                )
    missing = sorted({c for line in variants for c in line if ord(c) not in cmap})
    assert not missing, f"自检行里有字体没有的字形：{missing}"


def test_block_geometry_centers_the_lines():
    panel = QRectF(2.0, 2.0, 796.0, 476.0)
    block = boot.block_rect(panel, 6)
    assert block.center().y() == pytest.approx(panel.center().y(), abs=1.0)
    assert block.top() >= panel.top()
    assert block.bottom() <= panel.bottom()
    r0, r1 = boot.line_rect(block, 0), boot.line_rect(block, 1)
    assert r1.top() - r0.top() == pytest.approx(boot.LINE_H)
    cur = boot.cursor_rect(r0, 100.0)
    assert cur.left() == pytest.approx(r0.left() + 100.0 + boot.CURSOR_GAP)
    assert cur.center().y() == pytest.approx(r0.center().y())


# ── 窗口层 ─────────────────────────────────────────


def test_begin_boot_respects_the_switches(monkeypatch):
    monkeypatch.setenv("SAMMY_BOOT", "off")
    w_off = _steady()
    assert w_off.begin_boot() is False
    assert w_off._boot_t0 is None
    assert w_off._boot_frame() is None
    w_off.close()

    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "off")
    w_anim_off = _steady()
    assert w_anim_off.begin_boot() is False
    w_anim_off.close()

    monkeypatch.setenv("SAMMY_ANIM", "on")
    w_on = _steady()
    assert w_on.begin_boot() is True
    assert w_on._boot_t0 == w_on.anim_t
    assert len(w_on._boot_lines) == 6
    fr = w_on._boot_frame()
    assert fr is not None and fr.phase == "power"
    w_on.close()


def test_begin_boot_hides_the_input_and_finish_brings_it_back(monkeypatch):
    w = _booted(monkeypatch)
    assert w.input.isHidden(), "开机时输入框还露着"
    w._finish_boot()
    assert not w.input.isHidden(), "交班后输入框没回来"
    assert w._boot_t0 is None
    w.close()


def test_power_phase_draws_a_growing_bright_line(monkeypatch):
    w = _booted(monkeypatch)
    t0 = w._boot_t0

    w.anim_t = t0 + 0.06
    early = _img(w)
    assert _mean_g(early, 150, 128, 290, 136) > 60, "中心没有亮线"
    assert _mean_g(early, 150, 40, 290, 48) < 30, "远处居然亮着"
    assert early.pixelColor(0, 0).alpha() == 0, "圆角外漏了"

    w.anim_t = t0 + 0.38
    mid = _img(w)
    rows_e, rows_m = _lit_rows(early, 220), _lit_rows(mid, 220)
    assert len(rows_m) > len(rows_e) * 1.6, (len(rows_e), len(rows_m))
    assert rows_m[0] < rows_e[0], "没往上长"
    assert rows_m[-1] > rows_e[-1], "没往下长"
    w.close()


def test_log_phase_types_the_lines_in(monkeypatch):
    w = _booted(monkeypatch)
    t0 = w._boot_t0

    w.anim_t = t0 + 0.75  # 只出现第一行（标题）
    one = _img(w)
    lit1 = _lit(one, 22, 60, 187, 200)
    assert lit1 > 30, "一行都没画出来"

    w.anim_t = t0 + 1.75  # 四行
    four = _img(w)
    lit4 = _lit(four, 22, 60, 187, 200)
    assert lit4 > lit1 * 1.8, (lit1, lit4)

    # 第六行的位置还是空的（行是一行一行来的）
    assert _lit(four, 22, 172, 187, 186) == 0, "六行一起砸出来了"
    w.close()


def test_cursor_blinks_only_along_its_line(monkeypatch):
    w = _booted(monkeypatch)
    t0 = w._boot_t0

    w.anim_t = t0 + 1.0  # 光标亮（0.5 的整倍：周期前半）
    a = _img(w)
    w.anim_t = t0 + 1.25  # 光标灭
    b = _img(w)

    diffs = _diff_where(a, b)
    assert diffs, "光标没在闪"
    line1 = boot.line_rect(boot.block_rect(QRectF(w.lay.panel), 6), 1)
    y0, y1 = int(line1.top() * w.scale) - 5, int(line1.bottom() * w.scale) + 5
    bad = [p for p in diffs if not (y0 <= p[1] <= y1)]
    assert not bad, f"闪烁影响到了别的行：{bad[:5]}"
    w.close()


def test_boot_never_paints_the_normal_face(monkeypatch):
    w = _booted(monkeypatch)
    calls = []
    orig = w._paint_full
    monkeypatch.setattr(w, "_paint_full", lambda p: (calls.append(1), orig(p))[1])

    w.anim_t = w._boot_t0 + 1.2
    _img(w)
    assert calls == [], "开机阶段画了正常画面"
    w._finish_boot()
    w.anim_t += 0.4
    _img(w)
    assert calls, "交班后正常画面没画出来"
    w.close()


def test_click_skips_boot_and_lands_on_the_steady_frame(monkeypatch):
    booted = _booted(monkeypatch)
    twin = _steady()
    booted.anim_t = booted._boot_t0 + 0.8

    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(220, 132),
        QPointF(220, 132),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    booted.mousePressEvent(ev)
    assert booted._boot_t0 is None, "没跳过"
    assert not booted.input.isHidden()

    # 交班后**立刻**对账：环顾（第二十次）的第一眼在交班 0.35 秒之后才起步，
    # 所以跳过后的下一帧仍该与「从没开过机」的孪生逐像素一致；之后它看一圈
    # 是那之后的事（走位判据在 tests/test_survey.py 里）。
    twin.anim_t = booted.anim_t
    assert _diff_count(_img(booted), _img(twin)) == 0
    booted.close()
    twin.close()


def test_finish_by_the_clock_lands_on_the_same_frame(monkeypatch):
    booted = _booted(monkeypatch)
    twin = _steady()
    booted.anim_t = booted._boot_t0 + boot.total_seconds(6) + 0.05
    booted._anim_tick()  # 这一跳越过终点：应当收尾交班
    assert booted._boot_t0 is None
    assert not booted.input.isHidden()

    twin.anim_t = booted.anim_t
    assert _diff_count(_img(booted), _img(twin)) == 0
    booted.close()
    twin.close()


def test_wake_midpoint_is_a_half_faded_in_frame(monkeypatch):
    booted = _booted(monkeypatch)
    twin = _steady()
    t_mid = booted._boot_t0 + (boot.wake_start(6) + boot.total_seconds(6)) / 2.0
    booted.anim_t = t_mid
    twin.anim_t = t_mid
    faded = booted.grab().toImage()  # 原生预乘口径：淡入就是整体乘系数
    full = twin.grab().toImage()
    assert faded.format() == QImage.Format_ARGB32_Premultiplied
    bf, sf = _bytes(faded)
    bu, su = _bytes(full)

    # 只看脸框以内：那是纯painter画的内容；输入框是子控件，不受这段透明度影响
    box = twin.lay.face
    x0, x1 = int(box.left() * twin.scale) + 2, int(box.right() * twin.scale) - 2
    y0, y1 = int(box.top() * twin.scale) + 2, int(box.bottom() * twin.scale) - 2
    ratios = []
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            j = y * su + x * 4
            if bu[j + 3] > 200 and bu[j + 1] > 120:
                ratios.append(bf[y * sf + x * 4 + 1] / bu[j + 1])
    assert len(ratios) > 50, "找不到足够亮的稳态像素"
    ratios.sort()
    med = ratios[len(ratios) // 2]
    assert 0.44 < med < 0.56, med
    booted.close()
    twin.close()


def test_faceonly_boot_also_works(monkeypatch):
    fo = _booted(monkeypatch, face_only=True)
    fo.anim_t = fo._boot_t0 + 1.2
    img = _img(fo)
    assert _lit(img, 0, 0, img.width(), img.height()) > 30
    fo._finish_boot()
    assert fo.input.isHidden(), "face-only 的输入框该从头藏到尾"
    fo.close()


# ── 集成与素材 ─────────────────────────────────────


def test_only_the_run_path_and_the_previews_may_start_the_boot():
    """开机序列只许三处触发：真启动路径 + 两个开机相关素材脚本。

    别的入口（快照、自检、其余素材脚本）一律不许调 —— 否则拍到的
    素材会带着开机画面，验收就说不清哪张是"稳态"。第二个素材脚本是
    上电环顾（第二十次）：它拍的就是「自检交班之后」的收尾，必须真开机。
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = {p.name for p in (root / "src").rglob("*.py") if ".begin_boot(" in _read(p)}
    assert hits == {"__main__.py"}, hits
    scripts = {p.name for p in (root / "scripts").rglob("*.py") if ".begin_boot(" in _read(p)}
    assert scripts == {"boot_preview.py", "survey_preview.py"}, scripts
    assert ".begin_boot(" in _read(root / "tests" / "test_boot.py")


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def test_run_path_skips_boot_for_selftest():
    src = _read(pathlib.Path(__file__).resolve().parent.parent / "src" / "sammy" / "__main__.py")
    assert "win.begin_boot()" in src
    assert "if not args.selftest:" in src, "自检路径不许播开机（不然截图全废）"


def test_media_and_script_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "boot_preview.py").is_file()
    assert "boot-media" in _read(root / "Makefile")
    for name in ("boot-strip.png", "boot-zoom.png", "boot-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
