"""隔离要求 —— 用测试钉住，而不是靠我记得。

Rowan 的原话（2026-10-01）：

> 麻烦做一下隔离 把相关内容都隔离到 mac mini 这个盘里 并新建一个文件夹
> 关于这个项目上的东西 都放在这个文件夹里 不要添加 修改 我机器的任何东西

所以这里检查三件事：
1. 项目所有的运行时路径**都在项目文件夹里**
2. **没有一个**落在 `~/Library`、`~/Backups` 这类机器级目录里
3. 凭证文件**没被 git 跟踪**（在项目里，但绝不进版本库）

这条测试的意义：**约定写在文档里会烂，钉在测试里才会被执行。**
以后再往机器别处写东西，这里立刻会红。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from sammy import attention, care, drives, memory, paths  # noqa: E402

# 机器级目录 —— 这个项目的东西**一个都不该**出现在这里
FORBIDDEN = (
    "Library/Application Support",
    "Library/Preferences",
    "Library/LaunchAgents",
    "/Backups/",
)

ALL_RUNTIME_PATHS = {
    "data_dir": lambda: paths.data_dir(),
    "env_file": lambda: paths.env_file(),
    "记忆库": lambda: memory.DB_FILE,
    "驱力状态": lambda: drives.STATE_FILE,
    "心跳状态": lambda: attention.STATE_FILE,
    "休息计时": lambda: care.STATE_FILE,
}


@pytest.mark.parametrize("label", list(ALL_RUNTIME_PATHS))
def test_every_runtime_path_is_inside_the_project(label):
    """项目的一切都在项目文件夹里 —— 删掉这个文件夹就该彻底干净。"""
    p = ALL_RUNTIME_PATHS[label]()
    root = paths.project_root()
    assert str(p).startswith(str(root)), f"{label} 跑到项目外面去了：{p}"


@pytest.mark.parametrize("label", list(ALL_RUNTIME_PATHS))
def test_nothing_is_written_into_machine_level_dirs(label):
    """不在 ~/Library、~/Backups 这些机器级目录里留任何东西。"""
    p = str(ALL_RUNTIME_PATHS[label]())
    for bad in FORBIDDEN:
        assert bad not in p, f"{label} 又写进机器目录了：{p}"


def test_project_lives_on_the_external_drive():
    """项目在外置盘上（"隔离到 mac mini 这个盘里"）。

    如果哪天你把项目搬到别处，这条会红 —— 那不是它坏了，是**隔离约定变了**，
    请连这个文件和 paths.py 的注释一起更新。
    """
    root = str(paths.project_root())
    assert root.startswith("/Volumes/"), f"项目不在外置盘上了：{root}（隔离约定见本文件头部）"


def test_data_dir_is_gitignored():
    """数据目录（含 .env）必须被 git 忽略 —— 凭证和私人数据不进版本库。"""
    r = subprocess.run(
        ["git", "check-ignore", "-q", str(paths.env_file())],
        cwd=ROOT,
        capture_output=True,
    )
    assert r.returncode == 0, "data/.env 没被 git 忽略 —— 凭证会进版本库"


def test_backups_dir_is_gitignored():
    r = subprocess.run(
        ["git", "check-ignore", "-q", str(ROOT / "backups" / "x")],
        cwd=ROOT,
        capture_output=True,
    )
    assert r.returncode == 0, "backups/ 没被 git 忽略"


def test_sammy_home_override_still_works(monkeypatch, tmp_path):
    """`SAMMY_HOME` 能把数据目录指到别处（临时测试 / 将来树莓派）。

    第一版这条测试是**查文档字符串里有没有提 SAMMY_HOME** —— 那是在验文档，不是验行为。
    口子还在不在，要靠"真能指过去"来证明。
    """
    monkeypatch.setenv("SAMMY_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path
    assert paths.env_file() == tmp_path / ".env"
