#!/bin/bash
# 在 Nex 的小屏（DP-1）上跑 Sammy，并**录一段真实交互**发回来。
#
# 为什么要有这个脚本：Rowan 的小屏物理上看不见（那块屏 EDID 是 0 字节，
# X 只能按通用模式推），所以"投上去了"不能靠嘴说 —— 得录下来给他看。
# 录的时候真的打一句话进去，让它回一句，这样看到的是活的不是静止画面。
#
# 用法（从 Mac 上）:
#   scripts/demo_on_small_screen.sh [:]显示器 [屏名字] [秒数] [要说的话]
#   scripts/demo_on_small_screen.sh :1 DP-1 12 hello
#
# ⚠️ **用屏名字，不要用序号**：实测序号会变 —— 改了模式之后 DP-1 抢走 primary，
#    Qt 报的屏次序就翻过来了，按序号找屏会把窗口开到主屏上。
set -uo pipefail

DISPLAY_NUM="${1:-:1}"
SCREEN_NAME="${2:-DP-1}"   # 名字是稳定的键
SECONDS_TO_REC="${3:-12}"
MESSAGE="${4:-hello}"

cd ~/sammy || exit 1
mkdir -p .tmp
export DISPLAY="$DISPLAY_NUM"

# 屏幕几何（录哪一块取决于小屏在 X 里的位置）
# xrandr --listmonitors 的行长这样：  1: +DP-1 1920/10x1080/10+1920+0  DP-1
GEO=$(xrandr --listmonitors 2>/dev/null | awk -v n="$SCREEN_NAME" 'index($2, n) > 0 {print $3; exit}')
if [[ "$GEO" =~ ^([0-9]+)(/[0-9]+)?x([0-9]+)(/[0-9]+)?\+([0-9]+)\+([0-9]+) ]]; then
    SIZE="${BASH_REMATCH[1]}x${BASH_REMATCH[3]}"
    OFFSET="+${BASH_REMATCH[5]},${BASH_REMATCH[6]}"   # ffmpeg x11grab 用逗号分隔
else
    echo "❌ 解析不了屏 $SCREEN_NAME 的位置（拿到的是 ${GEO:-空}）："
    xrandr --listmonitors
    exit 2
fi
echo "小屏: $SCREEN_NAME 区域 $SIZE$OFFSET"

# 先停掉可能在跑的实例。**按 PID 精确杀**，不要 pkill -f python ——
# 那会误伤别的 python 进程（这边安全闸也不让那么干）。
for p in $(pgrep -f "sammy/run.sh|python -m sammy" 2>/dev/null); do
    kill "$p" 2>/dev/null
done
sleep 2

echo "启动常驻实例（只在这块屏上）…"
setsid nohup ./run.sh --kiosk --display "$SCREEN_NAME" > .tmp/kiosk.log 2>&1 < /dev/null &
sleep 7
echo "进程 pid: $(pgrep -f 'python -m sammy' | head -1)"
if [ -s .tmp/kiosk.log ]; then echo "日志: $(tail -3 .tmp/kiosk.log | tr '\n' ' ')"; fi
echo "窗口位置: $(xdotool search --name Sammy getwindowgeometry %@ 2>/dev/null | grep -E 'Position|Geometry' | tr '\n' ' ')"

echo "录制 ${SECONDS_TO_REC}s…"
ffmpeg -hide_banner -loglevel error -f x11grab -video_size "$SIZE" -framerate 8 \
    -i "${DISPLAY_NUM}.0${OFFSET}" -t "$SECONDS_TO_REC" \
    -c:v libx264 -preset veryfast -crf 30 -pix_fmt yuv420p \
    -y .tmp/demo-smallscreen.mp4 &
FF=$!
sleep 3

# 真打一句话进去 —— 让录像里有"你说它答"，不是静止的脸
W=$(xdotool search --name Sammy 2>/dev/null | head -1)
if [ -n "$W" ]; then
    xdotool windowactivate "$W" 2>/dev/null
    xdotool type --window "$W" --delay 80 "$MESSAGE" 2>/dev/null && echo "已输入: $MESSAGE"
    xdotool key --window "$W" Return 2>/dev/null && echo "已回车"
else
    echo "⚠️ 没找到窗口（可能还没起来）"
fi

wait $FF
sleep 1
# 再来一张静止图（手机上看得更清楚）
ffmpeg -hide_banner -loglevel error -f x11grab -video_size "$SIZE" \
    -i "${DISPLAY_NUM}.0${OFFSET}" -frames:v 1 -y .tmp/demo-still.png
ls -l .tmp/demo-smallscreen.mp4 .tmp/demo-still.png
