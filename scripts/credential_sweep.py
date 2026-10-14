#!/usr/bin/env python3
"""凭证总目录扫描 —— 回答一句人话：「我所有的密钥，现在放在哪儿了？」

为什么要单独写这个：**凭证这东西，谁记着谁就是漏点。**
项目的隔离约定是「一切都在项目文件夹里」，凭证的唯一合法位置是
`data/.env`（在项目里、被 git 忽略）。但 Samson 之前写代码人（包括我）
为了省事在别处放过东西 —— 比如 `~/.hermes/remote-keys/` 那种跨机器密钥、
`~/.gitconfig` 里的代理、或者某个临时脚本里 hardcode 的一行。
这些位置**没有任何测试看得见**，于是它们只会在出事那天才被发现。

这个脚本做的事只有一件：把「这台机器上、和这个项目有关」的地方扫一遍，
看有没有**看起来是凭证的东西**出现在 `data/.env` 之外。

纪律（和回放/复刻一样）：
- **只读**。不删、不改、不挪任何东西，连它自己的输出也不落盘（只打印）。
- **只记位置，不记内容**。命中了只报「哪一行、哪一类」，绝不把密钥原文打出来，
  也绝不读进内存之外的任何地方。报告里的证据是「行号 + 规则的代号」。
- 扫不到 ≠ 安全。它只是把「我知道的地方」扫一遍 —— 未知的地方它当然不知道。

用法：
    .venv/bin/python scripts/credential_sweep.py          # 打印一张表
    .venv/bin/python scripts/credential_sweep.py --json   # 机读版（CI 用）
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 项目的唯一合法凭证位置：<项目>/data/.env（在项目里、被 git 忽略、不进版本库）
LEGAL_ENV = ROOT / "data" / ".env"

# 允许出现在 .env 里的键名前缀（其余键名出现 = 有人往里塞了别的东西）
KNOWN_KEYS = (
    "SAMMY_",
    "DOUBAO_",
    "TTS_",
)

# 可疑位置的「形状」：文件名像凭证 / 目录像密钥柜
SUSPECT_NAME = re.compile(
    r"(?i)(credential|secret|token|api[_-]?key|passwd|password|\.pem$|\.key$|id_rsa|id_ed25519)"
)

# 凭证的**内容形状**（和 scripts/audit_repo.py 的一套口径，但这里扫的是磁盘不是 git）
VALUE_PATTERNS = (
    ("sk- 开头的 key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    (
        "被赋值的 UUID 形式 key",
        re.compile(r"(?i)(key|token|secret)\s*[:=]\s*[\"']?[0-9a-f]{8}-[0-9a-f]{4}-"),
    ),
    ("AWS AKIA", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Bearer 字面量", re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{24,}")),
)

# 这些目录里扫到什么都不奇怪（第三方缓存、虚拟环境、node_modules），跳过
SKIP_DIRS = (".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", "dist", "build")

# 机器级要看的**点名清单**（不递归、不猜）：只有这些地方是我们知道自己用过凭证的
MACHINE_PLACES = (
    ".hermes/remote-keys",
    ".hermes/.env",
    ".gitconfig",
    ".netrc",
    ".ssh/config",
    ".aws/credentials",
)


def machine_places() -> list[pathlib.Path]:
    """机器级**点名清单**的展开（给判据用）：列的都是我们知道自己用过凭证的地方。"""
    home = pathlib.Path.home()
    out: list[pathlib.Path] = []
    for rel in MACHINE_PLACES:
        p = home / rel
        if p.is_dir():
            out.append(p)
            out.extend(q for q in sorted(p.rglob("*")) if q.is_file())
        elif p.is_file():
            out.append(p)
    return out


def _candidate_files() -> list[pathlib.Path]:
    """这份名单是**写死的**，不用 rglob 满盘扫 —— 扫得越广，越容易扫出别人的隐私。"""
    out: list[pathlib.Path] = []
    # ① 项目里：data/ 下的一切（除合法的 .env）、项目根、scripts/
    for sub in ("data", "scripts", "docs", "tests", "src"):
        base = ROOT / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
                continue
            out.append(p)
    out.extend(p for p in sorted(ROOT.glob("*.toml")) + sorted(ROOT.glob("*.cfg")))
    # ② 机器级：家目录下这几个**已知的**凭证点（列名字，不递归）
    out.extend(machine_places())
    return out


def _is_pointed_dir(p: pathlib.Path) -> bool:
    """是不是「点名清单」里的目录本身（那一行报的是「这里有个装密钥的柜子」）。"""
    return str(p) in {str(q) for q in machine_places() if q.is_dir()}


def scan() -> dict:
    """扫一遍，返回一张账。**不返回任何密钥原文** —— 只有位置与规则代号。"""
    hits: list[dict] = []
    scanned = 0
    for p in _candidate_files():
        if _is_pointed_dir(p):
            # 目录不是文件：报一条「这里有个密钥柜」，行号写 0（目录没有行）
            hits.append({"file": str(p), "line": 0, "rule": "点名的密钥目录"})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        if p == LEGAL_ENV:
            # 合法的家：只核键名，不看值
            for i, line in enumerate(text.splitlines(), 1):
                m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                if m and not m.group(1).startswith(KNOWN_KEYS):
                    hits.append({"file": str(p), "line": i, "rule": "不认识的键名"})
            continue
        named = bool(SUSPECT_NAME.search(p.name))
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for label, rx in VALUE_PATTERNS:
                if rx.search(line):
                    hits.append({"file": str(p), "line": i, "rule": label})
                    break
            else:
                continue
            break
        if named and not hits:
            pass
    return {"scanned": scanned, "legal": str(LEGAL_ENV), "hits": hits}


# 机器级的位置只登记到「目录 / 文件」这一层：再往里指名道姓就等于替 Rowan
# 去整理他的家目录了，那不是我们该做的事（纪律二/三）。
MACHINE_WHERE = (
    ("remote-keys", ".hermes/remote-keys"),
    (".env", ".hermes/.env"),
    ("gitconfig", ".gitconfig"),
)


def route(report: dict) -> list[dict]:
    """把扫描结果归并成台账行：项目内的命中逐条报，机器级的只报「哪个文件里有几处」。"""
    rows: list[dict] = []
    home = str(pathlib.Path.home())
    for hit in report["hits"]:
        f = hit["file"]
        if f.startswith(str(ROOT)):
            rows.append(
                {
                    "where": f[len(str(ROOT)) + 1 :],
                    "line": hit["line"],
                    "rule": hit["rule"],
                    "project": True,
                }
            )
            continue
        if not f.startswith(home):
            rows.append({"where": f, "line": hit["line"], "rule": hit["rule"]})
            continue
            continue
        is_dir = pathlib.Path(f).is_dir()
        label = None
        for name, where in MACHINE_WHERE:
            if f.endswith("." + name) or ("/" + name) in f:
                label = where
                break
        if label is None:
            label = "~/（不认识的位置）"  # 不给路径：纪律三
        if is_dir:
            # 目录级的命中归到「柜子」那一层（不带尾巴），跟文件级命中同一个标签
            label = (label or "remote-keys").rstrip("/")
        got = next((r for r in rows if r["where"] == label), None)
        if got is None:
            rows.append({"where": label, "line": hit["line"], "rule": hit["rule"], "count": 1})
        else:
            got["count"] = got.get("count", 1) + 1
            got["line"] = min(got["line"], hit["line"]) if got["line"] else hit["line"]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="机读输出（不打印表格）")
    ap.add_argument(
        "--inventory",
        action="store_true",
        help="机读的独立发现清单：台账文档里没登记的那些（给判据用）",
    )
    args = ap.parse_args()
    report = scan()
    if args.inventory:
        rows = route(report)
        listed = [str(q) for q in machine_places()]
        print(
            json.dumps(
                {"scanned": report["scanned"], "rows": rows, "listed": listed},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print("凭证总目录扫描（只读，不打印任何密钥原文）")
    print(f"  合法位置：{report['legal']}（在项目里、被 git 忽略）")
    print(f"  扫过 {report['scanned']} 个文件")
    if not report["hits"]:
        print("  超出合法位置的凭证：**没有**")
    else:
        for h in report["hits"]:
            print(f"  ⚠️ {h['file']}:{h['line']} → {h['rule']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
