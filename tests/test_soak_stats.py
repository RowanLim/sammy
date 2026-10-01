"""压测报告里的统计量也要测 —— 错的分位数比不报还糟。

起因：跑出来的报告里出现了 `p90 0.808 < p50 1.551`。
一眼就不可信的数字，会让人连整份报告一起不信。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from soak import percentile


def test_p90_is_never_below_p50():
    """这条就是那个 bug 本身：样本少时 p90 一度比 p50 还小。"""
    for n in range(1, 40):
        values = [float(i) for i in range(n)]
        assert percentile(values, 0.9) >= percentile(values, 0.5), f"n={n} 时 p90 < p50"


def test_percentiles_stay_inside_the_sample():
    """分位数必须落在实际采样到的值上 —— 不能凭空造出一个数来。"""
    values = [1.0, 5.0, 3.0]
    for q in (0.0, 0.1, 0.5, 0.9, 1.0):
        assert percentile(values, q) in values


def test_small_samples_are_handled():
    assert percentile([], 0.9) == 0.0
    assert percentile([2.0], 0.9) == 2.0
    assert percentile([1.0, 2.0], 0.9) == 2.0
    assert percentile([1.0, 2.0], 0.5) == 1.0


def test_p90_is_the_near_top_value():
    values = [float(i) for i in range(10)]  # 0..9
    assert percentile(values, 0.9) == 8.0
    assert percentile(values, 1.0) == 9.0
