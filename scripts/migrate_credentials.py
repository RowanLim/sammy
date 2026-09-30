#!/usr/bin/env python3
"""把旧项目里硬编码的凭证搬进 .env，任何时候不打印凭证本身。"""
import re, pathlib, sys

OLD = pathlib.Path("/Volumes/Mac mini/Sammy")
NEW = pathlib.Path("/Volumes/Mac mini/Max agent/Sammy")

found = {}
pat = re.compile(r'["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']')
for f in OLD.rglob("*.py"):
    if "node_modules" in str(f) or "myenv" in str(f):
        continue
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for m in pat.finditer(txt):
        found.setdefault(m.group(1), []).append(str(f.relative_to(OLD)))

print("从旧代码里找到的凭证:")
for k, files in found.items():
    print(f"  {k[:8]}…{k[-4:]}  (len={len(k)})  出现在 {len(files)} 个文件: {files}")

if len(found) == 1:
    key = next(iter(found))
    env = NEW / ".env"
    body = (
        "# Sammy 凭证 —— 永不进 git（.gitignore 已覆盖）\n"
        "# 来源：旧项目硬编码，已迁移，旧文件保持不动\n\n"
        f"DOUBAO_API_KEY={key}\n"
        "DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3\n"
        "DOUBAO_MODEL=doubao-seed-2-0-lite-260215\n"
    )
    env.write_text(body, encoding="utf-8")
    env.chmod(0o600)
    print(f"\n✅ 已写入 {env}  (权限 600)")
else:
    print(f"\n⚠️ 找到 {len(found)} 个不同的凭证，不自动写入，需要人工确认")
    sys.exit(1)

# 确认 .env 被 git 忽略
import subprocess
r = subprocess.run(["git", "check-ignore", "-v", ".env"], cwd=NEW, capture_output=True, text=True)
print("git 忽略检查:", r.stdout.strip() or "❌ 未被忽略！")
