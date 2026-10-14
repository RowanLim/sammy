#!/bin/bash
# 验证 faceonly_stop.sh 真的停干净了（把检查放这里，脚本本体只管杀）。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0
sleep 2
if pgrep -f "python -m sammy" > /dev/null 2>&1; then
    echo "还有残留，补一次"
    for p in $(pgrep -f "python -m sammy" 2>/dev/null); do kill -9 "$p" 2>/dev/null; done
    sleep 1
fi
if pgrep -f "python -m sammy" > /dev/null 2>&1; then
    echo "没停干净"; exit 1
fi
echo "小屏实例已全部退出"
