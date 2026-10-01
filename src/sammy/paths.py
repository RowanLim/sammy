"""全项目的路径解析 —— 一套代码同时服务「源码运行」和「打包后的 .app」。

为什么单独开一个文件：
打包后最容易炸的就是路径，而且**炸得很安静** —— 资源读不到只是脸变白的，
配置读不到只是"没凭证"。等你发现时已经在查别的东西了。
所以：**路径只在这一个文件里算，别处不许自己拼。**

两条硬规矩：
1. 数据（记忆库 / 状态 / 配置）一律在 `~/Library/Application Support/Sammy/` ——
   内置盘。拔掉外置盘 Sammy 不能失忆，打包后的 .app 也不能往只读的包里写。
2. 只读资源（表情图）打包后在 `sys._MEIPASS`，源码运行时在仓库根。
"""

from __future__ import annotations

import pathlib
import sys

# 用户数据目录：记忆库、驱力状态、配置都在这儿
APP_SUPPORT = pathlib.Path.home() / "Library" / "Application Support" / "Sammy"


def is_frozen() -> bool:
    """是不是跑在 PyInstaller 打出来的包里。"""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundled_dir() -> pathlib.Path:
    """只读资源（assets）的根目录。"""
    if is_frozen():
        return pathlib.Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return pathlib.Path(__file__).resolve().parent.parent.parent


def assets_dir() -> pathlib.Path:
    """表情图目录。"""
    return bundled_dir() / "assets" / "expressions"


def env_file() -> pathlib.Path:
    """配置文件位置 —— 统一放 `Application Support`，**不放项目目录**。

    为什么统一：
    - 凭证不该住在代码仓库里（少一个被误提交、被同步、被截图的地方）
    - 开发版和双击版读**同一份**配置，才不会有"命令行好用、双击版说没凭证"这种鬼故事

    过渡期兜底：App Support 里还没有、而仓库里还留着老的 `.env`，就先用它 ——
    `--models` 会打印实际用的是哪一份，不靠猜。**不把人卡住，但也不永远两套。**
    """
    app_env = APP_SUPPORT / ".env"
    if is_frozen() or app_env.exists():
        return app_env
    legacy = bundled_dir() / ".env"
    return legacy if legacy.exists() else app_env


def ensure_app_support() -> pathlib.Path:
    """确保数据目录存在并返回它。"""
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    return APP_SUPPORT


__all__ = [
    "APP_SUPPORT",
    "assets_dir",
    "bundled_dir",
    "ensure_app_support",
    "env_file",
    "is_frozen",
]
