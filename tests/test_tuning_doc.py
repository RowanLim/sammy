"""调参速查表（docs/TUNING.md）的判据：纸上写的 = 代码里跑的。

为什么要有：8 小时报告里 6 个待拍板点，答案基本都是「调一个数」。
速查表如果指错文件、或写着旧值，Rowan 照着改就白忙一轮 —— 所以
这里把「文档里确实写的」和「代码里确实跑的」钉在一起：

1. 文档里每个「NAME = 数字」的常量，必须真在某个 sammy 模块里、值一致；
2. 钉住的常量集合就是约定好的那一组（多一个少一个都要显式改这里）；
3. 六个拍板点的小节与对应文件名一个不缺；
4. face-only 的派生数字（660×324 / 屏宽占比 / 倍数）与真算出来的布局一致；
5. MCP 的三个版本号与代码一致；
6. 报告（REPORT-8H.md）指到这页；
7. 第二轮（UI）的第 8~11 节与新增常量同样逐条对账；
8. 第 12 节（开机自检序列）与 boot.py 的 6 个时间常量逐条对账；
9. 第 13 节（关机序列）的 7 个常量同样逐条对账；
10. 第 14 节（光标凝视）的 3 个常量同样逐条对账。
11. 第 15 节（搬运凝视）的 3 个常量同样逐条对账。
12. 第 16 节（说话动脸）的 5 个常量同样逐条对账。
13. 第 18 节（醒来的哈欠）的 9 个常量同样逐条对账。
14. 第 19 节（无聊的叹气）的 8 个常量同样逐条对账。
15. 第 20 节（困得点头）的 7 个常量同样逐条对账。
16. 第 21 节（打字凝视）的 3 个常量同样逐条对账。
17. 第 22 节（睡梦抽动）的 7 个常量同样逐条对账。
18. 第 23 节（思考凝视）的 2 个常量同样逐条对账。
19. 第 24 节（摸摸头）的 6 个常量同样逐条对账。
20. 第 25 节（打个喷嚏）的 10 个常量同样逐条对账。
21. 第 26 节（哼小曲）的 9 个常量同样逐条对账。
22. 第 27 节（歪头）的 4 个常量同样逐条对账。
23. 第 28 节（好奇歪头）的 4 个常量同样逐条对账。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TUNING = DOCS / "TUNING.md"
REPORT = DOCS / "REPORT-8H.md"

# 文档里允许（也必须）出现的「常量 = 数字」全集。
EXPECTED_PINS = {
    "HOME",
    "HALF_LIFE_H",
    "FLOOR",
    "NUDGE",
    "POKE_NUDGE",
    "ALONE_AFTER_H",
    "ALONE_RATE",
    "MAX_RECALLS_PER_DAY",
    "ITEM_COOLDOWN_DAYS",
    "SAID_WINDOW_HOURS",
    "ELIGIBLE_AFTER_HOURS",
    "ELIGIBLE_BEFORE_DAYS",
    "MAX_RAPID_CRASHES",
    "GAVE_UP_CODE",
    "BACKOFF_BASE_S",
    "BACKOFF_MAX_S",
    "FACEONLY_LINE_HOLD",
    "FO_CLOSE_CLEAR",
    "FO_TOP",
    "FO_GAP",
    "FO_STATUS_H",
    "SCANLINE_PERIOD",
    "SCANLINE_ALPHA",
    "VIGNETTE_ALPHA",
    "VIGNETTE_INNER",
    "GLOW_OPACITY",
    "GLOW_DOWNSCALE",
    "PIXEL_STEP",
    "TYPE_CPS",
    "TYPE_PAUSE",
    "TYPE_CAP",
    "DOT_PERIOD",
    "PAGE_HOLD",
    "GAZE_MIN_GAP",
    "LOOK_MOVE_MIN",
    "LOOK_HOLD_S",
    "LOOK_RETARGET_MIN_S",
    "GAZE_MAX_GAP",
    "GAZE_EASE",
    "GAZE_MAX_X",
    "GAZE_MAX_Y",
    "CURIOSITY_STRETCH",
    "FADE_DURATION",
    "POP_DURATION",
    "POWER_DUR",
    "LOG_LEAD",
    "LINE_STEP",
    "LOG_TAIL",
    "WAKE_DUR",
    "CURSOR_PERIOD",
    "COLLAPSE_DUR",
    "LINE_DUR",
    "DOT_DUR",
    "SQUEEZE_MIN",
    "SHRINK_MIN",
    "DOT_SHRINK",
    "CORE_H",
    "CARRY_GAIN",
    "CARRY_MOVE_MIN",
    "CARRY_RETARGET_MIN_S",
    "TALK_PERIOD",
    "TALK_BOB_Y",
    "TALK_SQUASH",
    "TALK_EASE_IN",
    "TALK_EASE_OUT",
    "YAWN_RISE_S",
    "YAWN_HOLD_S",
    "YAWN_SETTLE_S",
    "YAWN_STRETCH",
    "YAWN_LIFT_PX",
    "YAWN_SQUINT_DELAY_S",
    "YAWN_SQUINT_RISE_S",
    "YAWN_SQUINT_FALL_S",
    "YAWN_SQUINT_MIN",
    "SIGH_BOREDOM_ABOVE",
    "SIGH_MIN_GAP",
    "SIGH_MAX_GAP",
    "SIGH_SINK_S",
    "SIGH_HOLD_S",
    "SIGH_RISE_S",
    "SIGH_DEFLATE",
    "SIGH_SINK_PX",
    "NOD_MIN_GAP",
    "NOD_MAX_GAP",
    "NOD_SAG_S",
    "NOD_HOLD_S",
    "NOD_SNAP_S",
    "NOD_SQUINT_MIN",
    "NOD_SINK_PX",
    "PET_DWELL_S",
    "PET_EASE_IN_S",
    "PET_EASE_OUT_S",
    "PET_PURR_PERIOD",
    "PET_PURR_PX",
    "PET_SQUINT_MIN",
    "SNEEZE_BURST_S",
    "SNEEZE_HOLD_S",
    "SNEEZE_JERK_PX",
    "SNEEZE_LIFT_PX",
    "SNEEZE_MAX_GAP",
    "SNEEZE_MIN_GAP",
    "SNEEZE_SETTLE_S",
    "SNEEZE_SQUINT_MIN",
    "SNEEZE_WINDUP",
    "SNEEZE_WINDUP_S",
    "HUM_EASE_IN_S",
    "HUM_EASE_OUT_S",
    "HUM_MAX_GAP",
    "HUM_MIN_GAP",
    "HUM_MOOD_ABOVE",
    "HUM_NOTE_RISE_PX",
    "HUM_ROCK_CYCLES",
    "HUM_ROCK_PERIOD",
    "HUM_ROCK_PX",
    "THINKING_GAZE_Y",
    "THINKING_RETARGET_MIN_S",
    "TILT_FALL_S",
    "TILT_HOLD_S",
    "TILT_MAX_DEG",
    "TILT_RISE_S",
    "TWITCH_DEFLATE",
    "TWITCH_HOLD_S",
    "TWITCH_JOLT_S",
    "TWITCH_MAX_GAP",
    "TWITCH_MIN_GAP",
    "TWITCH_SETTLE_S",
    "TWITCH_SHIFT_PX",
    "TYPING_HOLD_S",
    "TYPING_RETARGET_MIN_S",
    "TYPING_GAZE_Y",
    "TYPING_TILT_FIRST_MIN_S",
    "TYPING_TILT_FIRST_MAX_S",
    "TYPING_TILT_MIN_GAP",
    "TYPING_TILT_MAX_GAP",
}

_PIN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\s*=\s*(-?[0-9]+(?:\.[0-9]+)?)")

_MODULE_NAMES = (
    "mood",
    "recall",
    "watchdog",
    "pet",
    "layout",
    "mcp",
    "drives",
    "care",
    "attention",
    "tools",
    "crt",
    "typewriter",
    "anim",
    "boot",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _modules():
    return {name: importlib.import_module("sammy." + name) for name in _MODULE_NAMES}


def test_pinned_constants_match_the_code():
    pins = _PIN_RE.findall(_text(TUNING))
    seen = {name for name, _ in pins}
    assert seen == EXPECTED_PINS, "钉住的常量集合与约定不符：差集 " + repr(
        sorted(seen ^ EXPECTED_PINS)
    )
    mods = _modules()
    for name, raw in pins:
        owners = [mod for mod in mods.values() if hasattr(mod, name)]
        assert len(owners) == 1, name + " 应恰好在一个模块里，实际 " + str(len(owners)) + " 个"
        actual = getattr(owners[0], name)
        ok = abs(float(actual) - float(raw)) < 1e-9
        assert ok, name + "：文档写 " + raw + "，代码是 " + str(actual)


def test_decisions_and_files_are_covered():
    text = _text(TUNING)
    for heading in (
        "脸在小屏上的大小",
        "心情的推动量",
        "回忆的频率",
        "看门狗的放弃阈值",
        "MCP 的版本校验",
        "MCP 工具要不要默认开",
        "CRT 质感的强度",
        "像素字体的字号",
        "打字机与思考点的节奏",
        "凝视漂移与好奇",
        "表情淡化与弹跳",
        "开机自检序列",
        "关机序列",
        "光标凝视",
        "搬运凝视",
        "说话动脸",
        "作息与睡相",
        "醒来的哈欠",
        "无聊的叹气",
        "困得点头",
        "打字凝视",
        "睡梦抽动",
        "思考凝视",
        "摸摸头",
        "打个喷嚏",
        "哼小曲",
        "歪头",
        "好奇歪头",
    ):
        assert heading in text, "速查表缺小节：" + heading
    for filename in (
        "layout.py",
        "mood.py",
        "recall.py",
        "watchdog.py",
        "mcp.py",
        "mcp.json",
        "crt.py",
        "typewriter.py",
        "anim.py",
        "boot.py",
    ):
        assert filename in text, "速查表没点文件名：" + filename


def test_faceonly_numbers_are_computed_not_guessed():
    layout = importlib.import_module("sammy.layout")
    text = _text(TUNING)
    lay = layout.faceonly_layout(1024, 768)
    fw, fh = lay.face.width(), lay.face.height()
    full_w = layout.layout_dev(1024, 768).face.width()
    assert (str(fw) + "×" + str(fh)) in text, "文档该写实际脸框 " + str(fw) + "×" + str(fh)
    assert (str(round(fw / 1024 * 100)) + "%") in text, "文档该写真实的屏宽占比"
    mult = fw / full_w
    assert (f"{mult:g} 倍") in text, "文档该写 " + f"{mult:g}" + " 倍"


def test_mcp_versions_are_pinned():
    mcp = importlib.import_module("sammy.mcp")
    text = _text(TUNING)
    for v in (mcp.MODERN_VERSION, mcp.LEGACY_VERSION, mcp.LEGACY_RETRY_VERSION):
        assert v in text, "速查表没写版本号：" + v


def test_report_points_at_the_tuning_page():
    assert "TUNING.md" in _text(REPORT), "报告里应指到调参速查"
