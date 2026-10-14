"""待机省电（自选小步·第二十二次）——「你走了，屏幕慢慢暗下去；你回来，亮回来」。

动机：欢迎回来（第二十一次）管的是你回来**那一下**；你走了以后屏幕还一直
亮得像有人在用 —— 一台老终端没人理的时候是会省的。这一条：光标静够十分钟
（和休息提醒、欢迎回来同一把尺子）= 你走了，整块屏幕慢慢暗下去（2.5 秒，
沉下去）；你回来又亮回来（1.1 秒，快 —— 屏幕比它的脸醒得还急一点）。

四层判据（和 test_dozeoff / test_welcome 一个框架）：
1. 纯函数：两条缓动曲线逐点钉死、重复喂同一电平是空操作、连续反悔不跳、
   确定性；paint_dim 的黑度换算与面板裁剪；
2. 窗口链路：真信号链（_anim_tick 到 _poll_cursor 到 _note_presence 到 _away
   到 _standby_step）—— 慢慢暗、到点全暗、回来单调亮回来；被拎着不算、开局 /
   退场不算、动画关 / 光标功能关不算、睡着照样省电（但不叠着演欢迎）；
3. 渲染（真窗口离屏抓图）：暗区 = 整块面板（脸 / 状态行 / 输入框里的文字一起
   暗，比例 = 1 - STANDBY_DIM_MAX）、面板外一个像素不碰、档位 0 与对照逐字节
   一致、CRT 开着也照常；
4. 纪律与素材：站定不整层重刷、档位在动就刷；素材一条命令可重生成、真在仓库里。

（设计数字：STANDBY_ 三个常量在 standby.py 顶部；调参速查表第 32 节。）
"""

from __future__ import annotations

import itertools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim, standby

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

FADE_FRAMES = round(standby.STANDBY_FADE_S / anim.ANIM_DT) + 4
RISE_FRAMES = round(standby.STANDBY_RISE_S / anim.ANIM_DT) + 4


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_welcome 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


# ── 纯函数层：常量、曲线、换算 ──────────────────────


def test_standby_constants_are_sane():
    """常量的量级与相互关系：亮回来比暗下去快；「你走了」的尺子远长于淡入。"""
    assert 0.10 <= standby.STANDBY_DIM_MAX <= 0.40, "暗得太少看不见、太多像熄屏"
    assert 1.0 <= standby.STANDBY_FADE_S <= 6.0, "暗下去该是慢慢沉，不是咔一下"
    assert 0.5 <= standby.STANDBY_RISE_S <= 3.0, "亮回来该是快快醒，不是赖床"
    assert standby.STANDBY_RISE_S < standby.STANDBY_FADE_S, "亮回来要比暗下去快"
    # 走到全暗必然完成：「你走了」的尺子（和欢迎回来共用）远长于淡入
    assert anim.WELCOME_AWAY_S > standby.STANDBY_FADE_S * 10


def test_standby_fade_shape_point_by_point():
    """暗下去：逐点钉死（走的那一刻 0、半程一半、到点满、之后一直满）；单调不减。"""
    d = standby.StandbyDim()
    assert d.level(0.0) == 0.0, "刚生出来就该是亮的"
    assert d.away is False
    d.note_away(10.0, True)
    fade = standby.STANDBY_FADE_S
    assert d.level(10.0) == 0.0, "走的那一刻还是全亮（从这里起算）"
    assert d.level(10.0 + fade / 2) == pytest.approx(0.5), "半程该是一半"
    assert d.level(10.0 + fade) == 1.0, "到点该是全暗"
    assert d.level(10.0 + fade + 300.0) == 1.0, "之后一直是全暗"
    up = [d.level(10.0 + i * 0.01) for i in range(round(fade / 0.01) + 1)]
    assert all(b >= a for a, b in itertools.pairwise(up)), "暗下去不是单调的"


def test_standby_rise_shape_point_by_point():
    """亮回来：从全暗出发（回来这一刻还是全暗，不跳）；到点精确 0；单调不增。"""
    d = standby.StandbyDim()
    d.note_away(10.0, True)
    rise = standby.STANDBY_RISE_S
    d.note_away(20.0, False)
    assert d.level(20.0) == 1.0, "回来这一刻还是全暗（从当下出发）"
    assert d.level(20.0 + rise / 2) == pytest.approx(0.5), "半程该是一半"
    assert d.level(20.0 + rise) == 0.0, "到点该精确归零"
    assert d.level(20.0 + rise + 300.0) == 0.0, "之后一直是全亮"
    down = [d.level(20.0 + i * 0.01) for i in range(round(rise / 0.01) + 1)]
    assert all(b <= a for a, b in itertools.pairwise(down)), "亮回来不是单调的"


def test_standby_second_cycle_starts_fresh():
    """走 -> 回 -> 又走：第二轮的淡入从全亮重新起算（不是接着上一轮）。"""
    d = standby.StandbyDim()
    d.note_away(0.0, True)
    d.note_away(10.0, False)
    assert d.level(20.0) == 0.0
    d.note_away(30.0, True)
    fade = standby.STANDBY_FADE_S
    assert d.level(30.0) == 0.0, "第二轮没有从头起算"
    assert d.level(30.0 + fade / 2) == pytest.approx(0.5)
    assert d.level(30.0 + fade) == 1.0


def test_standby_reversal_does_not_jump():
    """连续反悔不跳：半暗时「回来」、半亮时「又走」—— 从当下档位出发。"""
    d = standby.StandbyDim()
    d.note_away(0.0, True)
    t1 = 1.2  # 半暗附近
    before = d.level(t1)
    d.note_away(t1, False)  # 反悔：回来了
    assert d.level(t1) == before, "回来的那一刻档位跳了"
    t2 = 1.5
    before2 = d.level(t2)
    d.note_away(t2, True)  # 又走了
    assert d.level(t2) == before2, "又走的那一刻档位跳了"


def test_standby_same_signal_is_a_noop():
    """同一电平反复喂是空操作 —— 起点不许被一遍遍往后拨（淡入永远走不完）。"""
    d = standby.StandbyDim()
    d.note_away(0.0, True)
    assert d.level(1.25) == pytest.approx(0.5, abs=0.05)  # 半暗
    for t in (1.25, 1.3, 2.0):  # 重复喂 True：不重置起点
        d.note_away(t, True)
    assert d.level(1.25) == pytest.approx(0.5, abs=0.05), "起点被往后拨了"
    d.note_away(10.0, False)  # 回来（这时早已全暗）
    assert d.level(10.0) == 1.0
    for t in (10.2, 10.5, 11.0):  # 重复喂 False：不许把回来时刻往后拨
        d.note_away(t, False)
    assert d.level(10.0 + standby.STANDBY_RISE_S) == 0.0, "回来时刻被往后拨了"


def test_standby_is_deterministic():
    """同一条序列跑两遍逐值相等（没有随机、没有隐藏状态）。"""

    def run():
        d = standby.StandbyDim()
        out = []
        for i in range(0, 500):
            t = round(i * 0.05, 6)
            if t == 5.0:
                d.note_away(t, True)
            if t == 12.0:
                d.note_away(t, False)
            if t == 16.0:
                d.note_away(t, True)
            out.append(round(d.level(t), 12))
        return out

    assert run() == run()


def test_paint_dim_covers_only_the_panel(qapp):
    """黑度换算（档位乘上 DIM_MAX）与面板裁剪：圆角以外一个像素不碰；0 不画。"""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QImage, QPainter

    img = QImage(120, 120, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    standby.paint_dim(
        p, level=1.0, panel=QRect(20, 20, 80, 80), panel_radius=10, scale=1.0, offset=(0, 0)
    )
    p.end()
    full = round(standby.STANDBY_DIM_MAX * 255)
    assert img.pixelColor(60, 60).alpha() == full
    assert img.pixelColor(5, 5).alpha() == 0, "面板外被蒙了"
    assert img.pixelColor(15, 60).alpha() == 0, "面板外（左边）被蒙了"
    assert img.pixelColor(22, 22).alpha() <= 2, "圆角外被蒙了（抗锯齿边只许一丝）"
    assert img.pixelColor(25, 25).alpha() > 0, "圆角以内该暗"
    img2 = QImage(120, 120, QImage.Format_ARGB32)
    img2.fill(Qt.transparent)
    p = QPainter(img2)
    standby.paint_dim(
        p, level=0.0, panel=QRect(20, 20, 80, 80), panel_radius=10, scale=1.0, offset=(0, 0)
    )
    p.end()
    assert img2.pixelColor(60, 60).alpha() == 0, "档位 0 还画了东西"


def test_dim_overlay_paints_only_when_dark(qapp):
    """蒙层控件：档位 0 一个字不画；落档位变才重刷；半档黑度减半。"""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    ov = standby.DimOverlay()
    ov.resize(120, 120)
    ov.set_context(panel=QRect(20, 20, 80, 80), panel_radius=10, scale=1.0, offset=(0, 0))
    assert ov.level() == 0.0
    img = ov.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    assert img.pixelColor(60, 60).alpha() == 0
    assert ov.set_level(1.0) is True
    assert ov.set_level(1.0) is False, "同一档位不该重刷"
    img = ov.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    assert img.pixelColor(60, 60).alpha() == round(standby.STANDBY_DIM_MAX * 255)
    assert img.pixelColor(5, 5).alpha() == 0
    assert ov.set_level(0.5) is True
    img = ov.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    assert img.pixelColor(60, 60).alpha() == round(0.5 * standby.STANDBY_DIM_MAX * 255)
    assert ov.set_level(0.0) is True
    assert ov.set_level(2.0) is True and ov.level() == 1.0, "档位往外该夹住"
    assert ov.set_level(-1.0) is True and ov.level() == 0.0


# ── 窗口链路：真信号链（光标静 -> 你走了 -> 省电）────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_STANDBY = 7


def _mk() -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「待机省电」一个变量。

    眨眼请出去（600 秒才眨一次）：抓图对账时脸必须干净。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w._sync_crt_layer()
    w._sync_dim_overlay()
    w.anim = anim.Animator(seed=SEED_STANDBY, blink_gap=(600.0, 600.0))
    w.set_expression(2)  # 普通脸：画面里动的只有呼吸 / 漂移
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.anim_on = True
    w.look_on = True
    return w


class _FakeCursor:
    """可拖动的假光标：位置用「相对脸中心」的设备像素表示。"""

    def __init__(self, win: SammyWindow):
        self.win = win
        self.dx = -400.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))


def _step(w: SammyWindow):
    """推进一帧（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def _arm_away(w: SammyWindow) -> None:
    """把「最近一次有人碰鼠标」往回拨十分钟 —— 模拟「你离开了」。"""
    w._presence_at = w.anim_t - (anim.WELCOME_AWAY_S + 1.0)


def _dim_fully(w: SammyWindow) -> None:
    """走真链路让它暗到全暗 —— 之后才能接着验「回来」。"""
    _arm_away(w)
    _step(w)
    assert w._away is True, "前提不成立：没安上「你走了」"
    for _ in range(FADE_FRAMES):
        _step(w)
    assert w._dim_overlay.level() == 1.0, "前提不成立：没暗到全暗"


def test_window_dims_slowly_after_you_leave(qapp):
    """真信号链：光标静够十分钟（= 你走了）之后，屏幕**慢慢**暗下去、到点全暗。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)  # 建立参照
        assert w._dim_overlay.level() == 0.0, "还没走就暗了"
        _arm_away(w)
        _step(w)
        assert w._away is True, "十分钟没人碰，没安上「你走了」"
        assert w._dim_overlay.level() == 0.0, "刚走就暗了？它是慢慢沉的"
        lv = [w._dim_overlay.level()]
        for _ in range(FADE_FRAMES):
            _step(w)
            lv.append(w._dim_overlay.level())
        assert all(b >= a for a, b in itertools.pairwise(lv)), "暗下去不是单调的"
        assert lv[1] < 1.0, "第一帧就全暗了？"
        assert w._dim_overlay.level() == 1.0, "到点没暗到全暗"
        n_full = next(i for i, v in enumerate(lv) if v == 1.0)
        assert abs(n_full * anim.ANIM_DT - standby.STANDBY_FADE_S) <= anim.ANIM_DT + 0.01, (
            f"暗到全暗用了 {n_full} 帧，和 FADE_S 对不上"
        )
        for _ in range(8):  # 站定之后保持全暗
            _step(w)
        assert w._dim_overlay.level() == 1.0
    finally:
        w.close()


def test_window_brightens_on_return_with_welcome(qapp):
    """你回来：屏幕亮回来（快）+ 欢迎回来同拍抬头；到点精确归零。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _dim_fully(w)
        cur.dx = -360.0  # 你碰了鼠标
        _step(w)
        assert w.anim._welcome_at == w.anim_t, "回来没抬头（欢迎没同拍）"
        assert w._dim_overlay.level() == 1.0, "回来这一刻档位该还在顶（从当下出发）"
        lv = [w._dim_overlay.level()]
        for _ in range(RISE_FRAMES):
            _step(w)
            lv.append(w._dim_overlay.level())
        assert all(b <= a for a, b in itertools.pairwise(lv)), "亮回来不是单调的"
        assert w._dim_overlay.level() == 0.0, "到点没亮回来"
        n_back = next(i for i, v in enumerate(lv) if v == 0.0)
        assert abs(n_back * anim.ANIM_DT - standby.STANDBY_RISE_S) <= anim.ANIM_DT + 0.01, (
            f"亮回来用了 {n_back} 帧，和 RISE_S 对不上"
        )
    finally:
        w.close()


def test_window_drag_keeps_the_screen_awake(qapp):
    """被拎着不算离开（手就在它身上）：屏幕先亮回来；松手后欢迎照常排。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _dim_fully(w)
        w._drag = QPoint(5, 5)  # 拎起来了（拖动开始）
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "被拎着屏幕还黑着"
        assert w._away is True, "拿起来的手不算「回来」—— 那次离开不该被消费"
        assert w.anim._welcome_at == -99.0, "拎着的时候不该演欢迎"
        w._drag = None
        cur.dx = -300.0  # 放下来，手又动了
        _step(w)
        assert w._away is False, "松手后该被消费"
        assert w.anim._welcome_at == w.anim_t, "松手后的第一次动该欢迎"
    finally:
        w.close()


def test_window_standby_works_while_asleep(qapp):
    """睡着不挡省电：屏还是慢慢暗下去；睡着回来屏幕亮回来但不演欢迎（走哈欠那条边）。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        w.drives.asleep = True
        _dim_fully(w)
        cur.dx = -360.0  # 睡着时你回来了
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "睡着的回来屏幕没亮回来"
        assert w.anim._welcome_at == -99.0, "睡着还「欢迎回来」（该走哈欠那条边）"
    finally:
        w.close()


def test_window_standby_gates(qapp):
    """闸门：动画关 / 光标功能关 / 开局 / 退场都不省电；中途关掉要亮回来。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        # 动画关：连检测都没有（_note_presence 直接返回）—— 不省电
        w.anim_on = False
        _step(w)
        _arm_away(w)
        _step(w)
        assert w._away is False and w._dim_overlay.level() == 0.0, "动画关着还省电"
        # 正暗着的时候把动画关掉：亮回来（关就关彻底）
        w.anim_on = True
        _step(w)
        _dim_fully(w)
        w.anim_on = False
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "动画关了屏幕还黑着"
        # 光标功能关着：连读都不读 —— 不省电（_away 可能还挂着前几段的底：
        # 它留着没关系，看的是效果 —— 屏必须一直亮着）
        w.anim_on = True
        w.look_on = False
        _step(w)
        _arm_away(w)
        for _ in range(10):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "SAMMY_LOOK 关了还省电"
        # 正暗着的时候把光标功能关掉：亮回来
        w.look_on = True
        _step(w)
        _dim_fully(w)
        w.look_on = False
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "光标功能关了屏幕还黑着"
        # 开局：演出时间屏幕亮着（暗着进开局也要亮回来）；出来之后人没回来就接着省
        w.look_on = True
        _step(w)
        _dim_fully(w)
        w._boot_t0 = w.anim_t
        w._boot_lines = ("· 一条", "· 两条")
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0, "开局里屏幕该亮着"
        w._boot_t0 = None
        w._boot_lines = ()
        assert w._away is True, "前提不成立：人还没回来"
        for _ in range(FADE_FRAMES + 10):
            _step(w)
        assert w._dim_overlay.level() == 1.0, "开局出来、人还没回来：省电该接着走"
        # 你回来了：亮回来（顺带消费掉「你走了」）
        cur.dx = -360.0
        for _ in range(RISE_FRAMES):
            _step(w)
        assert w._dim_overlay.level() == 0.0
        assert w._away is False
        # 退场：也亮着（只看趋势，别走到播完把退出交出去）
        _dim_fully(w)
        w._shutdown_t0 = w.anim_t
        lv0 = w._dim_overlay.level()
        for _ in range(10):
            _step(w)
        assert w._dim_overlay.level() < lv0, "退场里屏幕还黑着"
        w._shutdown_t0 = None
    finally:
        w.close()


def test_window_standby_screen_repaints_only_while_moving(qapp, monkeypatch):
    """站定之后不整层刷（省电）；档位在动才刷（跟得上）。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _dim_fully(w)
        ups = []
        monkeypatch.setattr(w._dim_overlay, "update", lambda *a: ups.append(a))
        for _ in range(8):
            _step(w)
        assert ups == [], "站定之后还在整层重刷"
        cur.dx = -360.0  # 回来：档位在动
        for _ in range(5):
            _step(w)
        assert ups, "档位在动却不刷 —— 蒙层会跟不上"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _face_clip(w: SammyWindow) -> QRect:
    """扫描区：脸框横向外扩 60，纵向只到 y=239 —— 状态行不许进来。"""
    box = w.lay.face
    return QRect(box.left() - 60, 4, box.width() + 120, 236)


def _ratio(a: SammyWindow, b: SammyWindow, clip: QRect, floor: int = 120) -> tuple[float, int]:
    """以对照 b 为准挑亮像素，量 a 里它们变暗的比例（期望 1 - STANDBY_DIM_MAX）。"""
    ia = a.grab().toImage().convertToFormat(QImage.Format_RGB32)
    ib = b.grab().toImage().convertToFormat(QImage.Format_RGB32)
    ba, bb = bytes(ia.constBits()), bytes(ib.constBits())
    sa, sb = ia.bytesPerLine(), ib.bytesPerLine()
    vals = []
    for y in range(clip.top(), clip.bottom() + 1):
        for x in range(clip.left(), clip.right() + 1):
            i = x * 4
            gb = bb[y * sb + i + 1]
            ga = ba[y * sa + i + 1]
            if gb >= floor:
                vals.append(ga / gb)
    assert len(vals) >= 100, f"亮像素太少（{len(vals)}）—— 区域选错了？"
    return sum(vals) / len(vals), len(vals)


def test_standby_dims_everything_in_the_panel_and_spares_nothing_inside(qapp):
    """全暗 vs 对照：脸 / 状态行 / 输入框里的文字一起按 1 - DIM_MAX 变暗；归零无残留。"""
    a, b = _mk(), _mk()
    try:
        a.input.setText("测试输入")
        b.input.setText("测试输入")
        assert _img_bytes(a) == _img_bytes(b), "前提不成立：两边不同帧"
        a._dim_overlay.set_level(1.0)
        want = 1.0 - standby.STANDBY_DIM_MAX
        r_face, _ = _ratio(a, b, _face_clip(a))
        assert r_face == pytest.approx(want, abs=0.02), f"脸没按预期变暗：{r_face}"
        st = a.lay.status
        r_text, _ = _ratio(a, b, QRect(20, st.top(), 760, 34))
        assert r_text == pytest.approx(want, abs=0.03), f"状态行没按预期变暗：{r_text}"
        inp = a.lay.input
        r_in, _ = _ratio(a, b, QRect(inp.left(), inp.top(), inp.width(), inp.height()))
        assert r_in == pytest.approx(want, abs=0.03), f"输入框里的文字没被蒙住：{r_in}"
        a._dim_overlay.set_level(0.0)
        assert _img_bytes(a) == _img_bytes(b), "档位归零后还有残留"
    finally:
        a.close()
        b.close()


def test_standby_dim_never_leaves_the_panel(qapp):
    """窗口是透明浮窗：面板圆弧以外（角上那几圈）一个像素都不许碰。"""
    a = _mk()
    try:
        img0 = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        a._dim_overlay.set_level(1.0)
        img1 = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        for x, y in ((0, 0), (3, 3), (4, 4), (6, 6), (a.width() - 1, 0), (0, a.height() - 1)):
            c0 = img0.pixelColor(x, y)
            c1 = img1.pixelColor(x, y)
            assert c0.getRgb() == c1.getRgb(), (
                f"({x},{y}) 被蒙层碰了：{c0.getRgb()} -> {c1.getRgb()}"
            )
    finally:
        a.close()


def test_standby_works_with_crt_on_too(qapp, monkeypatch):
    """CRT 开着（生产观感）也照常省电：比例还是 1 - DIM_MAX；档位 0 与对照一致。"""
    monkeypatch.setenv("SAMMY_CRT", "on")
    a, b = _mk(), _mk()
    try:
        assert a.crt_on is True and a._crt_overlay is not None
        assert _img_bytes(a) == _img_bytes(b), "前提不成立：两边不同帧"
        a._dim_overlay.set_level(1.0)
        r_face, _ = _ratio(a, b, _face_clip(a))
        assert r_face == pytest.approx(1.0 - standby.STANDBY_DIM_MAX, abs=0.03), (
            f"CRT 开着时没按预期变暗：{r_face}"
        )
        a._dim_overlay.set_level(0.0)
        assert _img_bytes(a) == _img_bytes(b), "档位归零后还有残留（CRT 开着）"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ────────────────────────────────────


def test_standby_is_wired_into_the_tuning_doc_and_checklist():
    """调参速查表要有「待机省电」一节并点到 standby.py；对账测试钉住三个常量。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "docs" / "TUNING.md").read_text(encoding="utf-8")
    assert "待机省电" in text, "速查表缺「待机省电」一节"
    assert "standby.py" in text, "速查表没点 standby.py"
    pin_text = (root / "tests" / "test_tuning_doc.py").read_text(encoding="utf-8")
    for name in ("STANDBY_DIM_MAX", "STANDBY_FADE_S", "STANDBY_RISE_S"):
        assert name in pin_text, f"速查表对账里没钉 {name}"


def test_standby_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "standby_preview.py").is_file()
    assert "standby-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("standby-strip.png", "standby-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
