"""回复区排版：缩字号、翻页、不裁字。

这一组的存在理由：用户第一眼看到的问题就是**"话说到一半没了"**。
旧实现从 26 试到 18，全放不下时照样用 18 往框里硬画，`drawText` 悄悄裁掉多余部分 ——
没有报错、没有提示，只有"这句话怎么没说完"。
所以这里钉的不是"能显示"，而是**"每一页都必须真的放得下"**。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontMetrics

from sammy import layout

pytestmark = pytest.mark.usefixtures("qapp")

BOX = QRect(46, 324, 708, 70)  # 设计尺寸（800×480）上的回复区
SHORT = "嗯，我在。"
MEDIUM = "我趴在你桌面边上看着你呢。刚才那事儿我想了想，你要是拿不准就先做最简单的版本。"
LONG = (
    "我趴在你桌面边上看着你呢。刚才那事儿我想了想 —— 你要是拿不准，就先做那个最简单的版本，"
    "做完给我看，我帮你挑毛病。别一上来就想把什么都做全，那样最容易卡住。"
    "还有啊，你昨天说要早点睡，结果又熬到两点。这个我可记着呢。"
    "今天要是有空，把那个小屏的事推进一下，我就能搬过去住了。"
) * 3


def _height(text: str, size: int) -> int:
    return (
        QFontMetrics(QFont(layout.FAMILY, size))
        .boundingRect(BOX, layout.REPLY_FLAGS, text)
        .height()
    )


def test_short_reply_uses_the_biggest_size():
    fit = layout.fit_reply(SHORT, BOX)
    assert fit.size == layout.REPLY_SIZES[0], "短句没必要缩小"
    assert fit.pages == (SHORT,) and not fit.paged


def test_medium_reply_shrinks_instead_of_paging():
    """能靠缩小放下就别翻页 —— 翻页是最后手段。"""
    fit = layout.fit_reply(MEDIUM, BOX)
    assert not fit.paged, "这句话缩小就该放得下"
    assert fit.size <= layout.REPLY_SIZES[0]
    assert fit.pages == (MEDIUM,), "没缩够时不能偷偷丢字"
    assert _height(MEDIUM, fit.size) <= BOX.height()


def test_long_reply_never_overflows():
    """核心承诺：**每一页都真的放得下**（旧实现在这里就是裁字）。"""
    fit = layout.fit_reply(LONG, BOX)
    assert fit.paged, "这么长的回复必须翻页"
    assert len(fit.pages) >= 2
    for i, page in enumerate(fit.pages):
        assert _height(page, fit.size) <= BOX.height(), f"第 {i + 1} 页放不下（会被裁）"


def test_paging_does_not_lose_text():
    """翻页只是分屏：**一个字都不许丢**（丢了就是另一种截断）。"""
    fit = layout.fit_reply(LONG, BOX)
    assert "".join(fit.pages).replace(" ", "") == LONG.replace(" ", "")


def test_pages_start_at_one_and_cycle():
    fit = layout.fit_reply(LONG, BOX)
    assert fit.page_at(0.0) == fit.pages[0], "新回复必须从第 1 页开始"
    assert fit.index_at(0.0) == 0
    assert fit.page_at(layout.PAGE_SECONDS * 1.5) == fit.pages[1]
    # 翻完一圈要回到开头，不能停在最后一页
    assert fit.page_at(layout.PAGE_SECONDS * len(fit.pages) + 0.1) == fit.pages[0]


def test_single_page_never_advances():
    """一页能放完就不该出现"第 2 页"。"""
    fit = layout.fit_reply(SHORT, BOX)
    for t in (0.0, 5.0, 100.0):
        assert fit.page_at(t) == SHORT
        assert fit.index_at(t) == 0


def test_empty_reply_is_not_an_error():
    fit = layout.fit_reply("", BOX)
    assert fit.pages == ("",) and not fit.paged


def test_tiny_box_does_not_hang():
    """区域小到放不下一个字也要能返回（死循环比截断更糟）。"""
    fit = layout.fit_reply("很长的一段话" * 20, QRect(0, 0, 20, 10))
    assert fit.paged and len(fit.pages) > 1
