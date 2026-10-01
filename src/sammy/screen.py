"""把它放到那块屏上 —— 屏幕选择与等比铺满。

为什么值得单独一个模块：
**800×480 一直是"设备坐标系"**（当初就按树莓派那块 5 寸屏画的）。
现在要接真屏，尺寸未定（可能是 1024×600、1280×720，甚至竖屏）——
所以渲染逻辑一律继续按设备坐标画，只有这里负责"映射到真实像素"。
**换屏不该动任何画脸的代码。**

两条规矩：
1. **等比，不拉伸。** 拉扁的脸就不是那张脸了。尺寸比不匹配就居中留黑边。
2. **选择要记住。** 选过是哪块屏，下次别再问。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .paths import data_dir

STATE_FILE = data_dir() / "screen.json"


@dataclass(frozen=True)
class Fit:
    """把设备坐标系映射到某块屏的结果。"""

    scale: float
    x: int  # 相对屏幕左上角的偏移（居中留边的量）
    y: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {
            "scale": round(self.scale, 4),
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


def fit(dev_w: int, dev_h: int, screen_w: int, screen_h: int) -> Fit:
    """等比放大到屏幕内并居中。

    取**两个方向里较小的那个缩放比**，这样两边都不会超出（一边贴边、另一边留黑边）。
    """
    if dev_w <= 0 or dev_h <= 0:
        raise ValueError(f"设备尺寸必须为正：{dev_w}×{dev_h}")
    if screen_w <= 0 or screen_h <= 0:
        raise ValueError(f"屏幕尺寸必须为正：{screen_w}×{screen_h}")
    scale = min(screen_w / dev_w, screen_h / dev_h)
    w = max(1, int(dev_w * scale))
    h = max(1, int(dev_h * scale))
    return Fit(scale, (screen_w - w) // 2, (screen_h - h) // 2, w, h)


# ── 屏幕清单与选择 ─────────────────────────────────


def list_screens() -> list[dict]:
    """列出所有屏幕。需要 Qt，所以延迟导入。"""
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    out: list[dict] = []
    primary = app.primaryScreen()
    for i, s in enumerate(app.screens()):
        g = s.geometry()
        out.append(
            {
                "index": i,
                "name": s.name(),
                "x": g.x(),
                "y": g.y(),
                "width": g.width(),
                "height": g.height(),
                "primary": s is primary,
            }
        )
    return out


def resolve_screen(want: str | int | None = None) -> dict:
    """按名字或序号（或记住的选择）挑一块屏。

    找不到就退回主屏并**说明原因** —— 静默回退会让人以为"设置没生效"。
    """
    screens = list_screens()
    if not screens:
        raise RuntimeError("一块屏都没找到")

    want = want if want is not None else load_preference()
    if want is not None and str(want) != "":
        w = str(want)
        for s in screens:
            if w == str(s["index"]) or w.lower() == s["name"].lower():
                return s
        # 没找到：退回主屏，但别装作没事
        primary = next((s for s in screens if s["primary"]), screens[0])
        primary["fallback_reason"] = f"没找到屏幕 {w!r}，退回主屏"
        return primary

    return next((s for s in screens if s["primary"]), screens[0])


def describe_screens(dev_w: int, dev_h: int) -> str:
    """给 `--screens` 用：每块屏一行，带铺满后的结果。"""
    lines = [f"设备坐标系 {dev_w}×{dev_h}（画脸一直是按这个画的）", ""]
    for s in list_screens():
        f = fit(dev_w, dev_h, s["width"], s["height"])
        mark = " ←主屏" if s["primary"] else ""
        lines.append(
            f"  [{s['index']}] {s['name']}  {s['width']}×{s['height']}"
            f"{mark}\n      铺满后 {f.width}×{f.height}（缩放 {f.scale:.2f}）"
            f"，居中留边 左右 {f.x} / 上下 {f.y}"
        )
    return "\n".join(lines)


# ── 记住选择 ──────────────────────────────────────


def remember(which: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"screen": which}, ensure_ascii=False), encoding="utf-8")


def load_preference() -> str | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("screen")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


__all__ = [
    "STATE_FILE",
    "Fit",
    "describe_screens",
    "fit",
    "list_screens",
    "load_preference",
    "remember",
    "resolve_screen",
]
