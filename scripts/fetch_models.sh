#!/bin/bash
# 下唤醒词 / 语音识别要用的模型（都不是小文件，所以不进仓库）。
#
# 为什么走 ghfast.top：这台机器直连 GitHub 只有 30~40 KB/s（Nex 也一样），
# 走这个代理能到 600~1700 KB/s —— 差 20 倍。PyPI 直连会间歇性 TLS 失败，
# 装包走清华镜像。这些实测数据记在这儿，省得下次重新试一遍。
set -euo pipefail

cd "$(dirname "$0")/.."
PROXY="${PROXY:-https://ghfast.top/}"
GH="https://github.com/k2-fsa/sherpa-onnx/releases/download"
mkdir -p models .tmp

fetch() { # fetch <url> <输出路径>
    local url="$1" out="$2"
    if [ -e "$out" ]; then
        echo "  ✓ 已有 $(basename "$out")"
        return
    fi
    echo "  ↓ $(basename "$out")"
    curl -fL --progress-bar --max-time 900 -o "$out" "$url"
}

echo "唤醒词模型（中文）—— 「嗨萨米」"
fetch "${PROXY}${GH}/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2" .tmp/kws-zh.tar.bz2
tar xjf .tmp/kws-zh.tar.bz2 -C models/

echo "唤醒词模型（英文）—— 「Hi Sammy」"
fetch "${PROXY}${GH}/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2" .tmp/kws-en.tar.bz2
tar xjf .tmp/kws-en.tar.bz2 -C models/

echo "语音识别模型（paraformer 中文小模型，74MB）"
fetch "${PROXY}${GH}/asr-models/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2" .tmp/asr.tar.bz2
tar xjf .tmp/asr.tar.bz2 -C models/

echo "VAD（判断你说完没）"
fetch "${PROXY}${GH}/asr-models/silero_vad.onnx" models/silero_vad.onnx

echo
du -sh models/*
echo "✅ 完成。模型在 models/（已 gitignore）"
