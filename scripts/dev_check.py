#!/usr/bin/env python
"""M1 自检：解析器健壮性 + 真实对话延迟 + 表情渲染。

用法: .venv/bin/python scripts/dev_check.py
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QPixmap 需要先有 QGuiApplication，离屏渲染也必须建
from PySide6.QtWidgets import QApplication  # noqa: E402

_qt_app = QApplication([])

from sammy.brain import SammyBrain, _canon_emotion  # noqa: E402
from sammy.expressions import name_of  # noqa: E402
from sammy import faces  # noqa: E402

FAIL = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'✅' if ok else '❌'} {label}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAIL.append(label)


print("═" * 62)
print("1) 情绪解析器 —— 含实测踩过的坑")
print("═" * 62)
check("标准格式", SammyBrain._parse("happy\n今天天气真好"), ("happy", "今天天气真好"))
check("模型自创词 sympathetic", SammyBrain._parse("sympathetic\n那就别硬扛了"),
      ("wronged", "那就别硬扛了"))
check("冒号格式", SammyBrain._parse("thinking: 让我想想"), ("thinking", "让我想想"))
check("中文冒号", SammyBrain._parse("smile：好呀"), ("smile", "好呀"))
check("加粗包装", SammyBrain._parse("**giggle**\n嘿嘿"), ("giggle", "嘿嘿"))
check("完全不给标签", SammyBrain._parse("我在这儿呢"), ("normal", "我在这儿呢"))
check("空回复", SammyBrain._parse(""), ("normal", "……"))
check("同义词 confused", _canon_emotion("confused"), "curious")
check("同义词累坏 exhausted", _canon_emotion("exhausted"), "sleepy")
check("中文行不是标签", _canon_emotion("我在这儿呢"), None)

print()
print("═" * 62)
print("2) 表情渲染")
print("═" * 62)
ready = faces.assets_ready()
print(f"  资产目录: {faces.ASSETS_DIR if hasattr(faces, 'ASSETS_DIR') else '?'}  就绪={ready}")
t0 = time.time()
n = faces.preload()
print(f"  预热 {n}/35 张表情，耗时 {time.time() - t0:.2f}s")
crop = faces.content_bounds()
print(f"  统一裁切区域: {crop.x()},{crop.y()} {crop.width()}×{crop.height()}")

print()
print("═" * 62)
print("3) 真实对话（关掉思考链）")
print("═" * 62)
brain = SammyBrain()
probes = [
    "你好，你是谁？",
    "今天好累啊，不想干活，给我点建议",
    "我最近老是睡不好，怎么办",
    "帮我记住：我明天下午三点要开会",
    "推荐一部适合晚上看的电影",
]
lat = []
for text in probes:
    r = brain.chat(text)
    lat.append(r["latency"])
    print(f"  你：{text}")
    print(f"  Sammy[{name_of(r['expression'])}]（{r['latency']:.2f}s）：{r['reply']}")
    print()

print("═" * 62)
print(f"延迟：最快 {min(lat):.2f}s  最慢 {max(lat):.2f}s  平均 {sum(lat)/len(lat):.2f}s")
print(f"PRD P0-1 标准「3 秒内返回」：{'✅ 通过' if max(lat) < 3.0 else '❌ 未达标'}")
print("═" * 62)

if FAIL:
    print(f"\n❌ 有 {len(FAIL)} 项检查未通过: {FAIL}")
    sys.exit(1)
print("\n✅ 全部通过")
