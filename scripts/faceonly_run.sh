#!/bin/bash
# 小屏常驻（face-only 形态）—— 在 Linux 那台（Nex）上跑，**用户会话里**，不碰任何显示设置。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

DISPLAY_NUM="${DISPLAY:-:1}"
SCREEN="${SAMMY_SCREEN:-HDMI-0}"
MODE="setsid"

for a in "$@"; do
    case "$a" in
        --foreground) MODE="fg" ;;
        *) echo "未知参数: $a"; exit 2 ;;
    esac
done

export DISPLAY="$DISPLAY_NUM"
if [ -S "/run/user/$(id -u)/bus" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi

mkdir -p .tmp
if [ -x scripts/faceonly_stop.sh ]; then scripts/faceonly_stop.sh; fi

echo "小屏常驻：$DISPLAY_NUM 上那块 [$SCREEN]（face-only 形态）"
echo "  停它：scripts/faceonly_stop.sh"
echo "  显示设置：一个字都不动（只读几何）"

if [ "$MODE" = "fg" ]; then
    exec ./run.sh --face-only --kiosk --display "$SCREEN"
fi

setsid nohup ./run.sh --face-only --kiosk --display "$SCREEN" > .tmp/faceonly.log 2>&1 < /dev/null &
sleep 7
pid="$(pgrep -f "python -m sammy" | head -1)"
if [ -n "$pid" ]; then
    echo "  已常驻，pid $pid（日志 .tmp/faceonly.log）"
else
    echo "  ❌ 没起来，看 .tmp/faceonly.log"
    exit 1
fi
