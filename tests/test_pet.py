"""窗口逻辑 —— 表情切换、空闲行为、对话接线、各条降级路径。

全部离屏跑，大脑和记忆都注入假件，不联网、不碰真实记忆库。
"""

import pytest

from sammy.expressions import EMOTIONS
from sammy.pet import POKE_FACES, POKE_QUIPS, SammyWindow

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """本模块所有测试都不许碰**用户真实的状态文件**（驱力 / 心跳）。

    默认路径在 ~/Library/Application Support/Sammy/ 下 —— 测试一旦写进去，
    就是拿你的真实数据当实验品。（记忆库那边已经是用 tmp_path 注入的了，
    驱力和心跳这两处是后加的，容易漏。）
    """
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


class FakeBrain:
    """假大脑：记录被问过什么，返回可预测的结果。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.spoke: list[tuple[str, str]] = []
        self.extracted: list[tuple[str, str]] = []

    def chat(self, text, memory_context="", on_event=None):
        self.calls.append((text, memory_context))
        if self.fail:
            raise RuntimeError("网络炸了")
        return {"reply": "假的回复", "emotion": "happy", "expression": 4, "latency": 0.12}

    def speak_first(self, instruction, memory_context=""):
        """主动开口 —— 单独记，才能断言"是它自己开的口"而不是"回了谁的话"。"""
        self.spoke.append((instruction, memory_context))
        if self.fail:
            raise RuntimeError("网络炸了")
        return {
            "reply": "我自己想说话",
            "emotion": "expect",
            "expression": 32,
            "latency": 0.2,
            "proactive": True,
        }

    def extract_memories(self, user_text, reply, known_slots):
        self.extracted.append((user_text, reply))
        return {"slots": {"favorite": "美式"}, "journal": ["聊了咖啡"]}


class FakeMemory:
    """假记忆库：够用的接口 + 记录写入。"""

    def __init__(
        self,
        block: str = "",
        broken: bool = False,
        slots_data: dict | None = None,
        journal_rows: list | None = None,
    ):
        self._block = block
        self.broken = broken
        self.slots_written: dict[str, str] = dict(slots_data or {})
        self.journal: list[str] = []
        self._rows = list(journal_rows or [])  # 回忆用：带 id/kind/text/ts 的假日记行

    def context_block(self, *a, **k):
        return self._block

    def slots(self):
        if self.broken:
            raise RuntimeError("记忆库坏了")
        return dict(self.slots_written)

    def entries_between(self, start, end, kinds=("event", "explicit", "digest")):
        if self.broken:
            raise RuntimeError("记忆库坏了")
        return [r for r in self._rows if start <= r["ts"] <= end and r["kind"] in kinds]

    def set_slot(self, key, value, source=""):
        self.slots_written[key] = value

    def add(self, text, kind="event", **k):
        self.journal.append(text)
        return len(self.journal)


@pytest.fixture
def win():
    w = SammyWindow(autoconnect=False)
    yield w
    w.close()


# ── 启动与降级 ────────────────────────────────────


def test_no_brain_no_memory_does_not_crash(win):
    """没接大脑也不能崩 —— 这是 P0-6 的要求。"""
    assert win.brain is None
    assert win.memory is None
    assert win.expression == 3  # 微笑开场


def test_send_without_brain_degrades_gracefully(win):
    win.input.setText("你好")
    win.send()
    assert win.thinking is False
    assert "接通" in win.sammy_line or "凭证" in win.sammy_line
    assert win.expression == 17  # 生病脸
    assert win.input.text() == ""  # 输入框要清空，不能把用户的话吞着


def test_empty_input_is_ignored(win):
    win.brain = FakeBrain()
    win.input.setText("   ")
    win.send()
    assert win.brain.calls == []
    assert win.thinking is False


# ── 表情 ──────────────────────────────────────────


def test_set_expression_accepts_valid(win):
    win.set_expression(21)
    assert win.expression == 21


def test_set_expression_rejects_unknown(win):
    before = win.expression
    win.set_expression(999)
    assert win.expression == before, "非法编号不能让状态坏掉"


def test_poke_changes_face_and_quips(win):
    win.poke()
    assert win.expression in POKE_FACES
    assert win.sammy_line in POKE_QUIPS
    assert win.my_line == ""


def test_poke_is_ignored_while_thinking(win):
    """正在思考时戳它不该打断（也不该把思考脸换掉）。"""
    win.thinking = True
    win.set_expression(16)
    win.poke()
    assert win.expression == 16


# ── 空闲行为（归驱力系统管，不再是硬编码定时器）──────


def test_idle_when_tired_shows_sleepy_face(win):
    win.drives.energy = 0.2
    win._tick()
    assert win.expression == EMOTIONS["sleepy"]
    assert win.status == "有点困了"


def test_idle_when_exhausted_falls_asleep(win):
    win.drives.energy = 0.05
    win._tick()
    assert win.expression == EMOTIONS["sleep"]
    assert win.status == "睡着了"


def test_idle_boredom_shows_on_its_face(win):
    """无聊和犯困必须长得不一样 —— 否则"驱力系统"等于只做了一条。"""
    win.drives.boredom = 0.8
    win._tick()
    bored = win.expression
    assert bored == EMOTIONS["bored"]

    win.drives.boredom = 0.05
    win.drives.energy = 0.2
    win._tick()
    assert win.expression != bored


def test_a_fresh_reply_is_not_stomped_by_the_idle_face(win):
    """刚交互完的 5 秒内，驱力不该抢戏把表情换掉。"""
    import time

    win._last_interaction_at = time.time()
    win.set_expression(EMOTIONS["love"])
    win.drives.energy = 0.05  # 状态上"该睡了"
    win._tick()
    assert win.expression == EMOTIONS["love"], "用户刚说完话，脸不该立刻变"


def test_idle_face_is_only_set_when_it_changes(win):
    """心境没变就不该动手 —— 否则会在别处刚设好表情的一瞬间把它盖掉。"""
    win.drives.energy = 0.2
    win._tick()
    assert win.expression == EMOTIONS["sleepy"]

    win.set_expression(EMOTIONS["love"])  # 假装别处刚改过（比如刚回完话）
    win._tick()  # 心境没变
    assert win.expression == EMOTIONS["love"], "心境没变就该让别处的更新留着"


def test_idle_does_not_advance_while_thinking(win):
    win.thinking = True
    win.idle_seconds = 119
    win._tick()
    assert win.idle_seconds == 119, "思考中不该被当成空闲"


# ── 交互会改驱力 ──────────────────────────────────


def test_poke_relieves_boredom(win):
    win.drives.boredom = 0.9
    win.poke()
    assert win.drives.boredom < 0.9


def test_sending_a_message_counts_as_reaching_out(win):
    """主动说话比随手戳一下更有分量。"""
    win.drives.boredom = 0.9
    win.drives.closeness = 0.3
    before = win.drives.closeness
    win.input.setText("在吗")
    win.send()
    assert win.drives.closeness > before
    assert win.drives.boredom < 0.9


# ── 主动心跳接线 ──────────────────────────────────


@pytest.fixture
def chatty(win, monkeypatch):
    """把免打扰时段关掉，让这套测试**与现在几点无关**。

    ⚠️ 不这么做的话，它们白天绿、半夜红 —— 而它们本来要验的是别的东西。
    时间相关的测试必须自己控制时间，不能依赖"什么时候跑"。
    """
    from sammy import attention

    monkeypatch.setattr(attention, "QUIET_START", 0)
    monkeypatch.setattr(attention, "QUIET_END", 0)  # 0 <= hour < 0 恒假 = 没有免打扰
    win.brain = FakeBrain()
    win.drives.boredom = 1.0
    win.drives.energy = 0.8
    win.drives.closeness = 0.8
    win._started_at = 0.0  # 早过了启动宽限
    win._last_interaction_at = 0.0  # 从没交互过 = 很安静
    return win


def test_speaks_up_when_everything_allows(chatty):
    """规则引擎必须**真的可能触发** —— 会挑刺的规则很多，会开口的才算功能。"""
    chatty._heartbeat()
    assert chatty.thinking, "什么都满足时该进入'想说话'状态"
    assert chatty.last_gate and chatty.last_gate.ok
    chatty._speak_up("测试指令")  # 同步跑，免得等线程
    assert chatty.brain.spoke, "应该走 speak_first 这条路，而不是 chat()"
    assert not chatty.brain.calls, "主动开口不该被当成'回了谁的话'"


def test_stays_quiet_when_it_does_not_feel_like_talking(chatty):
    chatty.drives.boredom = 0.0
    chatty.drives.closeness = 0.9
    chatty._heartbeat()
    assert not chatty.thinking, "它自己不想说话时不许说"
    assert not chatty.last_gate.ok
    assert "不想说" in chatty.last_gate.reason


def test_stays_quiet_right_after_a_chat(chatty):
    import time

    chatty._last_interaction_at = time.time()
    chatty._heartbeat()
    assert not chatty.thinking


def test_heartbeat_does_nothing_while_thinking(chatty):
    chatty.thinking = True
    chatty._heartbeat()
    assert not chatty.brain.spoke


def test_proactive_line_leaves_your_side_empty(chatty):
    """它自己开的口，不是回给你的 —— 界面里"你"那一侧该是空的。"""
    chatty.my_line = "我说过的话"
    chatty._on_spoke_up(chatty.brain.speak_first("指令"))
    assert chatty.my_line == ""
    assert chatty.sammy_line == "我自己想说话"
    assert chatty.expression == 32


def test_speaking_costs_todays_quota(chatty):
    assert chatty.attention.spoken_today == 0
    chatty._on_spoke_up(chatty.brain.speak_first("指令"))
    assert chatty.attention.spoken_today == 1


def test_generation_failure_does_not_burn_quota(chatty):
    """生成失败不该消耗今天的机会 —— 否则网络抖一下，今天就再也不会主动了。"""
    chatty.brain.fail = True
    chatty._heartbeat()
    chatty._speak_up("测试指令")
    assert chatty.attention.spoken_today == 0


def test_care_reminder_takes_priority_over_chatting(chatty):
    """你坐太久时，先提醒你起来动动，而不是先找你闲聊。

    关心身体比找人聊要紧 —— 而且两者不能在同一分钟各说一句（那就是两条消息）。
    """
    import time

    from sammy.care import Care

    now = time.time()
    c = Care()
    start = now - 45 * 60
    c.note_activity(now=start)
    for m in range(5, 46, 5):  # 模拟"一直在用"
        c.note_activity(now=start + m * 60)
    chatty.care = c
    chatty.drives.boredom = 1.0  # 它其实也很想聊

    chatty._heartbeat()
    assert chatty._speak_kind == "care", "该先提醒你动一动"
    assert chatty.last_care_gate.ok
    assert chatty.thinking


def test_care_reminder_does_not_burn_the_chat_quota(chatty):
    """两件事各记各的账 —— 提醒你休息不该算作"它今天找过你 3 次"。"""
    chatty._speak_kind = "care"
    chatty._on_spoke_up(chatty.brain.speak_first("提醒你动一动"))
    assert chatty.attention.spoken_today == 0
    assert chatty.care.last_reminded is not None


def test_care_reminder_shows_on_the_chat_line(chatty):
    """提醒也是它主动开口，所以走同一条显示路径（你那一侧同样是空的）。"""
    chatty.my_line = "我说过的话"
    chatty._speak_kind = "care"
    chatty._on_spoke_up(chatty.brain.speak_first("提醒你动一动"))
    assert chatty.my_line == ""
    assert chatty.sammy_line == "我自己想说话"


def test_snooze_from_the_menu_is_reachable(chatty):
    """「推后」必须有真能点到的地方 —— 否则被催烦了只能卸载。"""
    import time

    from sammy.care import SNOOZE_MINUTES

    chatty.snooze_care()
    assert chatty.care.snooze_until is not None, "推后没生效"
    assert chatty.care.snooze_until > time.time() + (SNOOZE_MINUTES - 1) * 60
    assert not chatty.care.due().ok, "推后之后不该还在催"
    assert "推后" in chatty.status or "半小时" in chatty.status


def test_kiosk_mode_fills_the_screen_without_stretching(win):
    """小屏模式：窗口**铺满整屏**、**内容自适应**（画布跟着屏变宽/变高），但脸绝不拉伸。

    判据在 2026-10-05 改过：以前是"窗口 = 等比内容（1800×1080）+ 居中黑边"，
    现在是"窗口铺满 + 版面自己铺开"。原因是 16:9 屏上等比居中会在右侧白留一条，
    而回复文字最缺的正是宽度。这条测试原来钉的是旧行为，所以一起改。
    """
    import pytest

    from sammy import screen
    from sammy.faces import DEV_H, DEV_W, face_box
    from sammy.pet import SammyWindow

    s = screen.list_screens()[0]
    k = SammyWindow(kiosk=True, display=s["index"], autoconnect=False)
    assert k.scale == pytest.approx(min(s["width"] / DEV_W, s["height"] / DEV_H)), "缩放没按屏算"
    assert (k.width(), k.height()) == (s["width"], s["height"]), "没铺满整块屏"
    # 内容自适应：画布 = 窗口 ÷ 缩放，且不小于设计基准
    assert k.lay.canvas_w == pytest.approx(k.width() / k.scale, rel=1e-2)
    assert k.lay.canvas_w >= DEV_W and k.lay.canvas_h >= DEV_H
    # 不拉伸：脸的宽高比还是设计比例
    fb = face_box()
    assert k.lay.face.width() / k.lay.face.height() == pytest.approx(
        fb.width() / fb.height(), rel=0.06
    )
    # 偏移必须是 0：窗口已经贴边，再平移一次会把内容推出窗口（右边被吃掉）
    assert k._offset == (0, 0)


def test_kiosk_does_not_crash_when_the_screen_reports_0x0(win, monkeypatch):
    """显示器没接 / 没信号时 Qt 会报 0×0 —— 这里**不许崩**。

    实测踩到：小屏断开时 kiosk 启动直接 `ValueError` 退出，
    人看到的表现是"插上屏 Sammy 也不见了"，还会以为是自己弄坏的。
    正确做法是先按设计尺寸把窗建出来（屏一恢复 resizeEvent 会自动重算）。
    """
    from sammy import screen as screen_mod
    from sammy.pet import SammyWindow

    monkeypatch.setattr(
        screen_mod,
        "resolve_screen",
        lambda want=None: {
            "index": 1,
            "name": "HDMI-0",
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
            "primary": False,
        },
    )
    k = SammyWindow(kiosk=True, display="HDMI-0", autoconnect=False)
    assert k.width() > 0 and k.height() > 0, "窗口尺寸还是 0（等于起不来）"
    assert k.lay.canvas_w >= 800 and k.lay.canvas_h >= 480, "没有兜底版面"


def test_desktop_mode_still_uses_the_default_scale(win):
    """不指定小屏模式时行为不变（桌面浮窗照旧）。"""
    from sammy.faces import DEV_H, DEV_W
    from sammy.pet import DEFAULT_SCALE, SammyWindow

    w = SammyWindow(autoconnect=False)
    assert w.scale == DEFAULT_SCALE
    assert (w.width(), w.height()) == (int(DEV_W * DEFAULT_SCALE), int(DEV_H * DEFAULT_SCALE))


# ── 对话接线 ──────────────────────────────────────


def test_reply_updates_face_and_status(win):
    win.brain = FakeBrain()
    win._call_brain("今天好累")
    assert win.sammy_line == "假的回复"
    assert win.expression == 4
    assert win.thinking is False
    assert win.status_ok is True
    assert "在线" in win.status


def test_memory_context_is_passed_to_brain(win):
    """记忆必须真的塞进提示词 —— 否则"记得你"是假的。

    2026-10-11 起上下文里**还多一行心情**（语气要跟着底色走），
    所以判据从"等于记忆块"改成"包含记忆块" —— 顺带也钉住心情那行确实进去了。
    """
    brain = FakeBrain()
    win.brain = brain
    win.memory = FakeMemory("【你记得关于 Rowan 的事】\n- preferred_name：Rowan")
    win._call_brain("我叫什么")
    sent = brain.calls[0][1]
    assert win.memory._block in sent, "记忆没进上下文"
    assert "Rowan" in sent
    assert "心情" in sent, "心情那行没进上下文（语气就不会跟着底色走）"


def test_a_warm_reply_lifts_the_mood(win):
    """回复的情绪要真的推动**底色** —— 不是只换一张脸就完事。"""
    win.brain = FakeBrain()  # 它的回复带 expression=4（开心）
    before = win.mood.mood.valence
    win._call_brain("你今天怎么样")
    assert win.mood.mood.valence > before, "开心的回复没有推动心情"


def test_poking_lifts_the_mood(win):
    """有人来逗它，底色总会好一点。"""
    before = win.mood.mood.valence
    win.poke()
    assert win.mood.mood.valence > before


def test_hours_alone_does_not_explode_before_the_first_interaction(win):
    """启动那一刻不该被算成"没人理 49 万小时"。

    踩过：`_last_interaction_at` 初值是 0.0，直接减 time.time() 会得到天文数字，
    于是"刚启动它就很蔫"。所以没交互过算 0，且封顶 24 小时。
    """
    import time as _t

    assert win._hours_alone() == 0.0, "还没交互过，应当算 0"
    win._last_interaction_at = _t.time() - 100 * 3600
    assert win._hours_alone() == 24.0, "睡一觉回来不该被算成失踪一星期"


def test_idle_face_follows_the_mood_when_drives_are_neutral(win):
    """驱力说"没什么特别"时，空闲的脸由心情决定。"""
    from sammy import mood as mood_mod

    win.mood.mood.valence = 0.9  # 心情很好
    assert win._idle_face_for() == mood_mod.idle_expression(0.9)
    win.mood.mood.valence = -0.4  # 心情低落
    assert win._idle_face_for() == mood_mod.idle_expression(-0.4)
    assert win._idle_face_for() != mood_mod.idle_expression(0.9)


def test_drives_win_when_it_is_sleepy(win):
    """累到睡着时，心情再好也得摆睡脸 —— 累成那样还笑嘻嘻很假。"""
    from sammy.drives import EMOTIONS

    win.mood.mood.valence = 1.0
    win.drives.asleep = True
    assert win._idle_face_for() == EMOTIONS["sleep"]


def test_extraction_runs_after_reply(win):
    brain = FakeBrain()
    win.brain = brain
    mem = FakeMemory()
    win.memory = mem
    win._call_brain("我爱喝咖啡")
    assert brain.extracted == [("我爱喝咖啡", "假的回复")], "回复之后要抽记忆"
    assert mem.slots_written == {"favorite": "美式"}, "抽出来的槽位要落库"
    assert mem.journal == ["聊了咖啡"]
    assert "记住了" in win.status


def test_memory_failure_does_not_clobber_the_reply(win):
    """真 bug 回归：记忆写入失败曾把已经给出的回复覆盖成"我卡住了"。

    回复和记忆是两件事 —— 记忆坏了，用户该看到的答案一个字都不能少。
    """
    win.brain = FakeBrain()
    win.memory = FakeMemory(broken=True)
    win._call_brain("我爱喝咖啡")
    assert win.sammy_line == "假的回复", "回复被记忆故障吃掉了"
    assert win.status_ok is True
    assert win.expression == 4


def test_brain_failure_shows_sad_face(win):
    win.brain = FakeBrain(fail=True)
    win._call_brain("在吗")
    assert win.thinking is False
    assert win.status_ok is False
    assert win.expression == 6  # 伤心脸
    assert "网络炸了" in win.sammy_line


def test_failure_does_not_lose_the_window(win):
    """出错之后还能继续聊 —— 不能一次失败就进入不可用状态。"""
    win.brain = FakeBrain(fail=True)
    win._call_brain("第一次")
    win.brain = FakeBrain()
    win.input.setText("第二次")
    win.send()
    assert win.thinking is True  # 重新进入思考态
    assert win.my_line == "第二次"


# ── 状态文案 ──────────────────────────────────────


def test_memory_status_text(win):
    win._on_memory({"explicit": True, "slots": 2, "journal": 1})
    assert "2 条事实" in win.status
    assert "1 条记录" in win.status
    assert "你要我记的" in win.status


def test_memory_status_ignored_when_nothing_learned(win):
    before = win.status
    win._on_memory({"explicit": False, "slots": 0, "journal": 0})
    assert win.status == before


def test_consolidated_status_text(win):
    win._on_consolidated({"day": "2026-10-01", "digest": "今天聊了项目"})
    assert "2026-10-01" in win.status
    assert "理了理" in win.status


def test_nightly_skipped_without_brain_or_memory(win):
    """没有大脑/记忆时不该乱跑整理（也不该抛异常）。"""
    win._maybe_consolidate()  # 不应抛异常

    win.brain = FakeBrain()
    win.memory = None
    win._maybe_consolidate()


# ── 回忆主动性接线 ────────────────────────────────


def _recall_mem(slots: dict | None = None, events: list | None = None) -> FakeMemory:
    import time as _t

    rows = [
        {"id": i + 1, "kind": "event", "text": text, "ts": _t.time() - age_days * 86400}
        for i, (text, age_days) in enumerate(events or [])
    ]
    return FakeMemory(
        slots_data=slots if slots is not None else {"name": "Rowan"},
        journal_rows=rows,
    )


def test_heartbeat_brings_up_something_it_remembers(chatty):
    """心跳先问"有没有旧事可提" —— 有就提旧事，而不是又一次"我无聊了"。"""
    chatty.memory = _recall_mem()
    chatty._heartbeat()
    assert chatty.thinking
    assert chatty._speak_kind == "recall"
    assert chatty.last_recall_gate.ok
    assert chatty._speak_item_id == "slot:name"
    chatty._speak_up(chatty._speak_instruction)  # 同步跑，免得等线程
    assert any("Rowan" in instr for instr, _ in chatty.brain.spoke), "旧事没进指令"
    assert not chatty.brain.calls, "主动开口不该被当成回了谁的话"


def test_without_anything_to_recall_it_falls_back_to_its_topics(chatty):
    chatty.memory = FakeMemory()  # 空记忆
    chatty._heartbeat()
    assert chatty._speak_kind == "chat"
    assert chatty.last_recall_gate is not None and not chatty.last_recall_gate.ok


def test_recall_daily_cap_falls_back_to_topics(chatty):
    import time as _t

    from sammy.recall import MAX_RECALLS_PER_DAY

    chatty.memory = _recall_mem()
    chatty.recall.recalled_today = MAX_RECALLS_PER_DAY
    chatty.recall.day = _t.strftime("%Y-%m-%d")
    chatty._heartbeat()
    assert chatty._speak_kind == "chat", "回忆额度用完就该退回普通由头"


def test_recall_counts_against_both_quotas(chatty):
    import random

    chatty.memory = _recall_mem()
    chatty._heartbeat()
    item_id = chatty._speak_item_id
    chatty._on_spoke_up(chatty.brain.speak_first("x"))
    assert chatty.attention.spoken_today == 1, "它开口了，就要记主动额度"
    assert chatty.recall.recalled_today == 1, "回忆也要记自己的账"
    assert item_id in chatty.recall.recent_items
    g = chatty.recall.decide(chatty.memory, rng=random.Random(0))
    assert not g.ok, "唯一一条刚提过，马上不该能再提"


def test_recall_generation_failure_does_not_burn_quotas(chatty):
    chatty.memory = _recall_mem()
    chatty.brain.fail = True
    chatty._heartbeat()
    chatty._speak_up(chatty._speak_instruction)
    assert chatty.recall.recalled_today == 0, "生成失败不该消耗回忆额度"
    assert chatty.attention.spoken_today == 0


def test_does_not_recall_what_was_just_discussed(chatty):
    import time as _t

    from sammy import chatlog

    chatlog.append("user", "你的项目桌面机器人 Sammy 怎么样了", when=_t.time())
    chatty.memory = _recall_mem(slots={"current_project": "桌面机器人 Sammy"})
    chatty._heartbeat()
    assert chatty._speak_kind == "chat", "刚聊过的事不该又想起来"


def test_recall_shows_a_distinct_status(chatty):
    chatty.my_line = "我说过的话"
    chatty._speak_kind = "recall"
    chatty._speak_item_id = "slot:name"
    chatty._on_spoke_up(chatty.brain.speak_first("x"))
    assert chatty.my_line == "", "它自己开的口，你那一侧是空的"
    assert "想起" in chatty.status


# ── face-only 形态（T3：小屏上只留一张脸 + 一行状态）──────────


def test_faceonly_window_hides_the_input_and_uses_the_big_face(win):
    """face-only：输入框藏起来，版面换成"一张更大的脸"那套。"""
    from sammy import layout as layout_mod
    from sammy.pet import SammyWindow

    fo = SammyWindow(face_only=True, autoconnect=False)
    try:
        assert isinstance(fo.lay, layout_mod.FaceOnlyLayout)
        assert fo.input.isHidden(), "face-only 里输入框还露着"
        assert not win.input.isHidden(), "完整版里输入框不该被藏"
        assert fo.lay.face.width() > win.lay.face.width() * 1.4, "脸没换成大的"
    finally:
        fo.close()


def test_faceonly_line_prefers_what_it_just_said(win):
    """那一行的显示次序：**它刚说的话**（20 秒内）> 状态。"""
    import time as _t

    from sammy.pet import FACEONLY_LINE_HOLD, SammyWindow

    fo = SammyWindow(face_only=True, autoconnect=False)
    try:
        fo.status = "在线 · 0.5s"
        assert fo.face_line() == ("在线 · 0.5s", False), "没话说时该显示状态"

        fo.sammy_line = "刚说完的一句"
        fo._hold_line()
        text, fresh = fo.face_line()
        assert text == "刚说完的一句" and fresh is True
        # 停留时长就是设计值（±1 秒容差）
        assert abs((fo._line_until - _t.time()) - FACEONLY_LINE_HOLD) < 1.0

        # 时间过去后回到状态行 —— 它刚说的话不该永远赖着不走
        fo._line_until = _t.time() - 1
        assert fo.face_line() == ("在线 · 0.5s", False)
    finally:
        fo.close()


def test_faceonly_reply_lands_on_the_single_line(win):
    """真实回复路径：回完话，那一行必须换成它说的话（不是还挂着状态）。"""
    from sammy.pet import SammyWindow

    fo = SammyWindow(face_only=True, autoconnect=False)
    try:
        fo.brain = FakeBrain()
        fo._call_brain("你好")
        text, fresh = fo.face_line()
        assert text == "假的回复" and fresh is True
    finally:
        fo.close()


def test_faceonly_new_message_clears_the_old_reply_from_the_line(win):
    """你刚说了话：那一行该回到"思考中…"，别停在它上一条回复上。"""
    from sammy.pet import SammyWindow

    fo = SammyWindow(face_only=True, autoconnect=False)
    try:
        fo.sammy_line = "上一条回复"
        fo._hold_line()
        fo.brain = FakeBrain()
        fo.input.setText("在吗")
        fo.send()
        assert fo.face_line() == ("思考中…", False)
    finally:
        fo.close()


def test_faceonly_renders_without_crashing(win):
    """渲染路径要走得通：很长的一句话（必须省略号收尾）+ grab 不崩。"""
    from sammy.pet import SammyWindow

    fo = SammyWindow(face_only=True, autoconnect=False)
    try:
        fo.sammy_line = "这是一句非常长的话" * 12
        fo._hold_line()
        fo.update()
        img = fo.grab()
        assert not img.isNull()
        assert (img.width(), img.height()) == (fo.width(), fo.height())
    finally:
        fo.close()


def test_face_region_covers_the_real_face_in_every_mode(win):
    """动画的局部刷新区域必须真的盖住那张脸 —— 否则脸动画只刷一小块（脸会花）。

    踩到过：老代码按**设计位**的脸框算区域；face-only 下脸不在那儿（面积差一大截），
    kiosk 上画布变宽后脸被重新居中过、也偏着 —— 都靠"用版面里的脸"一并修掉。
    """
    from PySide6.QtCore import QRect

    from sammy import screen
    from sammy.pet import SammyWindow

    s = screen.list_screens()[0]
    windows = [win, SammyWindow(face_only=True, autoconnect=False)]
    windows.append(SammyWindow(kiosk=True, display=s["index"], autoconnect=False))
    try:
        for w in windows:
            L = w.lay
            px = QRect(
                round(L.face.x() * w.scale),
                round(L.face.y() * w.scale),
                round(L.face.width() * w.scale),
                round(L.face.height() * w.scale),
            )
            assert w._face_region().contains(px), f"脸没被刷新区盖住（face_only={w.face_only}）"
    finally:
        for w in windows[1:]:
            w.close()


def test_faceonly_kiosk_fills_the_screen_with_the_big_face(win):
    """face-only + kiosk：铺满整屏，脸还是大的（真机上就是这么跑的）。"""
    from sammy import layout as layout_mod
    from sammy import screen
    from sammy.pet import SammyWindow

    s = screen.list_screens()[0]
    k = SammyWindow(kiosk=True, face_only=True, display=s["index"], autoconnect=False)
    try:
        assert isinstance(k.lay, layout_mod.FaceOnlyLayout)
        assert (k.width(), k.height()) == (s["width"], s["height"]), "没铺满整块屏"
        full = layout_mod.layout_dev(s["width"], s["height"])
        assert k.lay.face.width() > full.face.width() * 1.4
    finally:
        k.close()
