#!/usr/bin/env python
"""把 API key 安全地写进 .env —— 不经过命令行参数、不进任何日志、不回显。

为什么需要这个脚本：
  直接 `export KEY=xxx` 或把 key 写进命令行，它会出现在 shell 历史、进程列表（ps）、
  以及任何捕获命令的地方。这个脚本用 getpass 读取（终端不回显、不落 shell 历史），
  只在内存里握一下，直接写进权限 600 的 .env。

用法:
  python3 scripts/set_key.py                 # 两个档位都写（交互式，粘一次）
  python3 scripts/set_key.py --tier CHAT     # 只写聊天档
  python3 scripts/set_key.py --verify        # 写完立刻打一次真实调用，报延迟
  python3 scripts/set_key.py --from-file K   # 从文件读（给不方便交互的场景）
  python3 scripts/set_key.py --env-file P    # 指定 .env 路径（测试用）
"""

from __future__ import annotations

import argparse
import getpass
import json
import pathlib
import re
import stat
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sammy.paths import env_file

# 配置统一放在 ~/Library/Application Support/Sammy/.env（见 src/sammy/paths.py）——
# 开发版和双击版读同一份，凭证也不住在代码仓库里。
DEFAULT_ENV = env_file()


def read_key(args) -> str:
    if args.from_file:
        return pathlib.Path(args.from_file).read_text(encoding="utf-8").strip()
    if not sys.stdin.isatty():
        # 管道进来（比如 echo xxx | set_key.py）—— 这也算一种不回显的方式
        return sys.stdin.read().strip()
    print("粘贴 API key，然后回车（不会回显，也不会进 shell 历史）：")
    return getpass.getpass("key: ").strip()


def upsert(text: str, key: str, value: str) -> tuple[str, bool]:
    """改写/追加 `key=value`。返回 (新文本, 是否改动)。"""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}={value}", text), True
    return text.rstrip("\n") + f"\n{key}={value}\n", True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["CHAT", "AGENT", "BOTH"], default="BOTH")
    ap.add_argument("--from-file", metavar="PATH", help="从文件读 key（读一行）")
    ap.add_argument("--env-file", default=str(DEFAULT_ENV))
    ap.add_argument("--verify", action="store_true", help="写完立刻打一次真实调用")
    args = ap.parse_args()

    env_path = pathlib.Path(args.env_file)
    if not env_path.exists():
        print(f"❌ 找不到 {env_path}（先复制一份：cp .env.example .env）")
        return 1

    key = read_key(args)
    if not key:
        print("❌ 没读到 key")
        return 1
    if len(key) < 16:
        print(f"⚠️  key 只有 {len(key)} 个字符，看着不像完整的 key —— 继续写入，但你确认一下")
    if re.search(r"\s", key):
        print("❌ key 里带了空白字符，多半是复制时多选了 —— 重来一次")
        return 1

    tiers = ["CHAT", "AGENT"] if args.tier == "BOTH" else [args.tier]
    text = env_path.read_text(encoding="utf-8")
    for tier in tiers:
        text, _ = upsert(text, f"SAMMY_{tier}_API_KEY", key)

    env_path.write_text(text, encoding="utf-8")
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600：只有你能读
    except OSError as e:
        # 不能静默吞掉：chmod 失败意味着这个文件可能有别人可读的权限
        print(f"⚠️  改权限失败（{e}）—— 请检查 {env_path} 的权限，别让它被人读到")

    # 只报长度，不报内容
    print(f"✅ 已写入 {env_path}（{', '.join(tiers)} 档，长度 {len(key)}，权限 600）")
    print("   想确认状态：./run.sh --models")

    if args.verify:
        return _verify(env_path)
    return 0


def _verify(env_path: pathlib.Path) -> int:
    """拿刚写进去的配置打一次真实调用 —— 立刻知道 key 和型号名对不对。"""
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    api_key = env.get("SAMMY_CHAT_API_KEY") or env.get("DOUBAO_API_KEY", "")
    base = (env.get("SAMMY_CHAT_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").rstrip(
        "/"
    )
    model = env.get("SAMMY_CHAT_MODEL") or "doubao-seed-2-0-lite-260215"

    print(f"\n验证：{base}  模型 {model}")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回两个字：在的"}],
        "temperature": 0.1,
        # ⚠️ 别给太小。会思考的模型会先把预算花在 reasoning 上，
        # max_tokens=20 时它"想"完就没了，content 直接是空的 —— 而我第一版居然
        # 把这判成"✅ 通了"。**报了通过却没有输出，就是假验收。**
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        print(f"❌ HTTP {e.code} —— {detail}")
        if e.code == 400 and "model" in detail.lower():
            print("   多半是型号名不对。DeepSeek 官方公开的是 deepseek-chat / deepseek-reasoner，")
            print("   把 .env 里的 SAMMY_CHAT_MODEL 改成其中一个再试。")
        elif e.code == 401:
            print("   多半是 key 不对或已失效。")
        return 1
    except Exception as e:
        print(f"❌ 连不上：{type(e).__name__}: {e}")
        return 1

    elapsed = time.time() - started
    reply = (body["choices"][0]["message"].get("content") or "").strip()
    usage = body.get("usage", {})
    if not reply:
        # 曾经在这里报过"✅ 通了"而回复是空的 —— 这不算通过。
        print("❌ 连上了，但**回复是空的** —— 这不算通过。")
        print(f"   用量：{usage}")
        print("   若 token 几乎全在 reasoning_tokens 上，说明这是个会思考的模型：")
        print("   把 max_tokens 调大（本脚本已设 400），或换一个非推理型号。")
        return 1
    print(f"✅ 通了　延迟 {elapsed:.2f}s　回复：{reply[:40]}")
    print(f"   用量：{usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
