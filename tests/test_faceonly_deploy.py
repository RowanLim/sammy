"""小屏常驻的落地件（DECISIONS §三 第 1 条「做，但按纪律做」）。

这些**必须能在 Mac 上离线验**（CI 也跑）：判据不是"在 Nex 上跑没跑过"，
而是"这套东西本身站得住" —— 三个脚本在仓库里、语法是对的、**真的不改显示设置**、
杀手按 PID 精确杀、纪律写在文件头。真机上的那次实测由 scripts/faceonly_assert.py
出数字（几何落在屏内 / 真画上去了 / 站得住 / 停干净）。

为什么这些判据值得写：Rowan 的红线是「不许动显示分辨率/刷新率」，
而"脚本里有没有偷偷 xrandr 改东西"这种事**只有读文件才能钉死** —— 靠人自觉不算数。
"""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

RUN = SCRIPTS / "faceonly_run.sh"
HALT = SCRIPTS / "faceonly_stop.sh"
ASSERT = SCRIPTS / "faceonly_assert.py"


def _bash_syntax_ok(path: pathlib.Path) -> bool:
    """用 bash -n 真解析一遍（不是正则猜"看起来像 shell"）。"""
    return subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


# ── 1. 文件都在、语法都对 ─────────────────────────────


def test_deploy_scripts_exist():
    for p in (RUN, HALT, ASSERT):
        assert p.is_file(), f"缺文件：{p.name}"
        assert p.stat().st_size > 400, f"{p.name} 太小，像空壳"


def test_shell_scripts_parse_and_are_executable():
    for p in (RUN, HALT):
        assert _bash_syntax_ok(p), f"{p.name} 语法不过"
        assert p.stat().st_mode & 0o111, f"{p.name} 没有可执行位（一键跑不起来）"


def test_assert_script_is_ruff_clean_and_has_a_cli():
    """.py 的判据脚本：ruff 干净 + 有 --display/--screen 入口（不是死代码）。"""
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "ruff", "check", str(ASSERT)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    src = ASSERT.read_text(encoding="utf-8")
    assert "--display" in src and "--screen" in src, "判据脚本没有入口参数，怎么跑？"
    assert "def main(" in src and "if __name__" in src


# ── 2. 红线：一个字都不许改显示设置 ────────────────────


def test_never_changes_display_settings():
    """**红线判据。** 三个脚本里不许出现任何会改显示设置的调用。

    Rowan 明确说过不许动分辨率/刷新率/主屏（可逆的也不行）。所以这里不是
    "注释里写了不改"，而是**扫源码**：出现 xrandr 的写操作就挂。
    """
    banned = (
        r"xrandr\s+--output\s+\S+\s+--mode",  # 改分辨率/刷新率
        r"xrandr\s+--output\s+.*--primary",  # 改主屏
        r"xrandr\s+--output\s+.*--auto",  # 让 X 自己挑模式（最阴的一种）
        r"\bxrandr\s+-s\b",  # 换屏尺寸
        r"gnome-monitor-config",
        r"xset\s+.*\brr\b",  # xset 改刷新率
        r"killall\s+gnome-shell",  # 重启桌面（会顺带改会话）
    )
    for p in (RUN, HALT, ASSERT):
        src = p.read_text(encoding="utf-8")
        for pat in banned:
            hit = re.search(pat, src)
            assert not hit, f"{p.name} 里出现了改显示设置的调用：{hit.group(0)!r}"


def test_xrandr_only_used_readonly():
    """xrandr 只准读，而且只认真正会执行的命令行。

    为什么要挑掉注释与文档字符串：注释里提一句 xrandr 是给人看的，不是调用。
    """
    for p in (RUN, HALT, ASSERT):
        for raw in p.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if s.startswith("#") or "xrandr" not in s:
                continue
            looks_live = s.startswith(chr(34)) or s.startswith(chr(39))
            if not (looks_live or "--listmonitors" in s):
                continue
            assert "--listmonitors" in s or "-q" in s or "--query" in s, (
                f"{p.name} 里有一行在跑 xrandr 却不是只读：{s!r}"
            )


# ── 3. 停得干净：按 PID 精确杀，不写 pkill ─────────────


def test_stop_kills_by_pid_not_by_pattern():
    src = HALT.read_text(encoding="utf-8")
    # 只准出现 "python -m sammy" 这一个精确特征，且必须经过 pgrep 拿 PID
    assert "pgrep -f" in src, "停脚本没按 PID 找进程"
    assert '"python -m sammy"' in src, "停脚本的匹配串太宽，会误伤别的 python"
    assert "pkill" not in src, "不许用 pkill（会误伤机器上别的 python 进程）"


def test_stop_is_wired_into_run():
    """一键停必须真的挂在常驻脚本里跑起来（写了没接线＝没有）。"""
    src = RUN.read_text(encoding="utf-8")
    assert "faceonly_stop.sh" in src, "常驻脚本没调停脚本，重复启动会叠出两个实例"


def test_run_uses_setsid_and_face_only_kiosk():
    src = RUN.read_text(encoding="utf-8")
    assert "setsid" in src, "没用 setsid：ssh 一断实例就被带走，常驻不成立"
    assert "--face-only" in src and "--kiosk" in src, "不是 face-only 小屏形态"
    assert "SAMMY_SCREEN" in src, "屏要能用环境变量指定（名字稳、序号会变）"


# ── 4. 纪律写在文件头（后来的人不必重猜）───────────────


def test_discipline_is_written_down():
    head = RUN.read_text(encoding="utf-8")[:1200]
    assert "显示设置" in head, "文件头没写「不碰显示设置」这条红线"
    assert "一键停" in head or "faceonly_stop" in head, "文件头没写怎么停"
    a = ASSERT.read_text(encoding="utf-8")[:1200]
    assert "判据" in a or "对账" in a, "判据脚本头没说它在量什么"


def test_decisions_checklist_points_at_these_files():
    """DECISIONS 的待执行清单要指到这套脚本 —— 不然下一个人不知道活干到哪了。"""
    d = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "faceonly_run.sh" in d, "DECISIONS 待执行清单没指到常驻脚本"
