"""打字机显示 + 思考指示（第二轮 U3）—— 先写判据，实现对着判据做。

为什么这些必须变成数字（肉眼判不了）：

- 打字机是**时间形状**：「每字 40 毫秒、标点后多停 90 毫秒、整段超 4.5 秒就整体加速」——
  盯着屏幕根本说不出快慢对不对；
- 思考点是每 0.4 秒换一帧的循环 —— 看单张截图永远看不出「它动不动」；
- 「第一遍逐字打、第二遍起循环不再重打」「动画关着必须瞬间给全句」这类**边界**，
  不写断言就会踩坑（U2 的教训：动画关着时淡化永久停在第一帧）。

分两层：
- 纯函数层（typewriter.py）：出字速度、标点停顿、上限加速、点循环、翻页时间表；
- 渲染层（真窗口离屏抓图）：回复区真的先少后多、思考点真的在长、face-only 那一行
  也逐字、以及「抓图前拨到尾」的 finish_typing 真的管用。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import typewriter as tw

pytestmark = pytest.mark.usefixtures("qapp")

# ── 纯函数：打字机 ────────────────────────────────────


def test_first_char_is_immediate_and_step_is_40ms():
    """第一个字立刻出现，之后每字 40 毫秒（25 字/秒）—— 速度是钉死的数字，不是感觉。"""
    times = tw.char_times("一二三四五六七八九十")
    assert times[0] == 0.0, "第一个字必须立刻出现（不许先空一拍）"
    assert times == pytest.approx([i * 0.04 for i in range(10)], abs=1e-9)


def test_punctuation_waits_pause_then_resumes():
    """标点之后多停 90 毫秒 —— 断句感来自这里，不是玄学。

    停的是**标点后面那个字**（句号自己不许迟到）。
    """
    plain = tw.char_times("啊啊啊")
    paused = tw.char_times("啊。啊")
    assert paused[2] - plain[2] == pytest.approx(tw.TYPE_PAUSE, abs=1e-9)
    assert paused[1] - plain[1] == pytest.approx(0.0, abs=1e-9)
    # 逗号同理
    comma = tw.char_times("啊，啊")
    assert comma[2] - plain[2] == pytest.approx(tw.TYPE_PAUSE, abs=1e-9)


def test_reveal_is_always_a_prefix_and_only_grows():
    """屏幕上出现的永远是已打出的前缀，而且只增不减 —— 不许跳字、不许回退。"""
    text = "先别硬撑，喝口水，跟我唠两句也行。"
    seen = 0
    for i in range(300):
        shown = tw.reveal(text, i * 0.02)
        assert text.startswith(shown), f"t={i * 0.02:.2f} 露出的不是前缀：{shown!r}"
        assert len(shown) >= seen
        seen = len(shown)
    assert tw.reveal(text, 999.0) == text
    assert tw.reveal("", 5.0) == ""


def test_short_text_never_touches_the_cap():
    assert tw.reveal_seconds("") == 0.0
    assert tw.reveal_seconds("短") == 0.0
    text = "你好"
    assert tw.reveal_seconds(text) == pytest.approx(0.04, abs=1e-9)
    assert tw.reveal_seconds(text) < tw.TYPE_CAP


def test_long_text_finishes_within_the_cap_and_accelerates():
    """一页最长打 4.5 秒：超了必须整体加速 —— 打字机不许变成让人干等的理由。"""
    long = "啊" * 400
    assert tw.reveal_seconds(long) == pytest.approx(tw.TYPE_CAP, abs=1e-6)
    assert tw.reveal(long, tw.TYPE_CAP) == long, "4.5 秒时必须整段可见"
    half = tw.visible_count(long, tw.TYPE_CAP / 2)
    assert abs(half - 200) <= 6, f"加速后中点应在半程附近，实际出了 {half} 字"
    # 没到上限的长度：原速，不动
    just_fit = "啊" * 100
    assert tw.reveal_seconds(just_fit) == pytest.approx(99 * 0.04, abs=1e-9)


def test_dots_grow_and_loop_every_400ms():
    """思考点：1 个点长到 3 个再循环，每 0.4 秒一帧 —— 「在动」是它的全部工作。

    回复区用大点（●），正文行用小点（·）；两套共用这一条时间轴。
    """
    assert tw.dots(0.0) == "●"
    assert tw.dots(0.39) == "●"
    assert tw.dots(0.4) == "●●"
    assert tw.dots(0.79) == "●●"
    assert tw.dots(0.8) == "●●●"
    assert tw.dots(1.19) == "●●●"
    assert tw.dots(1.2) == "●", "1.2 秒（三帧整）必须回到第一帧"
    assert tw.dots(tw.DOT_PERIOD * 3) == "●"
    assert tw.dots(-5.0) == "●", "坏时间不许崩（负数夹到 0）"
    for i in range(30):  # 任何时刻都非空 —— 思考中不许有「什么都没显示」的瞬间
        assert tw.dots(i * 0.1) in {"●", "●●", "●●●"}
    # 正文那一行的小点：同一时间轴，另一套字符
    assert tw.dots(0.8, tw.DOT_FRAMES_TEXT) == "···"


def test_grow_dots_replaces_the_dead_ellipsis():
    """状态行句尾的「…」换成会动的点（没有「…」就直接接上）。"""
    assert tw.grow_dots("思考中…", 0.0) == "思考中·"
    assert tw.grow_dots("思考中…", 0.4) == "思考中··"
    assert tw.grow_dots("思考中…", 0.8) == "思考中···"
    assert tw.grow_dots("正在上网查…", 0.4) == "正在上网查··"
    assert tw.grow_dots("在线", 0.4) == "在线··"


# ── 纯函数：翻页 + 打字的时间表 ────────────────────────


def test_plan_single_page_types_then_stays():
    plan = tw.TypePlan(("甲乙丙丁",))
    assert plan.view_at(0.0) == (0, "甲")
    assert plan.view_at(0.05) == (0, "甲乙")
    assert plan.view_at(1.0) == (0, "甲乙丙丁")
    assert plan.view_at(999.0) == (0, "甲乙丙丁"), "单页没有「循环」，打完就停在那儿"


def test_plan_flips_after_type_plus_hold_and_loops_with_full_pages():
    """第一遍：打 + 停，然后翻页；第二遍起：按同样节奏循环，但**不再重打**。"""
    p0, p1 = "甲" * 10, "乙" * 10
    plan = tw.TypePlan((p0, p1), hold=3.6)
    typed = 9 * 0.04  # 10 个字：最后一个在 0.36 秒出现
    slot = typed + 3.6
    assert plan.loop == pytest.approx(slot * 2, abs=1e-9)
    assert plan.view_at(0.35)[1] == "甲" * 9, "第一遍中途只该有一半"
    assert plan.view_at(slot - 0.1) == (0, p0), "第一页打完且停够了才翻"
    assert plan.view_at(slot + 0.05) == (1, "乙乙"), "翻页后第二页又从头逐字"
    assert plan.view_at(slot + slot - 0.1) == (1, p1)
    assert plan.view_at(plan.loop + 0.5) == (0, p0), "第二遍循环：整页直接给，不重打"
    assert plan.view_at(plan.loop + slot + 0.5) == (1, p1)


def test_plan_first_pass_never_shows_more_than_typed_so_far():
    """第一遍里，屏幕上永远是当前页已打出的前缀 —— 提前露尾巴就是穿帮。"""
    pages = ("先别硬撑，喝口水，跟我唠两句也行。", "另一页的话")
    plan = tw.TypePlan(pages)
    for i in range(int(plan.loop * 100)):
        idx, text = plan.view_at(i * 0.01)
        assert pages[idx].startswith(text)


def test_plan_is_deterministic():
    pages = ("甲" * 30, "乙" * 25)
    p1, p2 = tw.TypePlan(pages), tw.TypePlan(pages)
    for t in (0.0, 0.5, 1.3, 4.0, 9.9, 30.0):
        assert p1.view_at(t) == p2.view_at(t)


def test_plan_hold_defaults_to_layouts_page_seconds():
    """默认停留 = layout.PAGE_SECONDS：两份常量不许各自漂移。"""
    from sammy import layout

    assert tw.PAGE_HOLD == layout.PAGE_SECONDS


# ── 渲染层：真窗口离屏抓图 ────────────────────────────
# （纯函数说「该这么动」，这里说「屏幕上真的动了」—— 两码事。）

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

TEXT_LINE = "先别硬撑，喝口水，跟我唠两句也行。"
LIT_MIN = 300  # 「亮像素」判据：r+g+b 超过它才算文字（背景 ~30，灰绿边框 ~124）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_gaze 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


@pytest.fixture
def win(qapp):
    from sammy import layout
    from sammy.pet import SammyWindow

    layout.load_fonts()  # 和真机一致：量文字像素必须用像素字体（不然字距是回落的）
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()  # 时间轴由测试自己拨（不给定时器抢）
    yield w
    w.close()


@pytest.fixture
def win_fo(qapp):
    from sammy import layout
    from sammy.pet import SammyWindow

    layout.load_fonts()  # 和真机一致
    w = SammyWindow(face_only=True, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    yield w
    w.close()


def _rect_px(win_, r: QRect) -> QRect:
    """设备坐标的版面矩形 → 窗口像素矩形。"""
    s = win_.scale
    return QRect(
        int(r.x() * s) + win_._offset[0],
        int(r.y() * s) + win_._offset[1],
        int(r.width() * s),
        int(r.height() * s),
    )


def _lit_count(win_, r: QRect) -> int:
    """区域里「亮像素」的个数 —— 文字亮、底暗，个数随露出的字数走。"""
    img = win_.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())  # [B,G,R,A]（macOS 实测）—— 立刻拷贝，别持视图
    stride = img.bytesPerLine()
    clip = _rect_px(win_, r).intersected(QRect(0, 0, img.width(), img.height()))
    n = 0
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            if buf[i] + buf[i + 1] + buf[i + 2] > LIT_MIN:
                n += 1
    return n


def _prep_typing(w, text=TEXT_LINE):
    """把窗口摆成「刚好开始回这句话」的样子，返回后第一次抓图 = 打字机起步。"""
    w.my_line = ""
    w.status = "在线 · 1.8s"
    w.sammy_line = text
    w.anim_t = 0.0


def test_window_typing_reveals_progressively(win):
    """回复区：先少后多，最后打满 —— 逐字出现是整个 U3 的主句。"""
    w = win
    _prep_typing(w)
    early = _lit_count(w, w.lay.reply)  # 第一眼：刚起头
    w.anim_t = 0.4
    mid = _lit_count(w, w.lay.reply)
    w.anim_t = 20.0
    late = _lit_count(w, w.lay.reply)
    assert 0 < early < mid < late, f"逐字出现没发生：{early} → {mid} → {late}"
    assert mid < late * 0.75, f"中段应该明显没打完：mid={mid} late={late}"


def test_finish_typing_gives_the_whole_sentence_immediately(win):
    """抓图路径：finish_typing 之后哪怕 anim_t 还停在 0，也必须是一整句。"""
    w = win
    _prep_typing(w)
    w.finish_typing()
    one_shot = _lit_count(w, w.lay.reply)
    w.anim_t = 20.0
    full = _lit_count(w, w.lay.reply)
    assert one_shot > 0
    assert one_shot == full, "拨到尾之后打出的画面必须和稳态一模一样"


def test_typing_steady_state_equals_flush(win):
    """打完之后画面 == 拨到尾的画面：打字机只是过程，不是另一种终态。"""
    w = win
    _prep_typing(w)
    _lit_count(w, w.lay.reply)  # 第一眼把打字机起步定住
    w.anim_t = 20.0
    steady = _lit_count(w, w.lay.reply)
    w.finish_typing()
    assert _lit_count(w, w.lay.reply) == steady


def test_anim_off_shows_the_full_sentence_without_a_timeline(win):
    """SAMMY_ANIM=off：没有时间轴，打字机会永远停在第一个字 —— 必须瞬间整句。

    （U2 踩过的同款坑：淡化在动画关着时永远停在第一帧。同一条教训，这里是判据。）
    """
    w = win
    w.anim_on = False
    w.anim_timer.stop()
    _prep_typing(w)
    shown = _lit_count(w, w.lay.reply)
    w.anim_t = 20.0
    assert _lit_count(w, w.lay.reply) == shown
    assert shown > 0


def test_thinking_shows_growing_dots_instead_of_a_dead_ellipsis(win):
    """思考中：回复区和状态行都换成会动的点，而且真的随 anim_t 长大。"""
    w = win
    w.thinking = True
    w.status = "思考中…"
    w.sammy_line = "……"
    w.my_line = ""
    w.anim_t = 0.0
    d1 = _lit_count(w, w.lay.reply)
    w.anim_t = 0.4
    d2 = _lit_count(w, w.lay.reply)
    w.anim_t = 0.8
    d3 = _lit_count(w, w.lay.reply)
    assert 0 < d1 < d2 < d3, f"思考点没在长：{d1} / {d2} / {d3}"
    # 状态行也动：两个时刻的状态行裁片必须不同
    w.anim_t = 0.0
    crop0 = w.grab().toImage().copy(_rect_px(w, w.lay.status))
    w.anim_t = 0.4
    crop1 = w.grab().toImage().copy(_rect_px(w, w.lay.status))
    assert bytes(crop0.constBits()) != bytes(crop1.constBits()), "状态行的点没动"


def test_faceonly_line_also_types(win_fo):
    """face-only 那一行：它刚说的话也逐字出现（小屏同样是这台老机器）。"""
    w = win_fo
    w.anim_t = 0.0
    w.sammy_line = TEXT_LINE
    w._hold_line()
    early = _lit_count(w, w.lay.status)
    w.anim_t = 0.4
    mid = _lit_count(w, w.lay.status)
    w.anim_t = 20.0
    late = _lit_count(w, w.lay.status)
    assert 0 < early < mid < late, f"那一行没逐字：{early} → {mid} → {late}"


def test_faceonly_line_returns_to_status_on_time(win_fo, monkeypatch):
    """20 秒一到，那一行该回到状态 —— 要有一次「到点重画」，不能赖着不走。

    那一行平时不在动画的刷新范围里（动画只刷脸）。不给「到点重画」这一下，
    时间到了画面还停在旧文字上 —— FACEONLY_LINE_HOLD 就只是个没人看的时间戳。
    """
    from PySide6.QtTest import QTest

    from sammy import pet as pet_mod

    monkeypatch.setattr(pet_mod, "FACEONLY_LINE_HOLD", 0.2)
    w = win_fo
    w.status = "在线 · 0.5s"
    w.sammy_line = "刚说完的一句"
    w._hold_line()
    assert w.face_line()[1] is True, "刚说完：那一行该是它的话"
    calls: list[tuple] = []
    orig = w.update

    def rec(self, *a, **k):
        calls.append(a)
        return orig(*a, **k)

    monkeypatch.setattr(type(w), "update", rec)
    QTest.qWait(500)  # 走过 0.2 秒的停留 + 余量
    assert w.face_line()[1] is False, "到点了，face_line 该回状态"
    assert any(a and isinstance(a[0], QRect) for a in calls), "到点没有重画（画面会赖在旧文字上）"


def test_text_region_covers_status_and_reply(win):
    """文字区刷新的范围必须真的盖住状态行和回复区两个矩形。"""
    r = win._text_region()
    assert r.contains(_rect_px(win, win.lay.status))
    assert r.contains(_rect_px(win, win.lay.reply))


def test_anim_tick_repaints_the_text_while_typing_then_stops(win, monkeypatch):
    """打字机在打时，动画每帧要多刷「文字区」；打完之后只刷脸（省电）。"""
    w = win
    _prep_typing(w)
    _lit_count(w, w.lay.reply)  # 第一眼把打字机起步定住（惰性起步）
    calls: list[tuple] = []
    orig = w.update

    def rec(self, *a, **k):
        calls.append(a)
        return orig(*a, **k)

    monkeypatch.setattr(type(w), "update", rec)
    w._anim_tick()
    assert any(a and isinstance(a[0], QRect) and a[0] == w._text_region() for a in calls), (
        "正在打字，动画却没有刷新文字区（字会卡住不出现）"
    )
    assert any(a and isinstance(a[0], QRect) and a[0] == w._face_region() for a in calls)
    calls.clear()
    w.anim_t = 100.0  # 远超一轮（打字 + 停留）
    w._anim_tick()
    assert calls == [(w._face_region(),)], f"打完之后还在刷文字区：{calls}"
