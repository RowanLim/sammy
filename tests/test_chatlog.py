"""对话记录：可查、可清空，**且清空不能连带删掉记忆**。

为什么值得测：这是"用户要能擦掉聊天记录"的功能。
最容易犯的错是**把记忆一起擦了** —— 那等于把 Sammy 变成陌生人，
而用户以为只是清了聊天框。所以"只动流水"这条要有硬判据。
另外：记录文件是长期追加的，坏行、写不进去都不该让"查看"或"聊天"整个坏掉。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import chatlog


@pytest.fixture
def log(tmp_path, monkeypatch):
    """把记录文件指到临时目录 —— 别把测试数据写进真的 data/。"""
    f = tmp_path / "chat.jsonl"
    monkeypatch.setattr(chatlog, "LOG_FILE", f)
    monkeypatch.setattr(chatlog, "ROTATED", tmp_path / "chat.jsonl.1")
    return f


def test_append_then_read_back(log):
    chatlog.append("user", "在干嘛呢")
    chatlog.append("assistant", "数图标呢")
    items = chatlog.recent()
    assert [i["text"] for i in items] == ["在干嘛呢", "数图标呢"]
    assert [i["role"] for i in items] == ["user", "assistant"]
    assert chatlog.count() == 2


def test_recent_returns_oldest_first_and_respects_n(log):
    for i in range(5):
        chatlog.append("user", f"第{i}句")
    assert [i["text"] for i in chatlog.recent(2)] == ["第3句", "第4句"]
    assert chatlog.recent(0) == []


def test_proactive_lines_are_marked(log):
    chatlog.append("assistant", "你该起来走走了", kind="proactive")
    assert chatlog.recent()[0]["kind"] == "proactive"
    assert "（主动）" in chatlog.format_recent()


def test_clear_only_removes_the_chat_log(log, tmp_path):
    """**清空对话记录不能动记忆。** 记忆在 sammy.db 里，那是它记住的事。"""
    memory_file = tmp_path / "sammy.db"
    memory_file.write_text("我是一个很贵的数据库", encoding="utf-8")
    chatlog.append("user", "第一句")
    chatlog.append("assistant", "第二句")

    n = chatlog.clear()

    assert n == 2, "要报告删了几条"
    assert chatlog.count() == 0
    assert chatlog.recent() == []
    assert memory_file.exists(), "记忆被连带删掉了 —— 这是最不能犯的错"
    assert memory_file.read_text(encoding="utf-8") == "我是一个很贵的数据库"


def test_clear_on_empty_log_is_fine(log):
    assert chatlog.clear() == 0


def test_a_corrupt_line_does_not_break_reading(log):
    """记录坏了一行不该让"查看"整个失败（追加写的文件一定会遇到半行）。"""
    chatlog.append("user", "好的这句是完整的")
    with log.open("a", encoding="utf-8") as f:
        f.write("{这不是 JSON\n")
        f.write('{"t": 1, "role": "user"}\n')  # 没有 text 的空壳
    items = chatlog.recent()
    assert [i["text"] for i in items] == ["好的这句是完整的"]


def test_empty_text_is_not_logged(log):
    chatlog.append("user", "")
    chatlog.append("user", None)
    assert chatlog.count() == 0


def test_write_failure_does_not_raise(monkeypatch, capsys):
    """写不进去只打一行日志 —— 记不下来不该害得聊不了天。"""
    monkeypatch.setattr(chatlog, "LOG_FILE", pathlib.Path("/不会存在/chat.jsonl"))
    chatlog.append("user", "这句话写不进去")
    assert "对话记录写不进去" in capsys.readouterr().out


def test_rotation_keeps_old_lines_readable(log, monkeypatch):
    """超过上限就把旧记录轮换成 .1 —— 轮换后**两条记录都要能读到**。"""
    monkeypatch.setattr(chatlog, "MAX_BYTES", 10)
    chatlog.append("user", "很久以前那句")
    chatlog.append("user", "刚刚那句")
    texts = [i["text"] for i in chatlog.recent()]
    assert "刚刚那句" in texts, "新记录丢了"
    assert texts == ["很久以前那句", "刚刚那句"] or "很久以前那句" in texts


def test_format_says_how_many(log):
    chatlog.append("user", "喂")
    out = chatlog.format_recent()
    assert "你：" in out and "共 1 条" in out


def test_format_when_empty(log):
    assert "还没有对话记录" in chatlog.format_recent()


def test_records_are_jsonl_lines(log):
    """格式必须是"一行一条 JSON" —— 追加写才不会互相踩。"""
    chatlog.append("user", "第一句")
    chatlog.append("assistant", "第二句")
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert json.loads(line)["text"]
