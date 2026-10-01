"""set_key.py —— 写入凭证的工具本身也要测。

重点验证三件事：**写对位置**、**不重复写**、**输出里绝不出现 key 内容**。
"""

from __future__ import annotations

import pathlib
import stat
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "set_key.py"
PY = sys.executable


def _fake_key() -> str:
    """运行时拼装 —— 不然暂存区检查会把这份测试文件拦下来（实测拦过）。"""
    return "sk-" + "T" * 32


@pytest.fixture
def env_file(tmp_path):
    """一个和真实 .env 结构一致的临时文件。"""
    p = tmp_path / ".env"
    p.write_text(
        "# 注释行不该被动\n"
        "SAMMY_CHAT_API_KEY=\n"
        "SAMMY_CHAT_BASE_URL=https://api.deepseek.com/v1\n"
        "SAMMY_CHAT_MODEL=deepseek-flash\n"
        "SAMMY_AGENT_API_KEY=\n"
        "SAMMY_AGENT_BASE_URL=https://api.deepseek.com/v1\n"
        "SAMMY_AGENT_MODEL=deepseek-flash\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "key.txt"
    p.write_text(_fake_key() + "\n", encoding="utf-8")
    return p


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def test_writes_both_tiers(env_file, key_file):
    r = run(["--env-file", str(env_file), "--from-file", str(key_file)])
    assert r.returncode == 0, r.stderr
    text = env_file.read_text(encoding="utf-8")
    assert f"SAMMY_CHAT_API_KEY={_fake_key()}" in text
    assert f"SAMMY_AGENT_API_KEY={_fake_key()}" in text
    # 空行被替换，不是追加出一条新的
    assert text.count("SAMMY_CHAT_API_KEY=") == 1
    assert text.count("SAMMY_AGENT_API_KEY=") == 1
    assert "# 注释行不该被动" in text
    assert "SAMMY_CHAT_MODEL=deepseek-flash" in text


def test_sets_600_permissions(env_file, key_file):
    run(["--env-file", str(env_file), "--from-file", str(key_file)])
    mode = env_file.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR, f"权限是 {oct(mode)}，应该是 600"


def test_never_prints_the_key(env_file, key_file):
    """它会被打印到终端 —— 只要有一处漏出 key 就是事故。"""
    r = run(["--env-file", str(env_file), "--from-file", str(key_file)])
    secret = _fake_key()
    for stream in (r.stdout, r.stderr):
        assert secret not in stream
        assert secret[:8] not in stream
        assert secret[-8:] not in stream
    assert str(len(secret)) in r.stdout  # 只报长度


def test_single_tier_untouched_other(env_file, key_file):
    run(["--env-file", str(env_file), "--from-file", str(key_file), "--tier", "CHAT"])
    text = env_file.read_text(encoding="utf-8")
    assert f"SAMMY_CHAT_API_KEY={_fake_key()}" in text
    assert "SAMMY_AGENT_API_KEY=\n" in text, "只写 CHAT 档时不该动 AGENT 档"


def test_appends_when_line_missing(tmp_path, key_file):
    p = tmp_path / ".env"
    p.write_text("SAMMY_CHAT_BASE_URL=https://x/v1\n", encoding="utf-8")
    r = run(["--env-file", str(p), "--from-file", str(key_file), "--tier", "CHAT"])
    assert r.returncode == 0
    assert f"SAMMY_CHAT_API_KEY={_fake_key()}" in p.read_text(encoding="utf-8")


def test_rejects_key_with_whitespace(env_file, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("sk-abc def ghi jkl mno pqr stu vwx yz\n", encoding="utf-8")
    r = run(["--env-file", str(env_file), "--from-file", str(bad)])
    assert r.returncode == 1
    assert "空白" in r.stdout
    assert "SAMMY_CHAT_API_KEY=\n" in env_file.read_text(encoding="utf-8"), "不该写进去"


def test_rejects_empty_key(env_file, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("\n", encoding="utf-8")
    r = run(["--env-file", str(env_file), "--from-file", str(empty)])
    assert r.returncode == 1
    assert "没读到 key" in r.stdout


def test_missing_env_file_is_reported(tmp_path, key_file):
    r = run(["--env-file", str(tmp_path / "nope.env"), "--from-file", str(key_file)])
    assert r.returncode == 1
    assert "找不到" in r.stdout


def test_warns_on_too_short_key(env_file, tmp_path):
    short = tmp_path / "short.txt"
    short.write_text("sk-abc\n", encoding="utf-8")
    r = run(["--env-file", str(env_file), "--from-file", str(short)])
    assert "不像完整的 key" in r.stdout
