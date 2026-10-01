"""全项目的路径解析 —— 一套代码同时服务「源码运行」和「打包后的 .app」。

**隔离原则（Rowan 定，2026-10-01）**：
这个项目的一切 —— 代码、数据、配置、备份 —— 都在**项目文件夹里**，
即外置盘 `/Volumes/Mac mini/Max agent/Sammy/` 下。
不在他机器上别处留任何东西。

为什么数据也放项目里（而不是 `~/Library`）：
- 干净的隔离：删掉这个文件夹 = 这个项目在你机器上彻底消失
- 代价：**盘拔了 Sammy 就没记忆、没配置**。但盘拔了 `.app` 本身也不在，
  所以"应用和数据同生共死"反而是一致的。这个取舍是 Rowan 拍的。

两条硬规矩：
1. 数据（记忆库 / 状态 / 配置）→ `<项目>/data/`，**已被 git 忽略**
   （私人数据不该进版本库，凭证更不该）
2. 只读资源（表情图）打包后在 `sys._MEIPASS`，源码运行时在项目根

⚠️ 唯一例外的应急口子：环境变量 `SAMMY_HOME` 可以把数据目录指到别处
（临时测试、或将来到树莓派上数据放 `/home/pi`）。默认永远走项目内。
"""

from __future__ import annotations

import os
import pathlib
import sys

# 项目内的数据目录名
DATA_DIR_NAME = "data"


def is_frozen() -> bool:
    """是不是跑在 PyInstaller 打出来的包里。"""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def project_root() -> pathlib.Path:
    """项目根目录 —— 无论源码运行还是打包后，都指向**同一个**文件夹。

    打包后 `.app` 躺在 `<项目>/dist/Sammy.app`，所以从可执行文件往上找几层就能
    摸到项目根（用 `src/sammy` 是否存在来确认找对了）。万一往上找不到
    （比如你把 .app 拷到别处去了），就退到 .app 自己所在目录 ——
    宁可数据跟着应用走，也不要凭空在你系统目录里造一个。
    """
    if is_frozen():
        exe = pathlib.Path(sys.executable).resolve()
        for up in range(2, 6):
            if len(exe.parents) > up:
                cand = exe.parents[up]
                if (cand / "src" / "sammy").is_dir():
                    return cand
        return exe.parent
    return pathlib.Path(__file__).resolve().parent.parent.parent


def data_dir() -> pathlib.Path:
    """运行时数据目录：记忆库、状态、配置都在这里。默认 `<项目>/data/`。"""
    override = os.environ.get("SAMMY_HOME", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return project_root() / DATA_DIR_NAME


def bundled_dir() -> pathlib.Path:
    """只读资源（assets）的根目录。"""
    if is_frozen():
        return pathlib.Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return project_root()


def assets_dir() -> pathlib.Path:
    """表情图目录。"""
    return bundled_dir() / "assets" / "expressions"


def env_file() -> pathlib.Path:
    """配置文件：`<项目>/data/.env`。

    两点要注意：
    - 它在**项目文件夹里**（Rowan 要求一切都在项目里）
    - 但它在 `data/` 里，而 `data/` 被 git 忽略 —— **凭证不会进版本库**，
      更不会被打进 `.app`（构建脚本会检查并拒绝）
    """
    return data_dir() / ".env"


def ensure_data_dir() -> pathlib.Path:
    """确保数据目录存在并返回它。"""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# 兼容旧名字（早期代码与文档里叫 APP_SUPPORT）
APP_SUPPORT = data_dir()

__all__ = [
    "APP_SUPPORT",
    "DATA_DIR_NAME",
    "assets_dir",
    "bundled_dir",
    "data_dir",
    "ensure_data_dir",
    "env_file",
    "is_frozen",
    "project_root",
]
