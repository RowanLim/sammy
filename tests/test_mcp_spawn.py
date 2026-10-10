"""MCP 子进程启动规矩的判据 —— 一份配置，源码与打包都跑得动。

背景（T5 记下的尾巴）：data/mcp.json 里的 command 按惯例写成项目内相对路径
（如 .venv/bin/python）。源码模式启动前会先 cd 到项目根，这个写法天然成立；
打包后的 .app 双击启动时，当前目录是「/」、环境里也没有 PYTHONPATH ——
同一份配置就断在这两个前提上。这组用例把三条规矩钉住：

1. resolve_command：含斜杠的相对路径按项目根解析；绝对路径与裸命令名原样返回；
2. child_env：环境里没有 PYTHONPATH 也要把项目的 src 补上；已有条目保留、
   配置里显式给的键优先；
3. 端到端：当前目录换到别处并清掉 PYTHONPATH，同一份配置照样把子进程拉起来。
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pytest

from sammy import mcp

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fixtures" / "fake_mcp_server.py"
VENV_PY = ROOT / ".venv" / "bin" / "python"


@pytest.fixture
def clients():
    """用例里开的客户端，结束一律送走（进程不许留）。"""
    opened = []
    yield opened
    for c in opened:
        with contextlib.suppress(Exception):
            c.stop()


# ── 规矩一：相对路径按项目根解析 ────────────────────


def test_path_like_relative_resolves_against_project_root():
    assert mcp.resolve_command(".venv/bin/python") == str(ROOT / ".venv" / "bin" / "python")
    assert mcp.resolve_command("tools/some-server") == str(ROOT / "tools" / "some-server")


def test_absolute_and_bare_names_left_alone():
    assert mcp.resolve_command("/usr/bin/python3") == "/usr/bin/python3"
    assert mcp.resolve_command("npx") == "npx"
    assert mcp.resolve_command("python3") == "python3"


def test_tilde_expands_to_home():
    got = mcp.resolve_command("~/bin/tool")
    assert got == os.path.expanduser("~/bin/tool")
    assert not got.startswith("~")


# ── 规矩二：子进程环境默认带上项目 src ──────────────


def test_env_prepends_project_src_when_missing(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    cfg = mcp.ServerConfig(name="x", command="x")
    parts = mcp.child_env(cfg)["PYTHONPATH"].split(os.pathsep)
    assert parts == [str(ROOT / "src")]


def test_env_keeps_existing_entries(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["/a", "/b"]))
    cfg = mcp.ServerConfig(name="x", command="x")
    parts = mcp.child_env(cfg)["PYTHONPATH"].split(os.pathsep)
    assert parts == [str(ROOT / "src"), "/a", "/b"]


def test_env_does_not_duplicate(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    cfg = mcp.ServerConfig(name="x", command="x")
    parts = mcp.child_env(cfg)["PYTHONPATH"].split(os.pathsep)
    assert parts == [str(ROOT / "src")]


def test_config_env_wins(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    cfg = mcp.ServerConfig(name="x", command="x", env={"PYTHONPATH": "/custom", "FOO": "bar"})
    env = mcp.child_env(cfg)
    assert env["PYTHONPATH"] == "/custom"
    assert env["FOO"] == "bar"


# ── 规矩三：启动三件套与端到端 ──────────────────────


def _shim(root: Path) -> Path:
    """在假项目根里放一个假解释器：先记录当前目录与环境，再 exec 真解释器。"""
    d = root / "fakebin"
    d.mkdir(parents=True, exist_ok=True)
    py = d / "py"
    py.write_text(
        "#!/bin/sh\n"
        'printf "%s" "$PWD" > "$SAMMY_SHIM_PWD"\n'
        'printf "%s" "$PYTHONPATH" > "$SAMMY_SHIM_PP"\n'
        f'exec "{sys.executable}" "{FAKE}" "$@"\n',
        encoding="utf-8",
    )
    py.chmod(0o755)
    return py


def test_spawn_spec_defaults(tmp_path, monkeypatch):
    fake_root = tmp_path / "proj"
    fake_root.mkdir()
    monkeypatch.setattr(mcp, "project_root", lambda: fake_root)
    cfg = mcp.ServerConfig(name="x", command="fakebin/py", args=["--a"])
    cmd, env, cwd = mcp.spawn_spec(cfg)
    assert cmd == [str(fake_root / "fakebin" / "py"), "--a"]
    assert cwd == str(fake_root)
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(fake_root / "src")


def test_spawn_spec_respects_explicit_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "project_root", lambda: tmp_path)
    cfg = mcp.ServerConfig(name="x", command="py", cwd="/somewhere")
    _, _, cwd = mcp.spawn_spec(cfg)
    assert cwd == "/somewhere"


def test_relative_command_runs_from_foreign_cwd(tmp_path, monkeypatch, clients):
    """核心场景：当前目录是别处、环境里没有 PYTHONPATH —— 照样通。"""
    fake_root = tmp_path / "proj"
    fake_root.mkdir()
    _shim(fake_root)
    monkeypatch.setattr(mcp, "project_root", lambda: fake_root)
    monkeypatch.chdir(tmp_path)  # 假装当前目录已经是「/」（双击启动的样子）
    monkeypatch.delenv("PYTHONPATH", raising=False)
    pwd_file = tmp_path / "pwd.txt"
    pp_file = tmp_path / "pp.txt"
    monkeypatch.setenv("SAMMY_SHIM_PWD", str(pwd_file))
    monkeypatch.setenv("SAMMY_SHIM_PP", str(pp_file))

    log = tmp_path / "req.jsonl"
    cfg = mcp.ServerConfig(name="fake", command="fakebin/py", args=["--log", str(log)])
    c = mcp.McpClient(cfg, timeout=5, probe_timeout=3)
    clients.append(c)
    c.start()
    assert [t.name for t in c.list_tools()] == ["echo", "fail", "slow", "booms", "big"]
    got_pwd = Path(pwd_file.read_text()).resolve()
    assert got_pwd == fake_root.resolve(), "子进程的工作目录该是项目根"
    got_pp = Path(pp_file.read_text()).resolve()
    assert got_pp == (fake_root / "src").resolve(), "PYTHONPATH 该带上项目 src"


@pytest.mark.skipif(not VENV_PY.exists(), reason="没有 .venv（CI 环境），这条只在源码真机跑")
def test_real_sammy_server_from_foreign_cwd(tmp_path, monkeypatch, clients):
    """同一份配置（相对路径 + 自家 server），换到别处启动也是真能说话。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    cfg = mcp.ServerConfig(
        name="net",
        command=".venv/bin/python",
        args=["-m", "sammy.mcp_server", "--tools", "current_time"],
    )
    c = mcp.McpClient(cfg, timeout=30, probe_timeout=6)
    clients.append(c)
    c.start()
    assert [t.name for t in c.list_tools()] == ["current_time"]
    now = c.call_tool_text("current_time")
    assert "现在是" in now
