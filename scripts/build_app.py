#!/usr/bin/env python
"""把 Sammy 打成双击即开的 `.app`（PRD P0-4）。

三条硬规矩，每条都对应一个真会出的坑：

1. **绝不把 `.env` 打进包。** 那等于把凭证复制到每一个副本里，
   而且 .app 是只读的，用户永远改不了。打包后的应用从
   `~/Library/Application Support/Sammy/.env` 读配置（见 src/sammy/paths.py）。
2. **表情素材必须 `--add-data` 进去。** 忘了这一步，程序能起、界面是白的 ——
   最容易被忽略的失败方式。
3. **打完真的验一遍**：跑包内二进制的 `--models` 和 `--snapshot`，
   证明二进制能起、资源能读。"dist/Sammy.app 存在"不算验收。

用法:
  .venv/bin/python scripts/build_app.py
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
APP = ROOT / "dist" / "Sammy.app"
BIN = APP / "Contents" / "MacOS" / "Sammy"

# 明确排除：这些是 Qt 的示例/测试/3D 模块，打进去只会让包大几十 MB
EXCLUDES = [
    "tkinter",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtWebEngineCore",
    "PySide6.QtCharts",
    "PySide6.QtMultimedia",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, **kw)


def main() -> int:
    if not (ROOT / ".venv").exists():
        print("❌ 没有 .venv")
        return 1

    print("=== 1/4 确认 PyInstaller 在 ===")
    r = run([str(PY), "-m", "PyInstaller", "--version"], capture_output=True)
    if r.returncode != 0:
        print("装一下：.venv/bin/python -m pip install pyinstaller")
        return 1
    print("PyInstaller", r.stdout.strip())

    print("\n=== 2/4 清理旧产物 ===")
    for p in (ROOT / "build", ROOT / "dist", ROOT / "Sammy.spec"):
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    print("已清理 build/ dist/ Sammy.spec")

    print("\n=== 3/4 打包 ===")
    cmd = [
        str(PY),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # macOS 上生成 .app
        "--name",
        "Sammy",
        "--paths",
        "src",
        "--add-data",
        "assets:assets",  # ← 少了这行，界面会是白的
        "--osx-bundle-identifier",
        "com.rowan.sammy",
        # 别把 .env 打进来（PyiInstaller 只收 import 到的东西和 --add-data，
        # 这里再显式排除一次，防止将来有人手滑）
        "--exclude-module",
        "dotenv",
    ]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    cmd.append("packaging/entry.py")
    r = run(cmd, capture_output=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        return 1
    print("打包完成")

    print("\n=== 4/4 真的验一遍（不是「文件存在就算」）===")
    if not BIN.exists():
        print(f"❌ 找不到可执行文件：{BIN}")
        return 1
    size_mb = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file()) / 1e6
    print(f"包大小 {size_mb:.0f} MB")

    # ① 凭证有没有被打进包 —— 必须没有
    leaked = []
    for f in APP.rglob("*"):
        if f.is_file() and f.name in (".env", ".env.local"):
            leaked.append(str(f.relative_to(APP)))
    if leaked:
        print(f"❌ 包里有配置文件：{leaked} —— 凭证绝不能进安装包")
        return 1
    print("✅ 包内没有 .env")

    # ② 二进制能不能起（用 CLI 子命令，不弹窗）
    r = subprocess.run([str(BIN), "--models"], capture_output=True, text=True, cwd=ROOT)
    out = r.stdout + r.stderr
    # 检查标记要**照实际输出写**，不能凭印象猜 ——
    # 第一版我写的是"档位"，而真实输出是"聊天档/代理档"，于是把好好的二进制判成起不来。
    if r.returncode != 0 or "聊天档" not in out:
        print(f"❌ 包内二进制起不来（退出码 {r.returncode}）：{out[-600:]}")
        return 1
    print("✅ 包内二进制能起（--models 正常）")
    for line in out.strip().splitlines()[:2]:
        print("   " + line)

    # ③ 资源能不能读：渲染一张脸出来（走的是 assets/expressions/*.bmp）
    snap = ROOT / "dist" / "packaged-face.png"
    r = subprocess.run(
        [str(BIN), "--snapshot", str(snap)], capture_output=True, text=True, cwd=ROOT
    )
    if r.returncode != 0 or not snap.exists():
        print(f"❌ 包内资源读不到（脸没渲染出来）：{(r.stdout + r.stderr)[-500:]}")
        return 1
    print(f"✅ 包内资源能读（渲染出 {snap.name}，{snap.stat().st_size} 字节）")

    print("\n" + "=" * 60)
    print(f"完成：{APP}")
    print("双击即开，全程不需要终端。")
    print("首次使用记得配凭证（打包版读的是这个文件）：")
    print("  ~/Library/Application Support/Sammy/.env")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
