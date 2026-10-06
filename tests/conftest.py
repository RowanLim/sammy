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

    monkeypatch.setattr(chatlog, "LOG_FILE", tmp_path / "chat.jsonl")
    monkeypatch.setattr(chatlog, "ROTATED", tmp_path / "chat.jsonl.1")


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
