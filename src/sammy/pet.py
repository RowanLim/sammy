"""Sammy 的脸 —— 桌面上的那个窗口。

设计决定：窗口本体就是「5 寸屏」本身（800×480 设备坐标系整体缩放），
这样屏幕上看到的一切，就是将来树莓派屏上看到的一切。
"""

from __future__ import annotations

import random
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QWidget

from . import faces, screen
from .attention import Attention, open_prompt
from .brain import SammyBrain
from .care import Care, care_prompt
from .drives import Drives, status_text
from .expressions import EXPR_NAMES, emoji_of, name_of
from .memory import Memory, consolidate_now, extract_and_store, needs_nightly
from .voice import Speaker, enabled_from_env

# ── 配色 ────────────────────────────────────────
GREEN = QColor("#3ddc5a")
GREEN_DIM = QColor(61, 220, 90, 70)
BEZEL = QColor(6, 14, 10, 242)
TEXT = QColor("#c8e6cf")
TEXT_DIM = QColor("#5f8a6c")
WARN = QColor("#e8c05a")

# ── 窗口缩放：树莓派上改成 1.0 ──
DEFAULT_SCALE = 0.55  # 桌面浮窗的默认缩放；小屏模式由 screen.fit() 按屏算
SCALE = DEFAULT_SCALE  # 兼容旧引用 —— 窗口内部一律用 self.scale

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
    activity = Signal(str)  # 工具调用时通知界面："正在联网…"
    spokeUp = Signal(dict)  # 它自己开口了（不是回谁的话）


class SammyWindow(QWidget):
    def __init__(
        self,
        brain: SammyBrain | None = None,
        memory: Memory | None = None,
        drives: Drives | None = None,
        attention: Attention | None = None,
        care: Care | None = None,
        speaker: Speaker | None = None,
        kiosk: bool = False,
        display: str | int | None = None,
        autoconnect: bool = True,
    ) -> None:
        """brain / memory 都可注入。

        autoconnect=False 时什么都不去连（测试用）—— 否则跑一次测试就会
        真连一次大模型、真在外置目录建一个记忆库。
        """
        super().__init__()

        # ── 屏幕与缩放 ───────────────────────────────
        # 800×480 是"设备坐标系"（树莓派的 5 寸屏），画脸的逻辑只认它。
        # 这里唯一负责的是：映射到真实像素 —— 换屏不动任何画脸的代码。
        self.scale = DEFAULT_SCALE
        self.target_screen: dict | None = None
        self._kiosk_geom: screen.Fit | None = None
        if kiosk:
            self.target_screen = screen.resolve_screen(display)
            self._kiosk_geom = screen.fit(
                faces.DEV_W,
                faces.DEV_H,
                self.target_screen["width"],
                self.target_screen["height"],
            )
            self.scale = self._kiosk_geom.scale

        self.setWindowTitle("Sammy")
        # 小屏模式不加 Qt.Tool：Tool 窗口在某些显示器上不会被显示出来
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if not kiosk:
            flags |= Qt.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if self._kiosk_geom is not None:
            f = self._kiosk_geom
            self.resize(f.width, f.height)
            self.move(self.target_screen["x"] + f.x, self.target_screen["y"] + f.y)
        else:
            self.resize(int(faces.DEV_W * self.scale), int(faces.DEV_H * self.scale))

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

        # 驱力（可注入）：精力 / 无聊 / 亲近，随时间漂移
        # autoconnect=False 时不读也不写真实的状态文件（测试不该碰用户的数据）
        self.drives = drives if drives is not None else (Drives.load() if autoconnect else Drives())
        self._idle_face: int | None = None
        self._last_interaction_at = 0.0
        self._save_ticks = 0
        self._started_at = time.time()

        # 主动心跳（可注入）：决定"要不要先开口"。**默认不说话** —— 见 attention.py
        self.attention = (
            attention
            if attention is not None
            else (Attention.load() if autoconnect else Attention())
        )
        self.last_gate = None
        self._speak_kind = "chat"

        # 休息提醒（可注入）：盯的是"你坐太久了"，和"它想不想聊"是两回事
        self.care = care if care is not None else (Care.load() if autoconnect else Care())
        self.last_care_gate = None

        # 声音（可注入）：测试里注入 NullBackend，不然半夜跑测试会突然有人说话
        self.speaker = (
            speaker
            if speaker is not None
            else Speaker(enabled=enabled_from_env() if autoconnect else False)
        )

        # 输入框
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("跟我说点什么…（回车发送）")
        self.input.returnPressed.connect(self.send)
        self.input.setStyleSheet(
            f"QLineEdit {{ background: rgba(18,42,26,190);"
            f" border: 2px solid rgba(61,220,90,110); border-radius: 16px;"
            f" color: #cfead6; padding-left: 18px; font-size: {int(30 * self.scale)}px; }}"
        )
        self.input.setGeometry(
            int(INPUT_BOX.x() * self.scale),
            int(INPUT_BOX.y() * self.scale),
            int(INPUT_BOX.width() * self.scale),
            int(INPUT_BOX.height() * self.scale),
        )

        self.bridge = Bridge()
        self.bridge.replyReady.connect(self._on_reply)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.memoryTouched.connect(self._on_memory)
        self.bridge.consolidated.connect(self._on_consolidated)
        self.bridge.activity.connect(self._on_activity)
        self.bridge.spokeUp.connect(self._on_spoke_up)

        # 空闲计时：会犯困、会睡着
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

        # 主动心跳：每分钟问一次"要不要先开口"（默认不说话，见 attention.py）
        self.heart = QTimer(self)
        self.heart.timeout.connect(self._heartbeat)
        self.heart.start(60 * 1000)

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
        self.drives.on_interaction()
        self.care.note_activity()
        self._last_interaction_at = time.time()
        self._idle_face = None
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
        self.drives.on_interaction(greeted=True)
        self.care.note_activity()
        self._last_interaction_at = time.time()
        self._idle_face = None
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
            result = self.brain.chat(
                text, ctx, on_event=lambda name: self.bridge.activity.emit(name)
            )
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

    def _on_activity(self, tool_name: str) -> None:
        """它决定联网了 —— 必须让用户看见，否则多等的几秒会像卡死。"""
        labels = {
            "web_search": "正在上网查…",
            "fetch_url": "正在读网页…",
            "current_time": "正在看时间…",
        }
        self.status = labels.get(tool_name, f"正在用 {tool_name}…")
        self.thinking = True
        self.set_expression(5 if tool_name == "web_search" else 16)  # 疑惑 / 思考
        self.update()

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
        self.speaker.say(self.sammy_line)  # 说出来（异步，不挡界面）
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
        self.drives.tick()
        self._refresh_idle_look()

        # 每分钟落盘一次 —— 状态是"它的一天"，不该只在退出时才存
        self._save_ticks += 1
        if self._save_ticks >= 60:
            self._save_ticks = 0
            self._save_drives()

    def _refresh_idle_look(self) -> None:
        """按驱力决定表情和状态文字。

        两道闸门都是为了**别抢戏**：
        1. 只在"心境"真的变了时才动手 —— 否则每秒重设一次，会盖掉刚回复完的表情
        2. 刚交互完的 5 秒内不动 —— 用户刚说完话，脸上不该立刻变回"无聊"
        """
        if time.time() - self._last_interaction_at < 5:
            return
        face = self.drives.expression()
        if face == self._idle_face:
            return
        self._idle_face = face
        self.set_expression(face)
        if self.status_ok:
            # 大脑没接通时保留那行错误提示，别用"在线"把它盖掉
            self.status = status_text(self.drives)

    def _save_drives(self) -> None:
        try:
            self.drives.save()
        except OSError as e:
            print(f"  ⚠️ 状态存不下来: {e}")

    def closeEvent(self, event) -> None:
        """退出前把状态存下来：否则重启就"满血复活"，人设是断的。"""
        self._save_drives()
        self._save_attention()
        self._save_care()
        self.speaker.stop()  # 别再念了
        super().closeEvent(event)

    # ── 主动心跳（它先开口） ─────────────────────────

    def _heartbeat(self) -> None:
        """问一次"要不要先开口"。**默认不说话** —— 所有闸门见 attention.py。

        这里刻意不写任何判断逻辑：判断全在 attention.py，因为那里能被单元测试
        单独验、能单独调参、能单独关掉。混进窗口代码就调不动了。
        """
        if self.thinking or self.brain is None or self._drag is not None:
            return

        # ① 先看"你坐太久了没" —— 关心你的身体，比它想找人聊更要紧
        care_gate = self.care.due()
        self.last_care_gate = care_gate
        if care_gate.ok:
            self._start_speaking(care_prompt(self.care.session_minutes()), kind="care")
            return

        # ② 再看"它自己想不想说话"
        silent = (
            (time.time() - self._last_interaction_at) / 60.0
            if self._last_interaction_at
            else 9999.0  # 从没交互过 = 很安静
        )
        gate = self.attention.decide(
            want_to_talk=self.drives.want_to_talk,
            silent_minutes=silent,
            started_at=self._started_at,
        )
        self.last_gate = gate  # 留给 --attention 和排查用：**每次拒绝都要能说出理由**
        if not gate.ok:
            return

        self._start_speaking(
            open_prompt(
                want_to_talk=self.drives.want_to_talk,
                closeness=self.drives.closeness,
                boredom=self.drives.boredom,
            ),
            kind="chat",
        )

    def _start_speaking(self, instruction: str, kind: str) -> None:
        """两种主动开口共用这条出口 —— 表情和状态文字按类型区分，机制只有一套。"""
        self.thinking = True
        self._speak_kind = kind
        if kind == "care":
            self.status = "该提醒你动一动了…"
            self.set_expression(5)  # 疑惑脸：它是在打量你
        else:
            self.status = "想跟你说句话…"
            self.set_expression(32)  # 期待脸
        self.update()
        threading.Thread(target=self._speak_up, args=(instruction,), daemon=True).start()

    def _speak_up(self, instruction: str) -> None:
        try:
            ctx = self.memory.context_block() if self.memory else ""
            result = self.brain.speak_first(instruction, ctx)
        except Exception as e:
            self.bridge.failed.emit(str(e))
            return
        self.bridge.spokeUp.emit(result)

    def _on_spoke_up(self, result: dict) -> None:
        """它自己开口了 —— 注意你那一侧是**空的**：这句话不是回给谁的。"""
        self.thinking = False
        self.my_line = ""
        self.sammy_line = result.get("reply", "……")
        self.set_expression(result.get("expression", 2))
        self.speaker.say(self.sammy_line)  # 主动开口同样要出声
        if getattr(self, "_speak_kind", "chat") == "care":
            self.status = f"提醒你动一动了 · {result.get('latency', 0):.1f}s"
            self.care.note_reminded()
            self._save_care()
        else:
            self.status = f"它自己开口了 · {result.get('latency', 0):.1f}s"
            self.attention.note_spoke()
            self._save_attention()
        self._idle_face = None
        self.update()

    def _save_attention(self) -> None:
        try:
            self.attention.save()
        except OSError as e:
            print(f"  ⚠️ 心跳状态存不下来: {e}")

    def _save_care(self) -> None:
        try:
            self.care.save()
        except OSError as e:
            print(f"  ⚠️ 休息计时存不下来: {e}")

    def snooze_care(self) -> None:
        """推后休息提醒（右键菜单里）。

        这条路径必须有：**被硬催着起来的提醒，用户第一件事就是把它卸载掉。**
        给一个"现在别烦我"的出口，比把提醒做得更"聪明"有用得多。
        """
        self.care.snooze()
        self._save_care()
        self.my_line = ""
        self.sammy_line = "行，那再过半小时。"
        self.status = "好，再过半小时提醒你"
        self.set_expression(8)  # 眨眼：懂你
        self._idle_face = None
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
        p.scale(self.scale, self.scale)  # 一行换屏：设备坐标 → 真实像素

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
        pos = event.position() / self.scale
        if (pos - CLOSE_C).manhattanLength() < CLOSE_R * 1.6:
            QApplication.quit()
            return
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            menu = QMenu(self)
            menu.addAction("戳一下", self.poke)
            # 「推后」必须有真能点到的地方 —— 被硬催着起来的提醒，用户第一件事就是卸载它
            menu.addAction("让我再坐会儿（推后 30 分钟）", self.snooze_care)
            menu.addAction("退出 Sammy", QApplication.quit)
            menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.poke()
