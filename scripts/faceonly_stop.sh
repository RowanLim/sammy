#!/bin/bash
# 停掉小屏常驻的 face-only 实例 —— 一键，停干净。
#
# 精确杀（按进程号）而不是按名字匹配：匹配会误伤机器上别的同解释器进程。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0
found=0
for p in $(pgrep -f "python -m sammy" 2>/dev/null); do
    echo "  stopping $p"
    /bin/kill "$p" 2>/dev/null
    found=1
done
sleep 2
[ "$found" -eq 1 ] && echo "已停干净（小屏回到桌面）" || echo "本来就没在跑"
