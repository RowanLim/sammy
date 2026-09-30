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
from sammy.memory import (  # noqa: E402
    Memory, consolidate_now, extract_and_store, looks_explicit,
    parse_digest, parse_extraction,
)
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

print()
print("═" * 62)
print("4) 记忆 —— 对齐 PRD P0-5「重启后仍记得昵称和至少 3 条关键偏好」")
print("═" * 62)

# 解析器离线健壮性（模型爱加 ```json 包裹、爱说废话）
check("JSON 裹在代码块里",
      parse_extraction('```json\n{"slots":{"a":"b"},"journal":["c"]}\n```'),
      {"slots": {"a": "b"}, "journal": ["c"]})
check("前后有废话",
      parse_extraction('好的，这是结果：{"slots":{},"journal":["他在做 Sammy"]} 完毕'),
      {"slots": {}, "journal": ["他在做 Sammy"]})
check("完全不合法",
      parse_extraction("我记不住"), {"slots": {}, "journal": []})
check("digest 解析",
      parse_digest('{"digest":"今天聊了项目","slots":{"项目":"Sammy"}}'),
      {"digest": "今天聊了项目", "slots": {"项目": "Sammy"}})
check("显式记住被识别", looks_explicit("帮我记住：我只喝美式"), True)
check("闲聊不误判", looks_explicit("今天天气不错"), False)

# 真对话 → 真抽取 → 落库 → 关库 → 重开（模拟重启）
import tempfile  # noqa: E402

tmp_db = pathlib.Path(tempfile.mkdtemp()) / "test_memory.db"
mem = Memory(tmp_db)

exchanges = [
    ("你以后就叫我 Rowan", None),
    ("我最近在做一个桌面机器人项目，叫 Sammy", None),
    ("帮我记住：我喝咖啡只喝美式，不加糖", None),
    ("我不太喜欢太吵的环境", None),
]
print("\n  走 4 轮真实对话，让模型自己判断该记什么：")
for user_text, _ in exchanges:
    r = brain.chat(user_text, mem.context_block())
    info = extract_and_store(brain, mem, user_text, r["reply"])
    print(f"    「{user_text}」→ 槽位 {info['slots']} 条"
          f"{'（显式）' if info['explicit'] else ''}  日记 {info['journal']} 条"
          f"  {info['keys'] if info['keys'] else ''}")

# 关键：关掉再打开 —— 模拟 Sammy 重启
mem.close()
mem2 = Memory(tmp_db)
slots = mem2.slots()
ctx = mem2.context_block()
print(f"\n  重启后重新打开记忆库：{len(slots)} 条槽位")
for k, v in slots.items():
    print(f"    · {k}：{v}")

check("P0-5 槽位 ≥3 条", len(slots) >= 3, True)
check("P0-5 记住了昵称", any("rowan" in str(v).lower() for v in slots.values()), True)
check("P0-5 记住了咖啡偏好",
      any("美式" in str(v) for v in slots.values()), True)
check("记忆能塞进提示词", ("Rowan" in ctx or "rowan" in ctx.lower()), True)

# 显式要求的东西必须留下痕迹（哪怕模型没抽成槽位）
explicit_rows = mem2.day_entries(mem2.stats()["since"] or "", kinds=("explicit",))
check("显式记忆原样留存", len(explicit_rows) >= 1, True)

print(f"\n  提示词片段（{len(ctx)} 字）：")
for line in ctx.splitlines()[:12]:
    print(f"    {line}")

# 夜里整理（真实调用）—— 指定今天，否则默认是整理"昨天"
from datetime import date as _date  # noqa: E402

info = consolidate_now(brain, mem2, _date.today().isoformat())
print(f"\n  夜里整理：{info['entries']} 条事件 → 摘要 {len(info['digest'])} 字，"
      f"新增/更新槽位 {info['new_slots']} 条")
if info["digest"]:
    print(f"    摘要：{info['digest'][:120]}")
check("整理产出了摘要", bool(info["digest"]), True)
check("整理后当天有 digest 标记", mem2.has_digest(info["day"]), True)
mem2.close()

print()
print("═" * 62)
print(f"延迟：最快 {min(lat):.2f}s  最慢 {max(lat):.2f}s  平均 {sum(lat)/len(lat):.2f}s")
print(f"PRD P0-1 标准「3 秒内返回」：{'✅ 通过' if max(lat) < 3.0 else '❌ 未达标'}")
print("═" * 62)

if FAIL:
    print(f"\n❌ 有 {len(FAIL)} 项检查未通过: {FAIL}")
    sys.exit(1)
print("\n✅ 全部通过")
