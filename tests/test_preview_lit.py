"""四个旧素材脚本的「亮像素」判据与 faces.LIT 对齐 —— 钉住，不再写死色相。

背景（DEVLOG「第九次小步」的记账）：talk / carry / look / report_8h 四个素材脚本
里「找脸像素」的判据把荧光绿写死过（g > 80 and 2*r 那一套）。2026-10-12 前景
由荧光绿改白之后，重跑它们一个像素都匹配不上、静默出错误数字（脚本不报错）。
2026-10-13 对齐为从 faces.LIT 读色（report_8h 另加 alpha 口径），这里把它钉住：

1. 行为：四个脚本的 _is_lit 认 faces.LIT、不认旧荧光绿、半透明描边不算亮；
2. 源码：不许再出现旧绿色判据的字面写法（防手滑挪回去）；
3. 顺带：_is_lit 必须真被用上（只定义不调用 = 死代码）。

注意：导入预览脚本会执行其模块级代码（建 QApplication、注册字体、把 SAMMY_* 置 on），
导入前后把环境变量原样恢复，别把整个测试会话的口径改了。不带窗口，不写文件。
"""

from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

_CACHE: dict[str, object] = {}


def _load(name: str):
    """把 scripts/<name>.py 当模块加载（缓存一次）；导入期间的 os.environ 原样恢复。"""
    if name in _CACHE:
        return _CACHE[name]
    saved = dict(os.environ)
    try:
        spec = importlib.util.spec_from_file_location(
            "_sammy_preview_" + name, SCRIPTS / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    _CACHE[name] = mod
    return mod


@pytest.mark.parametrize("name", ["talk_preview", "carry_preview", "look_preview"])
def test_rgb_previews_accept_lit_and_reject_the_old_green(name):
    """三个 RGB32 口径的脚本：认 faces.LIT；旧荧光绿 / 深底都不认。"""
    from sammy import faces

    mod = _load(name)
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    is_lit = mod._is_lit
    assert is_lit(lr, lg, lb) is True, f"{name} 连 faces.LIT 都不认"
    assert is_lit(61, 220, 90) is False, f"{name} 还在认旧荧光绿（又写死色相了？）"
    assert is_lit(10, 18, 13) is False, f"{name} 把深底像素当成了脸"
    assert is_lit(217, 217, 217) is True, f"{name} 对扫描线压暗一格的亮像素过于严格"


def test_report_8h_stats_require_opaque_pixels():
    """report_8h 的体检口径：认 faces.LIT；半透明（alpha 小于 200）不算。"""
    from sammy import faces

    mod = _load("report_8h_media")
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    is_lit = mod._is_lit
    assert is_lit(lr, lg, lb, 255) is True
    assert is_lit(lr, lg, lb, 200) is True
    assert is_lit(lr, lg, lb, 35) is False, "半透明面板描边被当成了脸描线"
    assert is_lit(61, 220, 90, 255) is False, "还在认旧荧光绿"


def test_no_hardcoded_green_left_in_the_four_scripts():
    """源码扫一遍：旧绿色判据不许复活；判据必须读 faces.LIT；不许只定义不调用。"""
    banned = ("g > 80", "green() > 120")
    for name in ("talk_preview", "carry_preview", "look_preview", "report_8h_media"):
        src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        for frag in banned:
            assert frag not in src, f"{name} 里还留着写死的绿色判据：{frag!r}"
        assert "faces.LIT" in src, f"{name} 的亮像素判据没从 faces.LIT 读"
        assert src.count("_is_lit(") >= 2, f"{name} 的 _is_lit 像死代码"
