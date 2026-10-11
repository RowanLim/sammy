#!/usr/bin/env bash
# 取「缝合像素字体」（Fusion Pixel Font，OFL-1.1）→ 子集化 → assets/fonts/
#
# 为什么要子集：完整 CJK 版解出来约 48MB，随仓库分发太重（打包进 .app 也要背这个体积）。
# GB2312 全字集 + ASCII + 中文标点覆盖日常中文 99.9% 以上，子集后约 1~2MB；
# 缺字仍会**回落到系统字体**，不会变方块。
#
# 许可证：**SIL OFL-1.1** —— 可以随项目分发，但必须带上许可证原文与出处
# （本脚本会把许可证与 README 一起写进 assets/fonts/，别删）。
#
# 为什么走 ghfast.top：直连 GitHub 实测只有 30~40KB/s，48MB 要十几分钟。
#
# 用法: bash scripts/fetch_pixel_font.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
VER="${SAMMY_PIXEL_FONT_VER:-2026.09.25}"
ZIP="fusion-pixel-font-12px-proportional-ttf-v${VER}.zip"
URL="https://github.com/TakWolf/fusion-pixel-font/releases/download/${VER}/${ZIP}"
MIRROR="${SAMMY_GH_MIRROR:-https://ghfast.top}"
DEST="${ROOT}/assets/fonts"
WORK="${ROOT}/.tmp/font-build"
OUT="${DEST}/sammy-pixel-zh-hans.ttf"

say() { printf '  %s\n' "$1"; }

mkdir -p "$DEST" "$WORK"
cd "$WORK"

say "① 下载 ${ZIP}（走 ${MIRROR}）"
if [ ! -f "$ZIP" ]; then
  curl -fL --max-time 900 -o "$ZIP" "${MIRROR}/${URL}"
fi
ls -lh "$ZIP" | awk '{print "     " $5 "  " $9}'

say "② 解压"
rm -rf extract && mkdir -p extract
unzip -q -o "$ZIP" -d extract

say "③ 挑 zh-Hans 那份 TTF"
SRC="$(find extract -name '*.ttf' | grep -i 'zh.hans' | head -1 || true)"
if [ -z "$SRC" ]; then SRC="$(find extract -name '*.ttf' | head -1 || true)"; fi
if [ -z "$SRC" ]; then say "❌ 压缩包里没有 ttf"; exit 1; fi
echo "     $(basename "$SRC")"

say "④ 生成字表（ASCII + 标点 + 全角 + GB2312 全字集）"
"${PY}" - "${WORK}/chars.txt" <<'PYEOF'
import pathlib
import sys

chars: list[str] = []
chars += [chr(c) for c in range(0x20, 0x7F)]  # ASCII 可见字符
chars += [chr(c) for c in range(0x2000, 0x2070)]  # 通用标点（— … “ ” 等）
chars += [chr(c) for c in range(0x3000, 0x3040)]  # CJK 标点（、。〈《「」等）
chars += [chr(c) for c in range(0xFF00, 0xFF60)]  # 全角
# GB2312 全字集：6763 汉字 + 682 符号
for hi in range(0xA1, 0xF8):
    for lo in range(0xA1, 0xFF):
        try:
            chars.append(bytes([hi, lo]).decode("gb2312"))
        except UnicodeDecodeError:
            pass
chars += list("—…·（）【】《》「」“”‘’")  # 常用但未必在 GB2312 里的

seen: set[str] = set()
out: list[str] = []
for ch in chars:
    if ch not in seen:
        seen.add(ch)
        out.append(ch)
pathlib.Path(sys.argv[1]).write_text("".join(out), encoding="utf-8")
print(f"     字表 {len(out)} 个字符")
PYEOF

say "⑤ 子集化 → $(basename "$OUT")"
"${PY}" -m fontTools.subset "$SRC" \
  --text-file="${WORK}/chars.txt" \
  --output-file="$OUT" \
  --drop-tables+=DSIG \
  --name-IDs='*' \
  --recalc-bounds
say "⑤b 改名：OFL 要求**改动过的字体不得沿用上游名**"
"${PY}" - "$OUT" <<'PYEOF'
import sys

from fontTools.ttLib import TTFont

path = sys.argv[1]
font = TTFont(path)
# 1=家族名 3=唯一标识 4=全名 6=PostScript 名 16/17=排版家族/子家族
for rec in font["name"].names:
    if rec.nameID in (1, 4, 16):
        rec.string = "Sammy Pixel"
    elif rec.nameID == 3:
        rec.string = "Sammy Pixel (Fusion Pixel Font subset)"
    elif rec.nameID == 6:
        rec.string = "SammyPixel-Regular"
    elif rec.nameID == 17:
        rec.string = "Regular"
font.save(path)
print("     家族名已改为 Sammy Pixel（OFL 保留字体名不受污染）")
PYEOF
ls -lh "$OUT" | awk '{print "     " $5 "  " $9}'

say "⑥ 许可证与出处（OFL-1.1 要求随分发带上）"
LIC="$(find extract \( -iname '*LICENSE*' -o -iname '*OFL*' \) -type f | head -1 || true)"
if [ -n "$LIC" ]; then
  cp "$LIC" "${DEST}/LICENSE-OFL.txt"
  echo "     从压缩包复制：$(basename "$LIC")"
else
  curl -fL --max-time 120 -o "${DEST}/LICENSE-OFL.txt" \
    "${MIRROR}/https://raw.githubusercontent.com/TakWolf/fusion-pixel-font/master/LICENSE-OFL" \
    || say "     ⚠️ 许可证没取到，请手工补 assets/fonts/LICENSE-OFL.txt"
  echo "     从仓库取 LICENSE-OFL"
fi

cat > "${DEST}/README.md" <<EOF
# 字体（随项目分发的唯一一份第三方资源）

**缝合像素字体 / Fusion Pixel Font** —— 开源的泛中日韩像素字体（黑体风格）。

- 出处：https://github.com/TakWolf/fusion-pixel-font
- 版本：\`${VER}\`（12px 比例模式，zh-Hans 字形）
- 许可：**SIL Open Font License 1.1**（见 \`LICENSE-OFL.txt\`，随字体一起分发，别删）
- 本仓库里这一份是**子集**：GB2312 全字集 + ASCII + 中文标点 + 全角，
  用 \`scripts/fetch_pixel_font.sh\` 从上游重新生成（上游完整版约 48MB，子集后约 1~2MB）。

## 为什么用它

整个界面是像素风格，字若是系统矢量字体（抗锯齿），一眼就不是"那台老机器"。
像素字体要用它的**设计字号整数倍**（12px 的 2 倍 = 24px），像素才不糊 ——
所以布局里的字号都是 12 的倍数（见 \`src/sammy/layout.py\`）。
EOF

say "⑦ 完成"
echo "     字体：${OUT}"
echo "     说明：${DEST}/README.md"
echo "     许可证：${DEST}/LICENSE-OFL.txt"
