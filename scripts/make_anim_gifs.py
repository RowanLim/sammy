#!/usr/bin/env python3
"""从 35 张静态脸**生成**动图表情（GIF）。

为什么要生成而不是手画：这套脸是 128×64 的单色像素涂鸦，手绘一套动图等于重做一遍美术；
而"动"这件事在这个尺寸上**其实就是位移 + 几个小符号** —— 爱心往上飘、Zzz 浮起来、
眼泪往下掉、生气抖一抖。生成器能保证：
1. 配色和界面**同一套**（直接调 `faces.face_pixmap`，不重新实现一遍渲染）；
2. 想改幅度/帧数/速度，改参数重跑，不用重画。

产出：`assets/expressions/anim/<编号>.gif`（透明底，1-bit 透明正好适合双色像素画）。
渲染器有动图就用动图循环，没有就退回静态脸（外加眨眼/呼吸）。

用法:
    .venv/bin/python scripts/make_anim_gifs.py            # 全部生成
    .venv/bin/python scripts/make_anim_gifs.py --list     # 只列出会生成哪些
    .venv/bin/python scripts/make_anim_gifs.py --preview  # 另出一张预览图（深底，方便看）
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import faces

OUT_DIR = ROOT / "assets" / "expressions" / "anim"
PREVIEW = ROOT / ".tmp" / "anim-preview.png"
W, H = 128, 64  # 素材原始尺寸（也是那块 OLED 的尺寸）
# 荧光线色从 faces.LIT 读（单一来源）—— 2026-10-12 由荧光绿改白，这里不用动
LIT_R, LIT_G, LIT_B = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()

# ── 像素符号（用字符画定义，改起来一眼能看懂）──
HEART = (" █ █ ", "█████", "█████", " ███ ", "  █  ")
Z = ("███", "  █", " █ ", "███")
TEAR = (" █ ", "██ ", "██ ", " █ ")
FLAME_A = (" █ ", "███", " █ ", " █ ")
FLAME_B = (" █ ", " █ ", "███", " █ ")
SPARK = (" █ ", "███", " █ ")
DROP = (" █ ", "███", "███", " █ ")


@dataclass(frozen=True)
class Effect:
    """一种动效：整张脸的位移 + 若干飘动符号。

    符号位置 = 起点 + 第 k 个的偏移(spread) + 每帧步进(step) × 帧号。
    **spread 不能省**：省了的话同组符号全叠在一个点上，看起来是一坨（火焰就踩过）。
    """

    key: str
    frames: int = 8
    delay_ms: int = 90
    dxy: tuple[int, int] = (0, 0)  # 整张脸每帧的位移幅度（抖动/呼吸）
    sprite: tuple[str, ...] | None = None
    sprite_count: int = 2
    sprite_from: tuple[int, int] = (0, 0)
    sprite_spread: tuple[int, int] = (8, 0)  # 第 k 个符号相对第 0 个的偏移
    sprite_step: tuple[int, int] = (0, 0)  # 每帧移动（负数=往上飘）
    flicker: tuple[tuple[str, ...], ...] = ()  # 逐帧轮换的形状（火焰闪动用）


# 表情编号 → 动效（编号↔名字见 src/sammy/expressions.py）
# 读法：从 sprite_from 开始摆 sprite_count 个符号，第 k 个偏移 k×spread，
#       每帧再走一步 step（负数=往上/往左）。
EFFECTS: dict[int, Effect] = {
    # 睡眠 / 犯困：Zzz 斜着往上飘
    1: Effect(
        "zzz",
        frames=8,
        delay_ms=140,
        sprite=Z,
        sprite_count=3,
        sprite_from=(96, 52),
        sprite_spread=(-7, -6),
        sprite_step=(-1, -4),
    ),
    27: Effect(
        "zzz",
        frames=8,
        delay_ms=140,
        sprite=Z,
        sprite_count=2,
        sprite_from=(98, 50),
        sprite_spread=(-7, -6),
        sprite_step=(-1, -4),
    ),
    # 爱心 / 亲亲 / 期待 / 卖萌：爱心往上飘
    21: Effect(
        "hearts",
        frames=8,
        delay_ms=100,
        sprite=HEART,
        sprite_count=3,
        sprite_from=(6, 44),
        sprite_spread=(8, -3),
        sprite_step=(4, -5),
    ),
    14: Effect(
        "hearts",
        frames=8,
        delay_ms=100,
        sprite=HEART,
        sprite_count=3,
        sprite_from=(4, 46),
        sprite_spread=(8, -3),
        sprite_step=(4, -5),
    ),
    32: Effect(
        "hearts",
        frames=8,
        delay_ms=110,
        sprite=HEART,
        sprite_count=2,
        sprite_from=(10, 46),
        sprite_spread=(9, -3),
        sprite_step=(4, -4),
    ),
    34: Effect(
        "hearts",
        frames=8,
        delay_ms=110,
        sprite=HEART,
        sprite_count=2,
        sprite_from=(94, 46),
        sprite_spread=(9, -3),
        sprite_step=(4, -4),
    ),
    # 伤心 / 委屈 / 可怜：两只眼睛下面各挂一滴眼泪
    6: Effect(
        "tears",
        frames=7,
        delay_ms=110,
        sprite=TEAR,
        sprite_count=2,
        sprite_from=(42, 26),
        sprite_spread=(26, 0),
        sprite_step=(0, 4),
    ),
    31: Effect(
        "tears",
        frames=7,
        delay_ms=110,
        sprite=TEAR,
        sprite_count=2,
        sprite_from=(42, 26),
        sprite_spread=(26, 0),
        sprite_step=(0, 4),
    ),
    12: Effect(
        "tears",
        frames=7,
        delay_ms=120,
        sprite=TEAR,
        sprite_count=2,
        sprite_from=(44, 28),
        sprite_spread=(24, 0),
        sprite_step=(0, 3),
    ),
    # 开心 / 燃：整张脸抖（笑到抖）
    4: Effect("shake", frames=6, delay_ms=80, dxy=(2, 1)),
    24: Effect("shake", frames=6, delay_ms=70, dxy=(2, 1)),
    # 星星眼 / 惊喜 / 惊吓 / 震惊：角上散布闪一下
    20: Effect(
        "sparkle",
        frames=6,
        delay_ms=90,
        sprite=SPARK,
        sprite_count=3,
        sprite_from=(10, 8),
        sprite_spread=(38, 14),
        sprite_step=(0, 0),
    ),
    7: Effect(
        "sparkle",
        frames=6,
        delay_ms=90,
        sprite=SPARK,
        sprite_count=3,
        sprite_from=(92, 10),
        sprite_spread=(-34, 12),
        sprite_step=(0, 0),
    ),
    15: Effect(
        "sparkle",
        frames=5,
        delay_ms=80,
        sprite=SPARK,
        sprite_count=3,
        sprite_from=(16, 6),
        sprite_spread=(40, 12),
        sprite_step=(0, 0),
    ),
    30: Effect(
        "sparkle",
        frames=5,
        delay_ms=80,
        sprite=SPARK,
        sprite_count=3,
        sprite_from=(24, 6),
        sprite_spread=(34, 14),
        sprite_step=(0, 0),
    ),
    # 生气 / 不悦 / 邪恶：头顶一排火，逐帧换形状（= 闪动）
    10: Effect(
        "flames",
        frames=6,
        delay_ms=90,
        sprite=FLAME_A,
        sprite_count=3,
        sprite_from=(26, 2),
        sprite_spread=(12, 0),
        sprite_step=(0, 0),
        flicker=(FLAME_A, FLAME_B),
    ),
    33: Effect(
        "flames",
        frames=6,
        delay_ms=100,
        sprite=FLAME_A,
        sprite_count=3,
        sprite_from=(32, 2),
        sprite_spread=(12, 0),
        sprite_step=(0, 0),
        flicker=(FLAME_A, FLAME_B),
    ),
    25: Effect(
        "flames",
        frames=6,
        delay_ms=100,
        sprite=FLAME_A,
        sprite_count=3,
        sprite_from=(28, 2),
        sprite_spread=(12, 0),
        sprite_step=(0, 0),
        flicker=(FLAME_A, FLAME_B),
    ),
    # 流汗 / 尴尬 / 无语：一颗汗珠滑下来
    19: Effect(
        "sweat",
        frames=7,
        delay_ms=110,
        sprite=DROP,
        sprite_count=1,
        sprite_from=(98, 18),
        sprite_step=(0, 4),
    ),
    22: Effect(
        "sweat",
        frames=7,
        delay_ms=110,
        sprite=DROP,
        sprite_count=1,
        sprite_from=(96, 20),
        sprite_step=(0, 4),
    ),
    11: Effect(
        "sweat",
        frames=7,
        delay_ms=120,
        sprite=DROP,
        sprite_count=1,
        sprite_from=(98, 22),
        sprite_step=(0, 3),
    ),
    # 微笑 / 满足 / 普通：最克制的一档 —— 只是轻轻上下浮
    3: Effect("bob", frames=6, delay_ms=120, dxy=(0, 1)),
    23: Effect("bob", frames=6, delay_ms=120, dxy=(0, 1)),
    2: Effect("bob", frames=8, delay_ms=140, dxy=(0, 1)),
}


def stamp(img: QImage, art: tuple[str, ...], x: int, y: int, color: QColor) -> None:
    """把字符画盖到图上（越界就跳过 —— 别为了一像素把整张图搞崩）。"""
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            if ch != "█":
                continue
            px, py = x + dx, y + dy
            if 0 <= px < img.width() and 0 <= py < img.height():
                img.setPixel(px, py, color.rgba())


def compose(expr: int, eff: Effect, i: int, n: int, lit: QColor) -> QImage:
    """一帧：基础脸 + 位移 + 符号。"""
    out = QImage(W, H, QImage.Format_ARGB32)
    out.fill(Qt.transparent)

    p = QPainter(out)
    # 基础脸（直接借界面自己的渲染 —— 配色不可能跑偏）
    base = faces.face_pixmap(expr, QSize(W, H))
    # 位移：来回摆动（前半段往一边，后半段往回来），这样循环起来是连续的
    phase = i if i <= n // 2 else n - i
    dx = eff.dxy[0] * phase
    dy = eff.dxy[1] * phase
    p.drawPixmap(dx, dy, base)
    p.end()

    if eff.sprite and eff.sprite_count:
        art = eff.sprite
        if eff.flicker:
            art = eff.flicker[i % len(eff.flicker)]
        for k in range(eff.sprite_count):
            x = eff.sprite_from[0] + k * eff.sprite_spread[0] + i * eff.sprite_step[0]
            y = eff.sprite_from[1] + k * eff.sprite_spread[1] + i * eff.sprite_step[1]
            # 飘出画面就不画了（这就是"淡出"）
            if y < -len(art) or y > H or x < -len(art[0]) or x > W:
                continue
            stamp(out, art, x, y, lit)
    return out


def qimage_to_pil(img: QImage) -> Image.Image:
    """QImage → PIL 的 **P 模式**（两色调色板：0=透明、1=荧光绿）。

    为什么非得是 P 模式 + 自定义调色板：GIF 的透明是"调色板索引 0 透明"。
    直接拿 RGBA 交给 Pillow 量化，它可能把索引 0 当成一种**真颜色**，
    结果透明底变成黑块（实测踩过 —— 测试里那条"必须是透明底"就是为它写的）。
    """
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()

    out = Image.new("P", (w, h), 0)
    out.putpalette([0, 0, 0, LIT_R, LIT_G, LIT_B] + [0, 0, 0] * 254)
    px = out.load()
    for y in range(h):
        for x in range(w):
            # ⚠️ 必须用 pixelColor()：`QColor(img.pixel(x,y))` 会把 QRgb 当**预定义颜色**解释
            # （0x0 → Qt::color0 → 不透明黑），于是每个像素都被判成"亮的"，
            # 8 帧全变成同一整块，Pillow 只存下 1 帧。这个坑让动图静静退化成静态图。
            if img.pixelColor(x, y).alpha() > 0:
                px[x, y] = 1
    return out


def build(expr: int, eff: Effect, app) -> Path:
    lit = faces.LIT if hasattr(faces, "LIT") else QColor("#3ddc5a")
    frames = [qimage_to_pil(compose(expr, eff, i, eff.frames, lit)) for i in range(eff.frames)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{expr}.gif"
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=eff.delay_ms,
        loop=0,
        disposal=2,
        transparency=0,
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出会生成哪些")
    ap.add_argument("--preview", action="store_true", help="另出一张深底预览图")
    args = ap.parse_args()

    from sammy.expressions import name_of

    if args.list:
        for expr, eff in sorted(EFFECTS.items()):
            print(
                f"  {expr:>2} {name_of(expr):<4} → {eff.key}（{eff.frames} 帧 × {eff.delay_ms}ms）"
            )
        return 0

    app = QApplication(sys.argv[:1])  # noqa: F841（QPixmap 需要 QApplication）
    made = []
    for expr, eff in sorted(EFFECTS.items()):
        path = build(expr, eff, app)
        made.append((expr, eff, path))
        print(
            f"  ✅ {expr:>2} {name_of(expr):<4} → {path.name}（{path.stat().st_size // 1024} KB）"
        )

    if args.preview:
        cols, scale = 6, 2
        rows = (len(made) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * W * scale, rows * H * scale), (11, 20, 13))
        for idx, (_expr, _eff, path) in enumerate(made):
            gif = Image.open(path)
            gif.seek(0)
            f = gif.convert("RGBA").resize((W * scale, H * scale), Image.Resampling.NEAREST)
            bg = Image.new("RGB", f.size, (11, 20, 13))
            bg.paste(f, (0, 0), f)
            sheet.paste(bg, ((idx % cols) * W * scale, (idx // cols) * H * scale))
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(PREVIEW)
        print(f"\n  预览图: {PREVIEW}")

    print(f"\n共 {len(made)} 个动图 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
