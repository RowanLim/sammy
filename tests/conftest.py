"""测试公共装置。

faces 用到 QPixmap，必须有 QGuiApplication；测试一律离屏跑，不弹窗。
"""

import os
import pathlib
import sys

# 必须在 import PySide6 之前设好
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(scope="session")
def qapp():
    """整个测试会话共用一个 QApplication。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolate_chatlog(tmp_path, monkeypatch):
    """**每个用例都别碰真的对话记录。**

    踩过的坑：窗口层的 `send()` / `_on_reply()` 会往 `data/chat.jsonl` 追加，
    于是一跑测试就把**测试夹具**（"假的回复"这种）写进真实的流水里 ——
    用户 `make history` 会看到一堆测试数据，那是数据污染，不是小事。
    隔离要放在**根上**（autouse），而不是指望每个用例自觉。
    """
    from sammy import chatlog
    from sammy import mood as mood_mod
    from sammy import recall as recall_mod

    monkeypatch.setattr(chatlog, "LOG_FILE", tmp_path / "chat.jsonl")
    monkeypatch.setattr(chatlog, "ROTATED", tmp_path / "chat.jsonl.1")
    # 心情也一样：窗口会自己写 data/mood.json，别让测试把真实心情改掉
    monkeypatch.setattr(mood_mod, "STATE_FILE", tmp_path / "mood.json")
    # 回忆状态同理：窗口会写 data/recall.json
    monkeypatch.setattr(recall_mod, "STATE_FILE", tmp_path / "recall.json")


@pytest.fixture(autouse=True)
def _default_crt_off(monkeypatch):
    """所有测试默认关掉 CRT 质感层（SAMMY_CRT=off）。

    为什么：其余判据量的是**内容本身**（脸的位置、文字像素）——扫描线会把
    每两行压暗一行，像素计数类断言的口径就变了。这层装饰在 test_crt.py 里
    单独开、关两条路全量验；生产默认是**开**（crt_enabled 默认 on）。
    """
    monkeypatch.setenv("SAMMY_CRT", "off")


@pytest.fixture
def memory(tmp_path):
    """每个用例一个干净的记忆库。"""
    from sammy.memory import Memory

    mem = Memory(tmp_path / "test.db")
    yield mem
    mem.close()


@pytest.fixture
def has_key():
    """有凭证时才跑联网用例。"""
    from sammy.brain import _load_env

    return bool(_load_env().get("DOUBAO_API_KEY"))
