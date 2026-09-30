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
