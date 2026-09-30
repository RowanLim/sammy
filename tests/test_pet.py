"""窗口逻辑 —— 表情切换、空闲行为、对话接线、各条降级路径。

全部离屏跑，大脑和记忆都注入假件，不联网、不碰真实记忆库。
"""

import pytest

from sammy.pet import POKE_FACES, POKE_QUIPS, SammyWindow

pytestmark = pytest.mark.usefixtures("qapp")


class FakeBrain:
    """假大脑：记录被问过什么，返回可预测的结果。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.extracted: list[tuple[str, str]] = []

    def chat(self, text, memory_context=""):
        self.calls.append((text, memory_context))
        if self.fail:
            raise RuntimeError("网络炸了")
        return {"reply": "假的回复", "emotion": "happy", "expression": 4, "latency": 0.12}

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


# ── 空闲行为 ──────────────────────────────────────


def test_idle_progression_to_sleepy(win):
    win.idle_seconds = 119
    win._tick()
    assert win.expression == 27, "无交互 120 秒该犯困"


def test_idle_progression_to_sleep(win):
    win.idle_seconds = 299
    win._tick()
    assert win.expression == 1
    assert win.status == "睡着了"


def test_idle_does_not_advance_while_thinking(win):
    win.thinking = True
    win.idle_seconds = 119
    win._tick()
    assert win.idle_seconds == 119, "思考中不该被当成空闲"


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
