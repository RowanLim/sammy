# 字体（随项目分发的唯一一份第三方资源）

**缝合像素字体 / Fusion Pixel Font** —— 开源的泛中日韩像素字体（黑体风格）。

- 出处：https://github.com/TakWolf/fusion-pixel-font
- 版本：`2026.09.25`（12px 比例模式，zh-Hans 字形）
- 许可：**SIL Open Font License 1.1**（见 `LICENSE-OFL.txt`，随字体一起分发，别删）
- 本仓库里这一份是**子集**：GB2312 全字集 + ASCII + 中文标点 + 全角，
  用 `scripts/fetch_pixel_font.sh` 从上游重新生成（上游完整版约 48MB，子集后约 1~2MB）。

## 为什么用它

整个界面是像素风格，字若是系统矢量字体（抗锯齿），一眼就不是"那台老机器"。
像素字体要用它的**设计字号整数倍**（12px 的 2 倍 = 24px），像素才不糊 ——
所以布局里的字号都是 12 的倍数（见 `src/sammy/layout.py`）。
