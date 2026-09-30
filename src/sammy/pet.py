"""Sammy 的脸 —— 桌面上的那个窗口。

设计决定：窗口本体就是「5 寸屏」本身（800×480 设备坐标系整体缩放），
这样屏幕上看到的一切，就是将来树莓派屏上看到的一切。
"""

from __future__ import annotations

import random
import threading

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QWidget

from . import faces
from .brain import SammyBrain
from .expressions import EXPR_NAMES, emoji_of, name_of
from .memory import Memory, consolidate_now, extract_and_store, needs_nightly

# ── 配色 ────────────────────────────────────────
GREEN = QColor("#3ddc5a")
GREEN_DIM = QColor(61, 220, 90, 70)
BEZEL = QColor(6, 14, 10, 242)
TEXT = QColor("#c8e6cf")
TEXT_DIM = QColor("#5f8a6c")
WARN = QColor("#e8c05a")

# ── 窗口缩放：树莓派上改成 1.0 ──
SCALE = 0.55

# ── 800×480 设备坐标系下的版面 ──
CLOSE_C = QPoint(752, 34)
CLOSE_R = 20
STATUS_Y = 242
DIVIDER_Y = 284
MY_LINE_BOX = QRect(46, 290, 708, 30)
REPLY_BOX = QRect(46, 324, 708, 70)
INPUT_BOX = QRect(46, 400, 708, 50)

POKE_QUIPS = [
    "哎哟！戳哪儿呢～",
    "干嘛呀，痒！",
    "我在呢我在呢。",
    "再戳我就咬你了啊。",
    "嘿嘿，就喜欢你戳我。",
]
POKE_FACES = [4, 8, 21, 29, 7]


class Bridge(QObject):
    """后台线程 → UI 线程的信号桥。"""

    replyReady = Signal(dict)
    failed = Signal(str)
    memoryTouched = Signal(dict)
    consolidated = Signal(dict)


class SammyWindow(QWidget):
    def __init__(
        self,
        brain: SammyBrain | None = None,
        memory: Memory | None = None,
        autoconnect: bool = True,
    ) -> None:
        """brain / memory 都可注入。

        autoconnect=False 时什么都不去连（测试用）—— 否则跑一次测试就会
        真连一次大模型、真在外置目录建一个记忆库。
        """
        super().__init__()
        self.setWindowTitle("Sammy")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(int(faces.DEV_W * SCALE), int(faces.DEV_H * SCALE))

        self.expression = 3  # 微笑开场
        self.my_line = ""
        self.sammy_line = "嗯…我醒着呢。"
        self.status = "在线"
        self.status_ok = True
        self.thinking = False
        self.idle_seconds = 0
        self._drag: QPoint | None = None

        # 大脑（可注入）
        self.brain = brain
        if self.brain is None and autoconnect:
            try:
                self.brain = SammyBrain()
            except Exception as e:
                self.status = "大脑未接通"
                self.status_ok = False
                self.sammy_line = f"{e}"
                self.expression = 17  # 生病脸

        # 记忆（可注入；独立于大脑 —— 大脑挂了也要能读出记忆）
        self.memory = memory
        if self.memory is None and autoconnect:
            try:
                self.memory = Memory()
            except Exception as e:
                print(f"  ⚠️ 记忆打不开（不影响对话）: {e}")

        # 输入框
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("跟我说点什么…（回车发送）")
        self.input.returnPressed.connect(self.send)
        self.input.setStyleSheet(
            f"QLineEdit {{ background: rgba(18,42,26,190);"
            f" border: 2px solid rgba(61,220,90,110); border-radius: 16px;"
            f" color: #cfead6; padding-left: 18px; font-size: {int(30 * SCALE)}px; }}"
        )
        self.input.setGeometry(
            int(INPUT_BOX.x() * SCALE),
            int(INPUT_BOX.y() * SCALE),
            int(INPUT_BOX.width() * SCALE),
            int(INPUT_BOX.height() * SCALE),
        )

        self.bridge = Bridge()
        self.bridge.replyReady.connect(self._on_reply)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.memoryTouched.connect(self._on_memory)
        self.bridge.consolidated.connect(self._on_consolidated)

        # 空闲计时：会犯困、会睡着
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

        # 「睡了一觉」：启动 8 秒后查一次，之后每半小时查一次
        self.night = QTimer(self)
        self.night.timeout.connect(self._maybe_consolidate)
        self.night.start(30 * 60 * 1000)
        QTimer.singleShot(8000, self._maybe_consolidate)

    # ── 表情 / 状态 ──────────────────────────────

    def set_expression(self, index: int) -> None:
        if index in EXPR_NAMES:
            self.expression = index
            self.update()

    def poke(self) -> None:
        """戳一下。"""
        if self.thinking:
            return
        self.idle_seconds = 0
        self.set_expression(random.choice(POKE_FACES))
        self.sammy_line = random.choice(POKE_QUIPS)
        self.my_line = ""

    # ── 对话 ────────────────────────────────────

    def send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.idle_seconds = 0
        self.my_line = text

        if self.brain is None:
            self.sammy_line = "我脑子还没接通 —— 检查一下 .env 里的凭证。"
            self.set_expression(17)
            return

        self.thinking = True
        self.status = "思考中…"
        self.set_expression(16)  # 思考脸
        self.sammy_line = "……"
        threading.Thread(target=self._call_brain, args=(text,), daemon=True).start()

    def _call_brain(self, text: str) -> None:
        # 对话失败和记忆失败是两件事，必须分开兜 ——
        # 否则一条记忆没写进去，就会把用户已经拿到的回复覆盖成"我卡住了"。
        try:
            ctx = self.memory.context_block() if self.memory else ""
            result = self.brain.chat(text, ctx)
        except Exception as e:
            self.bridge.failed.emit(str(e))
            return

        self.bridge.replyReady.emit(result)

        # 抽记忆放在同一条后台线程里 —— 用户已经看到回复了，这里不占他的等待
        if self.memory:
            try:
                info = extract_and_store(self.brain, self.memory, text, result["reply"])
                self.bridge.memoryTouched.emit(info)
            except Exception as e:
                print(f"  ⚠️ 记忆写入失败（回复不受影响）: {e}")

    def _on_memory(self, info: dict) -> None:
        bits = []
        if info.get("slots"):
            bits.append(f"{info['slots']} 条事实")
        if info.get("journal"):
            bits.append(f"{info['journal']} 条记录")
        if info.get("explicit"):
            bits.append("你要我记的")
        if bits and not self.thinking:
            self.status = "记住了 · " + "、".join(bits)
            self.update()

    def _on_consolidated(self, info: dict) -> None:
        if info.get("digest") and not self.thinking:
            self.status = f"睡了一觉，把 {info['day']} 理了理"
            self.update()

    def _on_reply(self, result: dict) -> None:
        self.thinking = False
        self.idle_seconds = 0
        self.sammy_line = result.get("reply", "……")
        self.set_expression(result.get("expression", 2))
        self.status = f"在线 · {result.get('latency', 0):.1f}s"
        self.status_ok = True
        self.update()

    def _on_failed(self, message: str) -> None:
        self.thinking = False
        self.status = "出错了"
        self.status_ok = False
        self.sammy_line = f"我卡住了：{message[:120]}"
        self.set_expression(6)  # 伤心脸
        self.update()

    # ── 空闲行为 ────────────────────────────────

    def _tick(self) -> None:
        if self.thinking:
            return
        self.idle_seconds += 1
        if self.idle_seconds == 120:
            self.set_expression(27)  # 犯困
        elif self.idle_seconds == 300:
            self.set_expression(1)  # 睡着
            self.status = "睡着了"
        if self.idle_seconds in (120, 300):
            self.update()

    # ── 夜里整理（Sammy 睡着的时候干活） ────────────

    def _maybe_consolidate(self) -> None:
        if self.thinking or not (self.memory and self.brain):
            return
        day = needs_nightly(self.memory)
        if not day:
            return
        threading.Thread(target=self._consolidate_worker, args=(day,), daemon=True).start()

    def _consolidate_worker(self, day: str) -> None:
        try:
            self.bridge.consolidated.emit(consolidate_now(self.brain, self.memory, day))
        except Exception as e:
            print(f"  ⚠️ 夜里整理失败: {e}")

    # ── 绘制 ────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(SCALE, SCALE)  # ← 一行切换屏幕：树莓派上改成 1.0

        # 屏幕玻璃
        p.setPen(QPen(GREEN_DIM, 3))
        p.setBrush(BEZEL)
        p.drawRoundedRect(QRect(2, 2, faces.DEV_W - 4, faces.DEV_H - 4), 32, 32)

        # 脸
        box = faces.face_box()
        p.drawPixmap(
            box.topLeft(), faces.face_pixmap(self.expression, QSize(box.width(), box.height()))
        )

        # 状态行：表情名 · 状态灯 ~~~~ 状态文字
        label = f"{emoji_of(self.expression)} {name_of(self.expression)}"
        p.setFont(QFont("PingFang SC", 26))
        p.setPen(GREEN)
        p.drawText(QRect(46, STATUS_Y, 500, 36), Qt.AlignLeft | Qt.AlignVCenter, label)
        dot_x = 46 + QFontMetrics(p.font()).horizontalAdvance(label) + 18
        p.setFont(QFont("PingFang SC", 22))
        p.setPen(TEXT if self.status_ok else WARN)
        p.drawText(
            QRect(dot_x + 20, STATUS_Y, 754 - dot_x - 20, 36),
            Qt.AlignRight | Qt.AlignVCenter,
            self.status,
        )
        p.setBrush(GREEN if self.status_ok else WARN)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(dot_x, STATUS_Y + 18), 7, 7)

        # 分隔线
        p.setPen(QPen(GREEN_DIM, 2))
        p.drawLine(46, DIVIDER_Y, 754, DIVIDER_Y)

        # 对话区
        if self.my_line:
            p.setFont(QFont("PingFang SC", 20))
            p.setPen(TEXT_DIM)
            p.drawText(
                MY_LINE_BOX,
                Qt.AlignLeft | Qt.AlignVCenter,
                QFontMetrics(p.font()).elidedText(
                    f"你：{self.my_line}", Qt.ElideRight, MY_LINE_BOX.width()
                ),
            )

        # 回复文字：自适应字号，宁可缩小也不许被切掉
        flags = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap
        font = QFont("PingFang SC", 26)
        for size in (26, 24, 22, 20, 18):
            font = QFont("PingFang SC", size)
            if (
                QFontMetrics(font).boundingRect(REPLY_BOX, flags, self.sammy_line).height()
                <= REPLY_BOX.height()
            ):
                break
        p.setFont(font)
        p.setPen(TEXT)
        p.drawText(REPLY_BOX, flags, self.sammy_line)

        # 关闭按钮
        p.setPen(QPen(GREEN_DIM, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(CLOSE_C, CLOSE_R, CLOSE_R)
        p.setPen(GREEN)
        p.drawText(
            QRect(CLOSE_C.x() - CLOSE_R, CLOSE_C.y() - CLOSE_R, CLOSE_R * 2, CLOSE_R * 2),
            Qt.AlignCenter,
            "✕",
        )
        p.end()

    # ── 交互 ────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = event.position() / SCALE
        if (pos - CLOSE_C).manhattanLength() < CLOSE_R * 1.6:
            QApplication.quit()
            return
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            menu = QMenu(self)
            menu.addAction("戳一下", self.poke)
            menu.addAction("退出 Sammy", QApplication.quit)
            menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.poke()
