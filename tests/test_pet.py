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

    def __init__(self, block: str = "", broken: bool = False):
        self._block = block
        self.broken = broken
        self.slots_written: dict[str, str] = {}
        self.journal: list[str] = []

    def context_block(self, *a, **k):
        return self._block

    def slots(self):
        if self.broken:
            raise RuntimeError("记忆库坏了")
        return dict(self.slots_written)

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


def test_kiosk_mode_fits_the_screen_and_does_not_stretch(win):
    """小屏模式：按那块屏的真实尺寸等比铺满（不是写死的 0.55）。

    这条要真建一个窗口来验 —— 缩放算错只会在"上真屏"那一刻暴露，
    而那时候人已经坐在屏前面等着看 Sammy 了。
    """
    import pytest

    from sammy import screen
    from sammy.faces import DEV_H, DEV_W
    from sammy.pet import SammyWindow

    s = screen.list_screens()[0]
    expected = screen.fit(DEV_W, DEV_H, s["width"], s["height"])

    k = SammyWindow(kiosk=True, display=s["index"], autoconnect=False)
    assert k.scale == pytest.approx(expected.scale), "缩放没按屏算"
    assert (k.width(), k.height()) == (expected.width, expected.height)
    # 不拉伸：宽高比必须还是设备坐标系的 5:3
    assert k.width() / k.height() == pytest.approx(DEV_W / DEV_H, rel=1e-2)


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
    """记忆必须真的塞进提示词 —— 否则"记得你"是假的。"""
    brain = FakeBrain()
    win.brain = brain
    win.memory = FakeMemory("【你记得关于 Rowan 的事】\n- preferred_name：Rowan")
    win._call_brain("我叫什么")
    assert brain.calls == [("我叫什么", win.memory._block)]
    assert "Rowan" in brain.calls[0][1]


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
