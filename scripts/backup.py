#!/usr/bin/env python
"""Sammy 项目备份 —— 落到内置盘（不能和源在同一块盘）。

产出 ~/Backups/Sammy/<日期>/
  ├── Sammy.bundle          新仓库完整 git 历史（单文件，可 clone 恢复）
  ├── old-Sammy-code.tar.gz  旧项目源码与文档（排除 venv/node_modules/缓存）
  └── MANIFEST.md            大小 + sha256 + 恢复方法

并且**真的验证一遍**：从 bundle 克隆到临时目录，比对提交号与文件数。

用法: python3 scripts/backup.py [--keep N]
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime

PROJECT = pathlib.Path("/Volumes/Mac mini/Max agent/Sammy")
OLD_PROJECT = pathlib.Path("/Volumes/Mac mini/Sammy")
APP_DB = pathlib.Path.home() / "Library" / "Application Support" / "Sammy" / "sammy.db"
DEST_ROOT = pathlib.Path.home() / "Backups" / "Sammy"

EXCLUDE_DIRS = {"myenv", "node_modules", "__pycache__", ".venv", ".git"}
EXCLUDE_NAMES = {".DS_Store", ".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems"}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def sha256(path: pathlib.Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def tar_filter(info: tarfile.TarInfo):
    parts = pathlib.Path(info.name).parts
    if any(p in EXCLUDE_DIRS or p in EXCLUDE_NAMES for p in parts):
        return None
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=7, help="保留最近几份快照")
    ap.add_argument("--refresh-old", action="store_true",
                    help="重新打包旧项目静态档（默认只在不存在时打一次）")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = DEST_ROOT / stamp
    dest.mkdir(parents=True, exist_ok=True)

    if not PROJECT.exists():
        print(f"❌ 项目目录不存在（外置盘没挂载？）: {PROJECT}")
        return 1

    print(f"备份目标: {dest}\n")

    # ── 1. 新仓库：git bundle（完整历史） ──
    head = run(["git", "rev-parse", "HEAD"], cwd=PROJECT).stdout.strip()
    files = run(["git", "ls-files"], cwd=PROJECT).stdout.strip().splitlines()
    bundle = dest / "Sammy.bundle"
    r = run(["git", "bundle", "create", str(bundle), "--all"], cwd=PROJECT)
    if r.returncode != 0:
        print("❌ git bundle 失败:", r.stderr[:400])
        return 1
    print(f"✅ git bundle          {human(bundle.stat().st_size)}   HEAD={head[:7]}  {len(files)} 个文件")

    # ── 2. 旧项目：只存一份静态档（它是只读参考，不会变） ──
    static_dir = DEST_ROOT / "_static"
    static_dir.mkdir(parents=True, exist_ok=True)
    oldtar = static_dir / "old-Sammy-code.tar.gz"
    n_old = 0
    if OLD_PROJECT.exists() and (not oldtar.exists() or args.refresh_old):
        with tarfile.open(oldtar, "w:gz") as tf:
            for child in sorted(OLD_PROJECT.iterdir()):
                if child.name in EXCLUDE_DIRS or child.name in EXCLUDE_NAMES:
                    continue
                tf.add(child, arcname=child.name, filter=tar_filter)
                n_old += 1
        print(f"✅ 旧项目静态档已更新   {human(oldtar.stat().st_size)}   {n_old} 个顶层条目")
    elif oldtar.exists():
        print(f"✅ 旧项目静态档已存在   {human(oldtar.stat().st_size)}   （只读参考，不重复打包）")

    # ── 2b. 记忆库（Sammy 的"人生"，丢了不可再生）──
    # 用 SQLite 官方 backup API 取一致性快照 —— 直接拷文件在写入时会拷到半个事务
    mem_copy = None
    if APP_DB.exists():
        import sqlite3

        mem_copy = dest / "sammy-memory.db"
        try:
            src = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
            dst = sqlite3.connect(str(mem_copy))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            n_slots = sqlite3.connect(f"file:{mem_copy}?mode=ro", uri=True).execute(
                "SELECT COUNT(*) FROM slots"
            ).fetchone()[0]
            print(f"✅ 记忆库快照          {human(mem_copy.stat().st_size)}   {n_slots} 条槽位")
        except Exception as e:
            print(f"⚠️  记忆库备份失败（不阻断其他备份）: {e}")
            mem_copy = None
    else:
        print("（还没有记忆库，跳过）")

    # ── 3. 校验和 + 清单 ──
    arts = [p for p in (bundle, oldtar, mem_copy) if p and p.exists()]
    digests = {p.name: sha256(p) for p in arts}
    for name, d in digests.items():
        print(f"   sha256 {name:<24} {d[:16]}…")

    # ── 4. 真验证：从 bundle 克隆出来对账 ──
    print("\n验证（从 bundle 真克隆一次）…")
    tmp = pathlib.Path("/tmp") / f"sammy_verify_{datetime.now():%H%M%S}"
    if tmp.exists():
        shutil.rmtree(tmp)
    r = run(["git", "clone", "--quiet", str(bundle), str(tmp)])
    ok = r.returncode == 0
    if ok:
        c_head = run(["git", "rev-parse", "HEAD"], cwd=tmp).stdout.strip()
        c_files = run(["git", "ls-files"], cwd=tmp).stdout.strip().splitlines()
        ok = c_head == head and len(c_files) == len(files)
        print(f"   克隆 HEAD={c_head[:7]}  文件数={len(c_files)}  →  "
              f"{'✅ 与源一致' if ok else '❌ 与源不一致'}")
    else:
        print("   ❌ 克隆失败:", r.stderr[:300])
    shutil.rmtree(tmp, ignore_errors=True)

    # ── 5. 清单文件 ──
    old_desc = f"{human(oldtar.stat().st_size)}（{n_old} 个顶层条目）" if oldtar.exists() else "未生成"
    mem_row = (f"| `sammy-memory.db` | {human(mem_copy.stat().st_size)} | "
               f"Sammy 的记忆（槽位 + 日记 + 摘要），SQLite 一致性快照 |"
               if mem_copy and mem_copy.exists() else "| — | — | 本次没有记忆库 |")
    (dest / "MANIFEST.md").write_text(f"""# Sammy 备份 · {stamp}

自动生成，请勿手改。

## 内容

| 文件 | 大小 | 说明 |
|:---|:---|:---|
| `Sammy.bundle` | {human(bundle.stat().st_size)} | 新仓库完整 git 历史，{len(files)} 个文件，HEAD `{head[:7]}` |
| `old-Sammy-code.tar.gz` | {old_desc} | 旧项目 `/Volumes/Mac mini/Sammy` 的源码与文档（在 `_static/` 下，只存一份） |
{mem_row}

## 校验和

```
""" + "".join(f"{d}  {n}\n" for n, d in digests.items()) + f"""```

## 怎么恢复

```bash
# 恢复新仓库（完整历史）
git clone ~/Backups/Sammy/{stamp}/Sammy.bundle Sammy-restored

# 恢复旧项目
mkdir -p /tmp/old-sammy && tar -xzf ~/Backups/Sammy/{stamp}/old-Sammy-code.tar.gz -C /tmp/old-sammy
```

## 注意

- 备份在**内置盘** `~/Backups/Sammy/`，与源（外置盘）不同盘，拔盘不影响。
- 恢复后需要重建环境：`uv venv --python 3.11 .venv && uv pip install -r requirements.txt`
- `.env`（API 凭证）**不在备份里**（已 gitignore），恢复后需重新配置。
- 校验：`cd <克隆出来的目录> && git log --oneline | head`
""", encoding="utf-8")
    print(f"\n✅ 清单已写 {dest / 'MANIFEST.md'}")

    # ── 6. 清理旧备份 ──
    snaps = sorted([d for d in DEST_ROOT.iterdir() if d.is_dir()])
    for old in snaps[:-args.keep] if len(snaps) > args.keep else []:
        shutil.rmtree(old)
        print(f"   清理旧备份 {old.name}")

    total = sum(p.stat().st_size for p in arts)
    print(f"\n{'✅ 备份完成' if ok else '⚠️ 备份完成但验证未通过'} —— {human(total)} → {dest}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
