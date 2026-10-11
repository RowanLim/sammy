"""Sammy 的脸 —— 桌面上的那个窗口。

设计决定：窗口本体就是「5 寸屏」本身（800×480 设备坐标系整体缩放），
这样屏幕上看到的一切，就是将来树莓派屏上看到的一切。
"""

from __future__ import annotations

import random
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QWidget

from . import anim, chatlog, crt, faces, layout, screen, typewriter
from . import mood as mood_mod
from .attention import Attention, open_prompt
from .brain import SammyBrain
from .care import Care, care_prompt
from .drives import EMOTIONS, Drives, status_text
from .expressions import EXPR_NAMES, emoji_of, name_of
from .memory import Memory, consolidate_now, extract_and_store, needs_nightly
from .mood import MoodTracker
from .recall import Recaller, chat_text_since, recall_prompt
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

# ── 版面：设计值现已集中在 layout.py（单一来源），这里不再留副本 ──
# （曾经这里写着一组 800×480 的常量，接线后删掉：两份会各自漂移，
#   屏幕自适应要的正是"一份设计值铺满任意屏"。）

POKE_QUIPS = [
    "哎哟！戳哪儿呢～",
    "干嘛呀，痒！",
    "我在呢我在呢。",
    "再戳我就咬你了啊。",
    "嘿嘿，就喜欢你戳我。",
]
POKE_FACES = [4, 8, 21, 29, 7]

# 睡着时的表情编号（1=睡眠）。这个状态下动画要收敛：睡着还晃来晃去就不像睡着了
SLEEP_EXPR = 1

# face-only 的那一行：它刚说的话停留多久（秒），之后回到状态行
FACEONLY_LINE_HOLD = 20.0


def anim_enabled(env: dict | None = None) -> bool:
    """脸部动画开关（`SAMMY_ANIM=off` 关掉 —— 省电、或排障时用）。"""
    if env is not None:
        raw = env.get("SAMMY_ANIM", "on")
    else:
        from .voice import config

        raw = config("SAMMY_ANIM", "on")
    return str(raw or "on").strip().lower() not in {"off", "0", "false", "no"}


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
        recall: Recaller | None = None,
        speaker: Speaker | None = None,
        kiosk: bool = False,
        display: str | int | None = None,
        face_only: bool = False,
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
        self.face_only = face_only
        # CRT 质感（U4）：默认开，SAMMY_CRT=off 关掉（三件事在 crt.py）。
        self.crt_on = crt.crt_enabled()
        self._crt_overlay: crt.CrtOverlay | None = None
        self._crt_buf: QImage | None = None
        # 兜底版面：窗口尺寸还没定（或报 0×0）时也不至于没有版面可用
        self.lay = (
            layout.faceonly_layout(faces.DEV_W, faces.DEV_H)
            if face_only
            else layout.layout_dev(faces.DEV_W, faces.DEV_H)
        )
        self.target_screen: dict | None = None
        self._kiosk_geom: screen.Fit | None = None
        self._offset: tuple[int, int] = (0, 0)  # 居中留边的偏移（见 paintEvent）
        if kiosk:
            self.target_screen = screen.resolve_screen(display)
            if self.target_screen["width"] <= 0 or self.target_screen["height"] <= 0:
                # 屏没接 / 没信号时，Qt 会报 0×0。
                # **这里绝不能崩** —— 崩了的表现是"插上屏 Sammy 也不见了"，
                # 而人会以为是自己弄坏的（实测：小屏断开时 kiosk 启动直接 ValueError）。
                # 先按设计尺寸把窗建出来，屏一恢复 resizeEvent 会自动重算。
                print(
                    f"  ⚠️ 屏 {self.target_screen['name']!r} 报不出尺寸"
                    f"（{self.target_screen['width']}×{self.target_screen['height']}，多半是没接/没信号），"
                    f"先按设计尺寸 {faces.DEV_W}×{faces.DEV_H} 起窗"
                )
                self.target_screen = {
                    **self.target_screen,
                    "x": 0,
                    "y": 0,
                    "width": faces.DEV_W,
                    "height": faces.DEV_H,
                }
            self._kiosk_geom = screen.fit(
                faces.DEV_W,
                faces.DEV_H,
                self.target_screen["width"],
                self.target_screen["height"],
            )
            self.scale = self._kiosk_geom.scale
            # 版面是**自适应**的（画布 = 窗口 ÷ 缩放），内容自己就铺满整窗 ——
            # 所以不能再叠加"居中留边"那一层偏移：窗口本身已经贴边，
            # 再平移一次就把右边推出去（实测：状态行的"在线"和页码被吃掉）。
            # 居中的活现在由 layout 干：元素按画布宽度铺开、脸在画布内居中。
            self._offset = (0, 0)
            self._bind_to_screen(self.target_screen["name"])

        self.setWindowTitle("Sammy")
        # 小屏模式不加 Qt.Tool：Tool 窗口在某些显示器上不会被显示出来
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if not kiosk:
            flags |= Qt.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if self._kiosk_geom is not None:
            # 铺满整块屏（窗管实际给多少就以 resizeEvent 为准 —— 顶栏可能吃掉几十像素）
            self.resize(self.target_screen["width"], self.target_screen["height"])
            self.move(self.target_screen["x"], self.target_screen["y"])
        else:
            self.resize(int(faces.DEV_W * self.scale), int(faces.DEV_H * self.scale))
        self._relayout()

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

        # 回忆主动性（可注入）：主动开口时带上"它想起的旧事"（闸门见 recall.py）
        self.recall = (
            recall if recall is not None else (Recaller.load() if autoconnect else Recaller())
        )
        self.last_recall_gate = None
        self._speak_item_id: str | None = None
        self._speak_instruction: str = ""

        # 声音（可注入）：测试里注入 NullBackend，不然半夜跑测试会突然有人说话
        self.speaker = (
            speaker
            if speaker is not None
            else Speaker(enabled=enabled_from_env() if autoconnect else False)
        )

        # 心情（底色）：驱力管"困不困"，心情管"乐不乐" —— 两者合起来才是完整的它
        self.mood = MoodTracker()

        # 输入框
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("跟我说点什么…（回车发送）")
        self.input.returnPressed.connect(self.send)
        self._layout_input()

        # CRT 质感层（U4）：扫描线 + 暗角盖在最上面（连输入框一起盖）。
        # 为什么单独一个子控件：QLineEdit 会压住父窗口画的东西（见 crt.CrtOverlay）。
        if self.crt_on:
            self._crt_overlay = crt.CrtOverlay(self)
            self._crt_overlay.show()
            self._sync_crt_layer()

        # 回复排版缓存（每帧都算二分查找太浪费；键变了才重算）
        self._fit_cache = None
        self._fit_key = None
        self._reply_t0 = 0.0  # 这条回复是第几秒出现的（翻页从第一页开始）
        self._line_until = 0.0  # face-only：刚说的话要在那一行停到什么时候
        # 打字机（U3）：回复逐字出现的进度。**惰性起步** —— 这条文本第一次
        # 被画出来时才算"开始打"（否则窗口没显示的那段时间也被算进去，
        # 一露面就已经打了一半）。
        self._type_key: str | None = None
        self._type_t0 = 0.0
        self._type_plan: typewriter.TypePlan | None = None
        self._type_plan_key: tuple[str, ...] | None = None

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

        # 脸的动画：眨眼 / 呼吸 / 微动 —— 让它像个活的，而不是一张贴图。
        # 纯数学在 anim.py（可测），这里只负责推进时间和重画那一小块。
        self.anim = anim.Animator()
        self.anim_t = 0.0
        # 动画开着吗？换表情要不要交叉淡化由它定 —— 关着时没有时间轴，
        # 只能瞬间切（否则淡化永远停在第一帧，表情再也换不动）。
        self.anim_on = anim_enabled()
        self.anim.set_expression(self.expression, None)  # 开场没有"上一张脸"
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._anim_tick)
        if self.anim_on:
            self.anim_timer.start(int(anim.ANIM_DT * 1000))

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
            if self.anim_on:
                self.anim.set_expression(index, self.anim_t)  # 缓动过渡：老脸淡出、新脸淡入
            else:
                self.anim.set_expression(index, None)  # 动画关着：没有时间轴，瞬间切
            self.expression = index
            self.update()

    def poke(self) -> None:
        """戳一下。"""
        self.mood.poke()  # 有人来逗它，底色总会好一点
        self.mood.save()
        if self.thinking:
            return
        self.idle_seconds = 0
        self.drives.on_interaction()
        self.care.note_activity()
        self._last_interaction_at = time.time()
        self._idle_face = None
        self.set_expression(random.choice(POKE_FACES))
        self.sammy_line = random.choice(POKE_QUIPS)
        self._hold_line()  # face-only 的那一行也先显示这句话
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
        chatlog.append("user", text)  # 先记你说的（哪怕它答不上来，流水也该有你那句）

        if self.brain is None:
            self.sammy_line = "我脑子还没接通 —— 检查一下 .env 里的凭证。"
            self.set_expression(17)
            return

        self.thinking = True
        self.status = "思考中…"
        self.set_expression(16)  # 思考脸
        self.sammy_line = "……"
        self._line_until = 0.0  # 单行先回到"思考中…"，别停在上一条回复上
        threading.Thread(target=self._call_brain, args=(text,), daemon=True).start()

    def _call_brain(self, text: str) -> None:
        # 对话失败和记忆失败是两件事，必须分开兜 ——
        # 否则一条记忆没写进去，就会把用户已经拿到的回复覆盖成"我卡住了"。
        try:
            ctx = self.memory.context_block() if self.memory else ""
            # 把"它此刻的心情"并进上下文 —— 语气要跟着底色走（提示词里也就这一处）
            self.mood.tick(hours_alone=self._hours_alone())
            ctx = "\n".join([p for p in (ctx, self.mood.prompt()) if p])
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
        self.mood.nudge(int(result.get("expression", 2) or 2))  # 这一轮的情绪推一把底色
        self.mood.save()
        self._hold_line()  # face-only 的那一行：先显示这句话
        self.status = f"在线 · {result.get('latency', 0):.1f}s"
        self.speaker.say(self.sammy_line)  # 说出来（异步，不挡界面）
        chatlog.append("assistant", self.sammy_line)  # 流水（P1-11）
        self.status_ok = True
        self.update()

    def _on_failed(self, message: str) -> None:
        self.thinking = False
        self.status = "出错了"
        self.status_ok = False
        self.sammy_line = f"我卡住了：{message[:120]}"
        self._hold_line()  # 出错的话也要在那一行上看得见
        self.set_expression(6)  # 伤心脸
        self.update()

    # ── face-only 的单行显示 ─────────────────────

    def _hold_line(self) -> None:
        """让那一行先显示它刚说的话；过一会儿再回到状态。

        「过一会儿」还得**到点自动重画一下**：那一行平时不在动画的刷新范围里，
        没有这一下，时间到了画面还赖着旧文字（20 秒就只是个没人看的时间戳）。
        """
        self._line_until = time.time() + FACEONLY_LINE_HOLD
        QTimer.singleShot(int((FACEONLY_LINE_HOLD + 0.1) * 1000), self._repaint_text_region)

    def face_line(self) -> tuple[str, bool]:
        """face-only 模式那一行显示什么（第二个值 = 是不是"刚说的话"）。

        屏幕小，只给得起一行：**它刚说的话**优先（说完 20 秒内），其余时间
        显示状态（在线/思考中/出错了……）—— 它也是那一屏唯一的报错出口。
        """
        if self.sammy_line and time.time() < self._line_until:
            return self.sammy_line, True
        return self.status, False

    # ── 打字机 / 思考点（U3）────────────────────

    def finish_typing(self) -> None:
        """把打字机**立刻拨到尾**（快照/报告素材用）—— 拍到的必须是一整句。

        抓图不能拍"话说到一半"：给个远古的起点，任何时刻都算打完。
        """
        self._type_key = self.sammy_line
        self._type_t0 = self.anim_t - 1e6

    def _sync_typing(self, text: str) -> float:
        """这条文本开打了多久 —— **第一次被画出来**时才开始（惰性起步）。"""
        if self._type_key != text:
            self._type_key = text
            self._type_t0 = self.anim_t
        return self.anim_t - self._type_t0

    def _plan_for(self, pages: tuple[str, ...]) -> typewriter.TypePlan:
        """这条回复的打字机时间表（文本没变就复用；节奏定义在 typewriter.py）。"""
        if self._type_plan is None or self._type_plan_key != pages:
            self._type_plan = typewriter.TypePlan(pages)
            self._type_plan_key = pages
        return self._type_plan

    def _reply_shown(self) -> tuple[int, str]:
        """回复区这一刻显示什么：(页码, 文本)。

        三种形态 —— 思考中给会动的点；动画关着直接整页（没有时间轴，
        打字机会永远停在第一个字）；其余走打字机（第一遍逐字）。
        """
        if self.thinking:
            return 0, typewriter.dots(self.anim_t)
        fit = self._reply_fit()
        if not self.anim_on:
            i = fit.index_at(self.anim_t - self._reply_t0)
            return i, fit.pages[i]
        plan = self._plan_for(fit.pages)
        return plan.view_at(self._sync_typing(self.sammy_line))

    def _typed_line(self, text: str) -> str:
        """face-only 那一行也逐字出现（动画关着就直接整句）—— 小屏同一台机器。"""
        if not self.anim_on:
            return text
        return typewriter.reveal(text, self._sync_typing(text))

    def _status_shown(self) -> str:
        """状态行：思考时把句尾的省略号换成会动的点（干等的省略号看着像卡死）。"""
        if self.thinking:
            return typewriter.grow_dots(self.status, self.anim_t)
        return self.status

    def _text_region(self) -> QRect:
        """文字区（状态行 + 回复区）在窗口里的像素区域 —— 打字机/思考点动时刷它。"""
        L = self.lay
        r = QRect(L.status)
        rep = getattr(L, "reply", None)  # face-only 版面没有回复区
        if rep is not None:
            r = r.united(rep)
        s = self.scale
        return QRect(
            int(r.x() * s) + self._offset[0] - 2,
            int(r.y() * s) + self._offset[1] - 2,
            int(r.width() * s) + 4,
            int(r.height() * s) + 4,
        )

    def _text_live(self) -> bool:
        """文字区现在是不是"活的"（思考点在动 / 打字机在打）—— 是才值得刷。"""
        if self.thinking:
            return True
        if not self.anim_on or self._type_key != self.sammy_line:
            return False
        if self.face_only:
            return (self.anim_t - self._type_t0) < typewriter.reveal_seconds(self.sammy_line)
        plan = self._type_plan
        if plan is None:
            return False
        if len(plan.pages) > 1:  # 翻页回复：整轮都在换内容，必须一直刷
            return True
        return (self.anim_t - self._type_t0) < plan.loop

    def _repaint_text_region(self) -> None:
        """到点把文字区重画一次（face-only 那一行的"到点回状态"就靠它）。"""
        self.update(self._text_region())

    # ── 空闲行为 ────────────────────────────────

    def _bind_to_screen(self, name: str) -> None:
        """把窗口**绑**到指定那块屏上。

        为什么光靠 move() 不够（实测）：多显示器下 move() 请求会被窗管重新摆，
        在 Nex 上窗口被摆到了 x=3840 —— 两块屏之外的虚空，**两块屏都看不见**，
        而且窗口列表里查得到、看着像"投上去了"。

        Qt 6 的 `setScreen()` 是唯一靠谱的做法：窗管明确知道这个窗口属于哪块屏，
        之后再 `showFullScreen()` 就只会铺满那一块。
        """
        from PySide6.QtWidgets import QApplication

        for qs in QApplication.screens():
            if qs.name() == name:
                self.setScreen(qs)
                return

    def _face_region(self) -> QRect:
        """脸在窗口里的像素区域（向外留余量，盖住呼吸位移和弹的那一下）。

        用**版面里的脸**（`self.lay.face`），不是设计位 —— face-only 下脸不在
        设计位置上，写死脸框会让动画只刷新一小块（脸会花）；顺带修掉 kiosk
        上的同一处旧错：画布变宽后脸被重新居中过，旧写法刷的是老位置。
        """
        r = self.lay.face.adjusted(-12, -12, 12, 12)
        s = self.scale
        return QRect(
            int(r.x() * s) + self._offset[0],
            int(r.y() * s) + self._offset[1],
            int(r.width() * s) + 2,
            int(r.height() * s) + 2,
        )

    def _anim_tick(self) -> None:
        """推进动画时间，**只重画需要重画的那一块**。

        整窗重画在 1920×1080 上 30fps 太浪费，而且大多数时候脸以外没变。
        文字区只在思考点 / 打字机在动的时候才刷（`_text_live` 说了算）——
        其余时间它是静的，谁也不用花这份电。
        """
        self.anim_t += anim.ANIM_DT
        self.update(self._face_region())
        if self._text_live():
            self.update(self._text_region())

    def _reply_fit(self) -> layout.ReplyFit:
        """当前回复的排版结论（带缓存）。

        翻页从**这条回复出现的那一刻**开始算，所以换一条回复总是从第 1 页显示，
        而不是接着上一条的页码继续翻。
        """
        key = (self.sammy_line, self.lay.reply.width(), self.lay.reply.height())
        if self._fit_key != key:
            self._fit_cache = layout.fit_reply(self.sammy_line, self.lay.reply)
            self._fit_key = key
            self._reply_t0 = self.anim_t
        return self._fit_cache

    def _layout_input(self) -> None:
        """按当前缩放摆输入框。

        单独成方法是因为**窗口尺寸会被别人改**：小屏模式下实测窗管按"可用区域"
        动了我的窗口（我要 1800×1080，它给 1920×1044 —— 差的就是 GNOME 顶栏那 36px）。
        字体和输入框都得跟着走，不然大字小框看着就是坏的。
        """
        if self.face_only:
            self.input.hide()  # "只留一张脸" —— 输入框也不许出现
            return
        self.input.setStyleSheet(
            f"QLineEdit {{ background: rgba(18,42,26,190);"
            f" border: 2px solid rgba(61,220,90,110); border-radius: 16px;"
            f" color: #cfead6; padding-left: 18px;"
            f" font-size: {int(self.lay.font_input * self.scale)}px; }}"
        )
        self.input.setGeometry(
            int(self.lay.input.x() * self.scale) + self._offset[0],
            int(self.lay.input.y() * self.scale) + self._offset[1],
            int(self.lay.input.width() * self.scale),
            int(self.lay.input.height() * self.scale),
        )

    def resizeEvent(self, event) -> None:
        """窗口尺寸变了就按**实际**尺寸重算缩放。

        不做这件事会出这种局面（实测）：我按 1800×1080 画，窗管给我 1920×1044 ——
        宽度多 120、高度少 36，内容**恰好**因为底部留白够才没被切掉。
        那是运气，换块屏（或换个窗管/缩放）就露馅。所以这里跟着实际尺寸走。
        """
        super().resizeEvent(event)
        self._relayout()
        if self._kiosk_geom is None:
            self._layout_input()
            self.update()
            self._sync_crt_layer()
            return  # 桌面浮窗：缩放是我自己定的，不跟着窗口尺寸走
        f = screen.fit(faces.DEV_W, faces.DEV_H, self.width(), self.height())
        if abs(f.scale - self.scale) > 1e-3:
            self.scale = f.scale
            self._layout_input()
            self.update()
            self._sync_crt_layer()

    def _relayout(self) -> None:
        """重算版面（**设备单位**）。

        桌面浮窗：按 self.scale 反推 —— 画布恒为 800×480，和设计稿一模一样（行为不变）。
        小屏模式：按**实际**窗口尺寸算 —— 16:9 的屏上画布会变成 853×480，
        元素因此能横向铺满，而不是在右边白白空一条。
        """
        w, h = self.width(), self.height()
        if self._kiosk_geom is None:
            w, h = round(faces.DEV_W * self.scale), round(faces.DEV_H * self.scale)
        if w > 0 and h > 0:
            self.lay = layout.faceonly_layout(w, h) if self.face_only else layout.layout_dev(w, h)

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
            self.mood.save()
        else:
            # 心情每分钟都回归一点（不落盘，落盘按上面的节奏）
            self.mood.tick(hours_alone=self._hours_alone())

    def _hours_alone(self) -> float:
        """多久没人说话了。**启动那一刻算 0**（不是从 1970 年算起）。

        踩过的坑：`_last_interaction_at` 的初值是 `0.0`（表示"还没交互过"），
        直接拿它算小时数会得到 **49 万小时**，一下子把心情砸到下限 ——
        表现是"刚启动它就很蔫"。所以：没交互过 → 0；并且**封顶 24 小时**
        （睡一觉回来不该被算成"失踪一星期"）。
        """
        if not self._last_interaction_at:
            return 0.0
        return min(24.0, max(0.0, (time.time() - self._last_interaction_at) / 3600.0))

    def _idle_face_for(self) -> int:
        """空闲时摆哪张脸。

        **驱力管"困不困"，心情管"乐不乐"**：驱力已经明确（困了/无聊/想你）就听驱力的 ——
        累成那样还笑嘻嘻很假；驱力说"没什么特别"时，才由心情决定底色表情。
        """
        face = self.drives.expression()
        if face == EMOTIONS["normal"]:
            return mood_mod.idle_expression(self.mood.mood.valence)
        return face

    def _refresh_idle_look(self) -> None:
        """按驱力决定表情和状态文字。

        两道闸门都是为了**别抢戏**：
        1. 只在"心境"真的变了时才动手 —— 否则每秒重设一次，会盖掉刚回复完的表情
        2. 刚交互完的 5 秒内不动 —— 用户刚说完话，脸上不该立刻变回"无聊"
        """
        if time.time() - self._last_interaction_at < 5:
            return
        face = self._idle_face_for()
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
        self._save_recall()
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

        # ③ 能提旧事就提旧事 —— "想起你说的某件事"比"我又无聊了"更像活物。
        #    提不了（没候选 / 刚提过 / 今天超了）再退回原来的由头。
        recent = chat_text_since(chatlog.recent(50))
        rec = self.recall.decide(self.memory, recent_text=recent)
        self.last_recall_gate = rec
        if rec.ok and rec.item is not None:
            self._start_speaking(recall_prompt(rec.item.text), kind="recall", item_id=rec.item.id)
            return

        self._start_speaking(
            open_prompt(
                want_to_talk=self.drives.want_to_talk,
                closeness=self.drives.closeness,
                boredom=self.drives.boredom,
            ),
            kind="chat",
        )

    def _start_speaking(self, instruction: str, kind: str, item_id: str | None = None) -> None:
        """三种主动开口共用这条出口 —— 表情和状态文字按类型区分，机制只有一套。"""
        self.thinking = True
        self._line_until = 0.0  # 先说"想跟你说句话…"，别停在旧内容上
        self._speak_kind = kind
        self._speak_item_id = item_id
        self._speak_instruction = instruction
        if kind == "care":
            self.status = "该提醒你动一动了…"
            self.set_expression(5)  # 疑惑脸：它是在打量你
        elif kind == "recall":
            self.status = "想起了点旧事…"
            self.set_expression(7)  # 惊喜脸：眼睛一亮
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
        self._hold_line()  # face-only 的那一行：它自己开口说的也算
        self.set_expression(result.get("expression", 2))
        self.speaker.say(self.sammy_line)  # 主动开口同样要出声
        chatlog.append("assistant", self.sammy_line, kind="proactive")  # 标出来是它先说的
        kind = getattr(self, "_speak_kind", "chat")
        if kind == "care":
            self.status = f"提醒你动一动了 · {result.get('latency', 0):.1f}s"
            self.care.note_reminded()
            self._save_care()
        else:
            if kind == "recall":
                self.status = f"想起了点旧事 · {result.get('latency', 0):.1f}s"
            else:
                self.status = f"它自己开口了 · {result.get('latency', 0):.1f}s"
            self.attention.note_spoke()
            self._save_attention()
            if kind == "recall" and getattr(self, "_speak_item_id", None):
                self.recall.note_recalled(self._speak_item_id)
                self._save_recall()
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

    def _save_recall(self) -> None:
        try:
            self.recall.save()
        except OSError as e:
            print(f"  ⚠️ 回忆状态存不下来: {e}")

    def snooze_care(self) -> None:
        """推后休息提醒（右键菜单里）。

        这条路径必须有：**被硬催着起来的提醒，用户第一件事就是把它卸载掉。**
        给一个"现在别烦我"的出口，比把提醒做得更"聪明"有用得多。
        """
        self.care.snooze()
        self._save_care()
        self.my_line = ""
        self.sammy_line = "行，那再过半小时。"
        self._hold_line()
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
        # CRT 通道（U4）：内容先画进离屏缓冲叠辉光、再整张贴回；
        # 关着（SAMMY_CRT=off）走原来的直画路径。
        if self.crt_on:
            if self._crt_overlay is not None:
                self._crt_overlay.update(event.region())  # 质感层跟着内容重画
            self._paint_crt()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_content(p)
        p.end()

    def _paint_content(self, p: QPainter) -> None:
        """整幅画面画进一个选好目标的 painter（坐标：设计单位）。"""
        p.scale(self.scale, self.scale)  # 一行换屏：设备坐标 → 真实像素
        p.translate(*self._offset)  # 居中留边：先缩放再平移，量是设备坐标
        if self.face_only:
            self._paint_face_only(p)
        else:
            self._paint_full(p)

    def _paint_crt(self) -> None:
        """CRT 渲染通道：离屏缓冲 → 叠辉光 → 整张贴回。

        为什么不只画脏区：辉光要读到全图的亮像素（脸、文字、点），只拿局部
        缓冲会把边界以外的光裁掉、接缝看得出来。30fps 下这点开销能接受
        （真要省电就走 SAMMY_CRT=off 的直画路径）。
        """
        dpr = self.devicePixelRatioF()
        w_px = max(1, round(self.width() * dpr))
        h_px = max(1, round(self.height() * dpr))
        buf = self._crt_buf
        if buf is None or buf.width() != w_px or buf.height() != h_px:
            buf = QImage(w_px, h_px, QImage.Format_ARGB32_Premultiplied)
            buf.setDevicePixelRatio(dpr)
            self._crt_buf = buf
        buf.fill(Qt.transparent)
        bp = QPainter(buf)
        bp.setRenderHint(QPainter.Antialiasing)
        self._paint_content(bp)
        bp.end()
        crt.compose_glow(
            buf,
            panel=self.lay.panel,
            panel_radius=self.lay.panel_radius,
            scale=self.scale,
            offset=self._offset,
        )
        p = QPainter(self)
        p.drawImage(0, 0, buf)
        p.end()

    def _sync_crt_layer(self) -> None:
        """（重）建质感层：窗口尺寸 / 缩放 / 像素密度变了都要重建。"""
        ov = self._crt_overlay
        if ov is None:
            return
        ov.setGeometry(0, 0, self.width(), self.height())
        ov.raise_()  # 永远压在输入框上面
        dpr = self.devicePixelRatioF()
        ov.set_layer(
            crt.build_layer(
                max(1, round(self.width() * dpr)),
                max(1, round(self.height() * dpr)),
                panel=self.lay.panel,
                panel_radius=self.lay.panel_radius,
                scale=self.scale,
                offset=self._offset,
                dpr=dpr,
            )
        )

    def _draw_face(self, p: QPainter) -> None:
        """画那张脸：有动图就播动图，没有就退回落单张。

        形变（眨眼/呼吸/凝视/好奇拉高）以**脸中心**为轴；
        换表情时交叉淡化 —— 老脸淡出、新脸淡入，不许"啪"地切断。
        画框取自**版面**（`self.lay.face`）：完整版里等于设计位，face-only 里是放大的脸。
        """
        box = self.lay.face
        fr = self.anim.frame_at(self.anim_t, calm=self.expression == SLEEP_EXPR)
        prev, alpha = self.anim.expr_fade(self.anim_t)
        p.save()
        if not fr.idle:
            # 形变以**脸中心**为轴：这样压扁读起来是"闭眼"，不是"沉下去"
            p.translate(box.center().x() + fr.dx + fr.gx, box.center().y() + fr.dy + fr.gy)
            p.scale(fr.pop, fr.pop * fr.squash * fr.stretch)
            p.translate(-box.center().x(), -box.center().y())
        if prev is not None and alpha < 1.0:
            # 交叉淡化：两张脸各半的时候，读起来是"变过去"而不是"切过去"
            p.setOpacity(1.0 - alpha)
            self._draw_face_image(p, prev, box)
            p.setOpacity(alpha)
            self._draw_face_image(p, self.expression, box)
            p.setOpacity(1.0)
        else:
            self._draw_face_image(p, self.expression, box)
        p.restore()

    def _draw_face_image(self, p: QPainter, index: int, box: QRect) -> None:
        """画单张脸（动图当前帧或静态位图）—— 淡化时两张脸共用这一条路径。"""
        moving = faces.motion_frame(index, self.anim_t)
        if moving is not None:
            p.drawImage(box, moving)
        else:
            p.drawPixmap(box.topLeft(), faces.face_pixmap(index, QSize(box.width(), box.height())))

    def _paint_full(self, p: QPainter) -> None:
        """完整版面：面板 + 脸 + 状态行 + 对话区 + 输入框。"""
        L = self.lay
        p.setPen(QPen(GREEN_DIM, 3))
        p.setBrush(BEZEL)
        p.drawRoundedRect(L.panel, L.panel_radius, L.panel_radius)

        self._draw_face(p)

        # 状态行：表情名 · 状态灯 ~~~~ 状态文字
        label = f"{emoji_of(self.expression)} {name_of(self.expression)}"
        p.setFont(QFont(layout.FAMILY, L.font_label))
        p.setPen(GREEN)
        p.drawText(
            QRect(L.status.x(), L.status.y(), L.status.width() * 7 // 10, L.status.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            label,
        )
        dot_x = L.status.x() + QFontMetrics(p.font()).horizontalAdvance(label) + 18
        p.setFont(QFont(layout.FAMILY, L.font_status))
        p.setPen(TEXT if self.status_ok else WARN)
        p.drawText(
            QRect(dot_x + 20, L.status.y(), L.status.right() + 1 - dot_x - 20, L.status.height()),
            Qt.AlignRight | Qt.AlignVCenter,
            self._status_shown(),  # 思考中：句尾省略号换成会动的点（U3）
        )
        p.setBrush(GREEN if self.status_ok else WARN)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(dot_x, L.status.y() + L.status.height() // 2), 7, 7)

        # 分隔线
        p.setPen(QPen(GREEN_DIM, 2))
        p.drawLine(L.my_line.x(), L.divider_y, L.my_line.x() + L.my_line.width(), L.divider_y)

        # 对话区
        if self.my_line:
            p.setFont(QFont(layout.FAMILY, L.font_my))
            p.setPen(TEXT_DIM)
            p.drawText(
                L.my_line,
                Qt.AlignLeft | Qt.AlignVCenter,
                QFontMetrics(p.font()).elidedText(
                    f"你：{self.my_line}", Qt.ElideRight, L.my_line.width()
                ),
            )

        # 回复文字：大字一页放得下就一页；放不下缩小；还放不下就翻页（绝不裁字）。
        # 显示内容由打字机给（U3）：逐字出现；思考中换成会动的点。
        fit = self._reply_fit()
        page_i, shown = self._reply_shown()
        p.setFont(QFont(layout.FAMILY, fit.size))
        p.setPen(TEXT)
        p.drawText(L.reply, layout.REPLY_FLAGS, shown)
        if fit.paged:
            # 翻页提示：让人知道"后面还有"，别以为话说到一半就没了
            p.setFont(QFont(layout.FAMILY, max(12, L.font_my - 2)))
            p.setPen(TEXT_DIM)
            p.drawText(
                L.reply,
                Qt.AlignRight | Qt.AlignBottom,
                f"{page_i + 1}/{len(fit.pages)}",
            )

        # 关闭按钮
        self._draw_close(p)

    def _paint_face_only(self, p: QPainter) -> None:
        """face-only 版面：**一张大脸 + 一行文字**，别的什么都没有。

        那一行显示什么由 `face_line()` 定：它刚说的话（说完 20 秒内）> 状态。
        小屏上这行也是唯一的报错出口（status_ok=False 时变警示色）。
        """
        L = self.lay
        p.setPen(QPen(GREEN_DIM, 3))
        p.setBrush(BEZEL)
        p.drawRoundedRect(L.panel, L.panel_radius, L.panel_radius)

        self._draw_face(p)

        text, fresh = self.face_line()
        # 刚说的话：也逐字出现；其余时间显示状态（思考中句尾的点会动）
        text = self._typed_line(text) if fresh else self._status_shown()
        p.setFont(QFont(layout.FAMILY, L.font_status))
        if not self.status_ok:
            p.setPen(WARN)
        elif fresh:
            p.setPen(TEXT)
        else:
            p.setPen(TEXT_DIM)  # 平时状态是背景信息，安静点，不抢脸的戏
        p.drawText(
            L.status,
            Qt.AlignCenter,
            QFontMetrics(p.font()).elidedText(text, Qt.ElideRight, L.status.width()),
        )

        self._draw_close(p)

    def _draw_close(self, p: QPainter) -> None:
        """关闭按钮 —— 两种版面共用（永远在右上角）。"""
        L = self.lay
        p.setPen(QPen(GREEN_DIM, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(L.close_c, L.close_r, L.close_r)
        p.setPen(GREEN)
        p.drawText(
            QRect(
                L.close_c.x() - L.close_r,
                L.close_c.y() - L.close_r,
                L.close_r * 2,
                L.close_r * 2,
            ),
            Qt.AlignCenter,
            "✕",
        )

    # ── 交互 ────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = event.position() / self.scale
        if (pos - self.lay.close_c).manhattanLength() < self.lay.close_r * 1.6:
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
