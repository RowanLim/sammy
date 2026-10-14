"""待机省电（自选小步·第二十二次）——「你走了，屏幕慢慢暗下去；你回来，亮回来」。

这一条补的是「你不在的那段时间」：欢迎回来管的是你回来的**那一下**（抬脸看
你一眼），可你走了以后，屏幕一直亮得像有人在用 —— 一台老终端没人理的时候
是会省的。现在：光标静够十分钟（和休息提醒、欢迎回来同一把尺子）＝ 你走了，
整块屏幕慢慢暗下去；你回来又亮回来（亮得比暗得快 —— 屏幕比它的脸醒得还急
一点）。

为什么单独一个模块：它算的是**屏幕**的档位，不是脸的形变（anim 管脸）、
也不是玻璃上的纹理（crt 管扫描线 / 暗角）—— 这是「电源」。StandbyDim 是
纯计算、不碰 Qt 的部分（好测）；DimOverlay 是那层蒙层的载体：为什么要
**单独一个子控件**（和 CrtOverlay 同一条理由）—— 输入框（QLineEdit）是
独立子控件，父窗口里画的蒙层盖不住它的文字，想「连输入框一起暗」只能比
它更高。它一直在（不随 SAMMY_CRT 开关），档位 0 时一个字都不画 —— 和没有
这个功能完全一样。

档位 = 0（全亮）～ 1（省电最暗）；由窗口（pet 的 _standby_step）每帧喂
away 电平 —— 「走 / 回」两条边的口径（睡着不算离开、被拎着不算、开局 /
退场不算、光标功能关着不算）都在窗口那层，这里只认电平。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .crt import panel_path

# ── 参数（都可以调，但调完要跑测试；速查表见 docs/TUNING.md 第 32 节）──
STANDBY_DIM_MAX = 0.25  # 最暗时蒙层的黑度（0~1）—— 看得见「暗下去了」，又还读得清
STANDBY_FADE_S = 2.5  # 暗下去用时（秒）—— 慢：人已经走了，屏是慢慢沉下去的
STANDBY_RISE_S = 1.1  # 亮回来用时（秒）—— 快：你回来了，屏比脸醒得还急一点


def _smooth01(p: float) -> float:
    """0→1 的平滑缓动（两端速度为 0）—— 和凝视转场、交叉淡化同一条曲线。"""
    p = min(1.0, max(0.0, p))
    return 0.5 * (1.0 - math.cos(math.pi * p))


@dataclass
class StandbyDim:
    """「你走了屏幕暗下去、你回来亮回来」的档位（纯计算，没有 Qt）。

    电平信号（note_away）每帧喂一次；level(t) 是闭式解 —— 和 Animator 里那些
    排期不同：这里没有随机、没有排期，只有两条缓动曲线（暗下去慢、亮回来快）。
    """

    _away: bool = field(default=False, repr=False)
    _since: float = field(default=0.0, repr=False)  # 这一轮「你走了」的时刻
    _from: float = field(default=0.0, repr=False)  # 暗下去的起点档位（正常是 0）
    _back_at: float | None = field(default=None, repr=False)  # 你回来的时刻
    _back_from: float = field(default=0.0, repr=False)  # 亮回来的起点档位

    @property
    def away(self) -> bool:
        return self._away

    def note_away(self, t: float, away: bool) -> None:
        """喂一次「现在你走没走」—— 窗口每帧调一次。

        升沿记下时刻（暗下去从这里起算）；降沿记下回来的时刻与**当时的档位**
        （亮回来从当下出发，不跳 —— 虽然实际时序里回来时总是全暗）。
        同一电平重复喂是空操作：不能把起点一遍遍往后拨（淡入永远走不完）。
        """
        t = float(t)
        away = bool(away)
        if away == self._away:
            return
        if away:
            self._from = self.level(t)  # 从当下出发（中途反悔也不跳）
            self._since = t
        else:
            self._back_from = self.level(t)
            self._back_at = t
        self._away = away

    def level(self, t: float) -> float:
        """t 时刻的档位（0 = 全亮，1 = 省电最暗）。"""
        t = float(t)
        if self._away:
            k = _smooth01((t - self._since) / STANDBY_FADE_S)
            v = self._from + (1.0 - self._from) * k
        else:
            if self._back_at is None:
                return 0.0
            k = _smooth01((t - self._back_at) / STANDBY_RISE_S)
            v = self._back_from * (1.0 - k)
        return min(1.0, max(0.0, v))


def paint_dim(
    painter: QPainter,
    *,
    level: float,
    panel: QRect,
    panel_radius: float,
    scale: float,
    offset: tuple[int, int],
) -> None:
    """把面板整块压暗（圆角裁齐、面板外一个像素都不碰）。

    level 是档位（0~1），乘上 STANDBY_DIM_MAX 才是蒙的黑度；0 的时候一个字
    都不画。坐标：painter 的逻辑坐标 = 版面那一套（设计单位 × scale + offset）。
    """
    alpha = round(min(1.0, max(0.0, level)) * STANDBY_DIM_MAX * 255)
    if alpha <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(scale, scale)
    painter.translate(*offset)
    painter.fillPath(panel_path(panel, panel_radius), QColor(0, 0, 0, alpha))
    painter.restore()


class DimOverlay(QWidget):
    """待机省电的蒙层控件 —— 盖住整个窗口（连输入框的文字一起暗）。

    为什么要单独一个子控件（和 CrtOverlay 同一条理由）：输入框是独立子控件，
    父窗口里画的蒙层盖不住它的文字。它一直在（不随 SAMMY_CRT 开关）——
    档位 0 时 paintEvent 直接返回，不画任何东西。鼠标穿透（拖窗口、点输入框、
    右键菜单照旧）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._level = 0.0
        self._panel: QRect | None = None
        self._panel_radius: float = 0.0
        self._scale: float = 1.0
        self._offset: tuple[int, int] = (0, 0)

    def set_context(
        self,
        *,
        panel: QRect,
        panel_radius: float,
        scale: float,
        offset: tuple[int, int],
    ) -> None:
        """版面变了（尺寸 / 缩放）：重建蒙层的裁剪上下文。"""
        self._panel = QRect(panel)
        self._panel_radius = float(panel_radius)
        self._scale = float(scale)
        self._offset = (int(offset[0]), int(offset[1]))
        self.update()

    def set_level(self, level: float) -> bool:
        """落一次档位；变了就重画整层（返回变了没 —— 窗口不必自己盯）。"""
        level = min(1.0, max(0.0, float(level)))
        if level == self._level:
            return False
        self._level = level
        self.update()
        return True

    def level(self) -> float:
        """测试口子：当前档位。"""
        return self._level

    def paintEvent(self, event) -> None:
        if self._level <= 0.0 or self._panel is None:
            return
        p = QPainter(self)
        paint_dim(
            p,
            level=self._level,
            panel=self._panel,
            panel_radius=self._panel_radius,
            scale=self._scale,
            offset=self._offset,
        )
        p.end()


__all__ = [
    "STANDBY_DIM_MAX",
    "STANDBY_FADE_S",
    "STANDBY_RISE_S",
    "DimOverlay",
    "StandbyDim",
    "paint_dim",
]
