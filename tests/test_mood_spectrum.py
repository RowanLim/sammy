"""心情的**全谱**：两根轴（好坏 + 劲头）合起来才是一个「谱」。

为什么这些判据要写死：
- **两根轴不许互相代理**。加第二根轴最大的风险是「顺手让它也改 `valence`」——
  那会动到「没人理也不许低于 FLOOR」和「默认表情钉死在心情上」两条已有的判据。
  所以有一组判据专门盯着：推劲头，`valence` 与 `idle_expression` 一个数都不许变。
- **负面格子不许说出好听的话**。低落 + 有劲最容易写成「还挺兴奋的」——
  陪伴产品在这上面翻车过一次（变成情感绑架），所以规则要**扫全表**，不是手抄一份对照。
- **谱是满的**。5 x 5 每格都得有名字、少一格就是「有的心情它说不出话来」。
- **`label()` 不许被换掉**。`describe()`（`--mood`）才用全谱名字；
  `label()` 在 pet.py 与多份判据里被读，换了就是无声改口径。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import mood as M

# ── 第二根轴：推 ──────────────────────────────────


@pytest.mark.parametrize("expr", sorted(M.LIVELY_EXPRS))
def test_a_lively_face_gets_it_going(expr):
    assert M.spirit_nudge(0.0, expr) > 0.0


@pytest.mark.parametrize("expr", sorted(M.DULL_EXPRS))
def test_a_dull_face_winds_it_down(expr):
    assert M.spirit_nudge(0.0, expr) < 0.0


@pytest.mark.parametrize("expr", [2, 13, 27, 30, 29])
def test_a_neutral_face_leaves_it_alone(expr):
    assert M.spirit_nudge(0.0, expr) == 0.0


def test_a_quiet_smile_is_not_the_same_as_getting_excited():
    """「平静的开心」不算热闹 —— 否则它一直在高位，等于常量。"""
    assert M.spirit_nudge(0.0, 3) == 0.0  # 微笑
    assert M.spirit_nudge(0.0, 21) > 0.0  # 爱心（这是热闹）
    assert M.spirit_nudge(0.0, 10) == 0.0, "生气是往下那根轴的事，不该代理成没劲"


def test_spirit_is_clamped_both_ways():
    v = 0.95
    for _ in range(20):
        v = M.spirit_nudge(v, 34)
    assert v <= 1.0
    v = -0.95
    for _ in range(20):
        v = M.spirit_nudge(v, 1)
    assert v >= -1.0


def test_a_single_reply_only_moves_spirit_partway():
    assert 0 < M.spirit_nudge(0.0, 21) < 0.3


# ── 实在没意思的时候自己往下走 ────────────────────


def test_being_alone_only_winds_down_after_the_same_gate():
    assert M.spirit_alone(0.3, M.ALONE_AFTER_H) == 0.3
    assert M.spirit_alone(0.3, M.ALONE_AFTER_H + 4.0) < 0.3


def test_being_alone_never_winds_down_forever():
    deep = M.spirit_alone(0.0, 200.0)
    assert deep >= -1.0
    assert M.spirit_alone(deep, 400.0) == deep, "到底了就不再往下（有地板）"


# ── 谱本身：两根轴合起来 ──────────────────────────


def test_the_spectrum_is_full():
    """5 x 5 every cell must be named."""
    values = (-0.5, -0.25, -0.05, 0.0, 0.15, 0.3, 0.55, 1.0)
    spirits = (-1.0, -0.5, 0.0, 0.5, 1.0)
    for v in values:
        for s in spirits:
            assert M.spectrum_label(v, s).strip()


def test_the_same_cell_can_name_two_different_moods():
    """加第二根轴的意义就在这儿：好坏一样、劲头不同，说出来的话不一样。"""
    assert M.spectrum_label(0.15, 0.6) != M.spectrum_label(0.15, -0.6)
    assert M.spectrum_label(-0.1, -0.6) != M.spectrum_label(-0.1, 0.6)


def test_home_is_not_called_plain():
    """基线 0.15 是略偏正面，不该被叫「平静」。"""
    assert M.spectrum_label(M.HOME, 0.0) == "还行"
    assert "平静" not in M.spectrum_label(M.HOME, 0.0)


def test_every_name_in_the_table_can_actually_be_reached():
    """**表里写的每个词都得真的用得上。**

    这条是被一个真 bug 逼出来的：第一版谱写成 if 阶梯，用位置索引取分档，
    结果「偏活」那一档被算进了别的档、成了死代码 —— 表里有名字、判据也绿
    （那条只查「有没有名字」），但那个词**永远轮不到**。
    所以判据要往两边都扫：表里每个词都至少有一组 (心情, 劲头) 能选中它。
    """
    seen = set()
    for v in [i / 100 for i in range(-50, 101)]:
        for s in [i / 100 for i in range(-100, 101)]:
            seen.add(M.spectrum_label(v, s))
    for row in M.SPECTRUM:
        for name in row:
            assert name in seen, f"表里写着「{name}」，但没有一组 (心情, 劲头) 能选中它"


def test_the_table_is_read_with_spirit_as_the_row():
    """The lookup orientation is pinned: row = spirit, col = mood."""
    col = M.band_of(0.0)
    assert M.spectrum_label(0.0, -1.0) == M.SPECTRUM[0][col]
    assert M.spectrum_label(0.0, 1.0) == M.SPECTRUM[4][col]
    assert M.spectrum_label(0.0, -1.0) != M.spectrum_label(0.0, 1.0)


def test_the_spectrum_table_has_no_holes():
    """The table itself is 5 x 5 and full."""
    assert len(M.SPECTRUM) == 5
    for row in M.SPECTRUM:
        assert len(row) == 5
        for name in row:
            assert name.strip()


def test_the_bands_agree_with_label_of():
    """band_of and label_of never disagree."""
    seen = []
    for i in range(-500, 1001):
        v = i / 1000.0
        if not seen or seen[-1] != M.label_of(v):
            seen.append(M.label_of(v))
    boundaries = []
    for i in range(-500, 1001):
        v = i / 1000.0
        b = M.band_of(v)
        if not boundaries or boundaries[-1] != b:
            boundaries.append(b)
    assert len(seen) == 5
    assert boundaries == [0, 1, 2, 3, 4]


def test_the_flat_spirit_lands_in_the_middle_band():
    """0.0 is the middle (normal) band."""
    assert M.spirit_band_of(0.0) == 2
    assert M.spirit_band_of(0.5) > M.spirit_band_of(0.0)
    assert M.spirit_band_of(-0.5) < M.spirit_band_of(0.0)
    assert M.spectrum_label(M.HOME, 0.0) == "\u8fd8\u884c"


def test_a_middle_spirit_adds_nothing_to_the_prompt():
    assert M.spirit_hint(M.HOME, 0.0) is None
    assert M.spirit_hint(M.HOME, 0.3) is None
    assert M.spirit_hint(M.HOME, -0.3) is None


def test_a_high_spirit_and_a_low_spirit_read_differently():
    up = M.spirit_hint(0.4, 0.8)
    down = M.spirit_hint(0.4, -0.8)
    assert up and down and up != down
    assert up not in down


def test_the_old_prompt_line_never_mentions_spirit():
    """老那行由第一根轴单独决定 —— 劲头不许混进去（不然老判据全红）。"""
    for s in (-1.0, -0.5, 0.0, 0.5, 1.0):
        assert M.prompt_line(0.4, None) == "你今天的心情：不错（可以稍微轻快一点）"
        hint = M.spirit_hint(0.4, s)
        if hint:
            assert hint not in M.prompt_line(0.4, None)


def test_the_prompt_keeps_saying_mood_first():
    line = "\n".join([M.prompt_line(0.4, ["聊得挺开心"]), M.spirit_hint(0.4, -0.8) or ""])
    assert line.startswith("你今天的心情：不错")
    assert line.count("你今天的心情") == 1


# ── 落盘：还是一个数 ──────────────────────────────


def test_only_the_mood_is_written_down(tmp_path):
    """劲头是算出来的，不进文件 —— 少一个要迁移的字段就少一类故障面。"""
    t = M.MoodTracker(path=tmp_path / "mood.json", now=1000.0)
    t.save()
    keys = set(t.mood.as_dict())
    assert keys == {"valence", "updated", "notes"}
    assert "spirit" not in keys


def test_spirit_still_shows_up_in_describe(tmp_path):
    t = M.MoodTracker(path=tmp_path / "mood.json", now=1000.0)
    t.mood.notes = [M.NOTE_LIVELY]
    text = t.describe(now=1000.0)
    assert "劲头" in text
    assert "valence" not in text, "给人看的话里不许出现变量名"


def test_an_old_mood_file_still_loads(tmp_path):
    """旧文件（没有劲头这个概念）读出来照样能用。"""
    p = tmp_path / "mood.json"
    p.write_text('{"valence": -0.2, "updated": 500.0, "notes": ["有点不痛快"]}', encoding="utf-8")
    t = M.MoodTracker(path=p, now=1000.0)
    assert t.mood.valence == pytest.approx(-0.2)
    # 心情是负的，但事由（notes）不在「热闹/没劲」那两类里 —— 劲头就该在平常位
    assert t.spirit(now=1000.0) == pytest.approx(0.0)
    assert "劲头" in t.describe(now=1000.0)
