#!/bin/bash
# 停掉在跑的 Sammy 实例。
#
# **按 PID 精确杀**，不要写 `pkill -f python`：那会误伤机器上其它 python 进程
# （外面那层安全闸也明确不让那么干）。宁可多两行，也不要误杀别人的东西。
set -uo pipefail
found=0
for p in $(pgrep -f "python -m sammy" 2>/dev/null); do
    echo "  kill $p"
    kill "$p" 2>/dev/null
    found=1
done
sleep 1
if pgrep -f "python -m sammy" > /dev/null 2>&1; then
    echo "⚠️ 还有残留进程"
    exit 1
fi
[ "$found" -eq 1 ] && echo "已停干净" || echo "本来就没在跑"
