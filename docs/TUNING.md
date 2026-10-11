# Sammy · 调参速查（改哪个数 → 会怎样）

> 缘起：8 小时报告（REPORT-8H.md）里 6 个「待拍板」的答案基本都是「调一个数」。
> 这页把「哪一个数」落到确切的文件与常量上：**表里的每个值都由
> tests/test_tuning_doc.py 与代码对账**（代码改了忘改这页，测试会红）。
> 第二轮（UI 优先）的拍板点也并进来了：第 8~11 节（字体 / 打字机 / 凝视 / 淡化）。
> 第 12 节是后来的自选小步：开机自检序列。

## 1. 脸在小屏上的大小

文件：src/sammy/layout.py

- FO_CLOSE_CLEAR = 140（脸宽上限 = 画布宽 减 140，数字调小 → 脸更大）
  - 再小会蹭到右上角的 ✕，布局测试会拦，别硬来
- 竖高受限的屏另看这三个：FO_TOP = 16、FO_GAP = 24、FO_STATUS_H = 72（都是间距）

现状（1024×768 的 4:3 屏）：脸 660×324，约屏宽 64%，同屏是完整版的 1.5 倍。

相关：它刚说的话在那一行停留的秒数 FACEONLY_LINE_HOLD = 20.0（在 src/sammy/pet.py）

## 2. 心情的推动量

文件：src/sammy/mood.py

- NUDGE = 0.12（每次回复的情绪推动）、POKE_NUDGE = 0.06（被戳一下）
- 配套：HALF_LIFE_H = 6.0（多久回基线，单位小时）、HOME = 0.15（基线）、
  FLOOR = -0.45（下限）、ALONE_AFTER_H = 3.0（多久没人理开始蔫）、
  ALONE_RATE = 0.05（蔫起来每小时往下多少）

## 3. 回忆的频率

文件：src/sammy/recall.py

- MAX_RECALLS_PER_DAY = 2（一天最多提几次）、ITEM_COOLDOWN_DAYS = 7（同一件事几天内不再提）、
  SAID_WINDOW_HOURS = 48（聊天里刚聊过的话题不重复提）
- 资格窗口：ELIGIBLE_AFTER_HOURS = 24（太新的不算「想起」）、
  ELIGIBLE_BEFORE_DAYS = 90（太旧的也不翻）

## 4. 看门狗的放弃阈值

文件：src/sammy/watchdog.py

- MAX_RAPID_CRASHES = 5（连续快速崩这么多次后放弃，放弃时退出码 GAVE_UP_CODE = 4）
- BACKOFF_BASE_S = 3.0、BACKOFF_MAX_S = 60.0（自动拉起的退避起点与封顶，单位秒）

想「永不言弃」：把 MAX_RAPID_CRASHES 调大，代价是安装坏了会一直闪屏。

## 5. MCP 的版本校验（现在宽松）

文件：src/sammy/mcp.py

- 三个版本常量：MODERN_VERSION（现在是 2026-07-28）、LEGACY_VERSION（2025-11-25）、
  LEGACY_RETRY_VERSION（2025-06-18）
- 现行策略：对方 supportedVersions 里列什么就接受什么（不认识也用第一个）。
  要收紧的话，在 _negotiate 与 _absorb_discover 两处加「只收认识的版本」的校验。

## 6. MCP 工具要不要默认开（现在：不开）

- 现在是零配置：data/mcp.json 不存在 = 不挂任何外挂工具
- 想开局就带联网工具：把 README「MCP 工具层」的示例配置存成 data/mcp.json 即可。


## 7. CRT 质感的强度（第二轮 U4）

文件：src/sammy/crt.py

- SCANLINE_ALPHA = 0.15（隔行暗线的不透明度；SCANLINE_PERIOD = 2 是网格周期）
- VIGNETTE_ALPHA = 0.30（四角的压暗顶格；VIGNETTE_INNER = 0.55 是起暗的位置）
- GLOW_OPACITY = 0.40（辉光叠回的不透明度；GLOW_DOWNSCALE = 6 是模糊半径）
- 整层可关：环境变量 SAMMY_CRT=off（写 .env 也行，语义和 SAMMY_ANIM 一套）

想淡一点：先动 SCANLINE_ALPHA 与 VIGNETTE_ALPHA；脚本 scripts/u4_preview.py
一跑就能对着图改（放大是最近邻，别糊掉隔行像素）。

## 8. 像素字体的字号（第二轮 U1）

文件：src/sammy/layout.py

- PIXEL_STEP = 12（字体设计字号；界面所有字号都吸到它的整数倍，否则字形糊一格）
- 现用：正文 / 输入 / 状态行 24 号；回复区从 36 号起、放不下就降档（备选 36、24、12）；
  face-only 那一行 40 号
- 想整体大一档：把 FONT_STATUS / FONT_INPUT / FONT_REPLY 三个常量一起调（保持 12 的倍数）；
  字体的来路与许可证在 assets/fonts/（OFL 要求改动过的字体必须改名，测试钉着）

## 9. 打字机与思考点的节奏（第二轮 U3）

文件：src/sammy/typewriter.py

- TYPE_CPS = 25.0（每秒打几个字 —— 40 毫秒一字）
- TYPE_PAUSE = 0.09（标点后额外停顿的秒数）
- TYPE_CAP = 4.5（一页最长打多久；超了整体等比加速）
- DOT_PERIOD = 0.4（思考点每帧停多久；一颗 → 三颗循环）
- PAGE_HOLD = 3.6（每页打完停多久再翻页；与布局的 PAGE_SECONDS 对账）

## 10. 凝视漂移与好奇（第二轮 U2）

文件：src/sammy/anim.py

- GAZE_MIN_GAP = 2.6、GAZE_MAX_GAP = 7.4（两次「看向新方向」的间隔范围，秒）
- GAZE_EASE = 0.55（一次转向的缓动时长；两端速度为 0，然后定格）
- GAZE_MAX_X = 10、GAZE_MAX_Y = 6（横 / 纵向摆幅，设备像素）
- CURIOSITY_STRETCH = 0.07（看向左右边缘时纵向拉高的上限 —— 7%）

## 11. 表情淡化与弹跳（第二轮 U2）

文件：src/sammy/anim.py

- FADE_DURATION = 0.38（换表情的交叉淡化时长，秒）
- POP_DURATION = 0.22（先有的「弹一下」，与淡化并存）


## 12. 开机自检序列（自选小步）

文件：src/sammy/boot.py

- POWER_DUR = 0.55（上电扫掠时长，秒）
- LOG_LEAD = 0.12（扫掠结束到第一行出现的间隔，秒）
- LINE_STEP = 0.3（自检行与行之间的间隔，秒）
- LOG_TAIL = 0.4（末行出现后停留多久进入唤醒，秒）
- WAKE_DUR = 0.65（正常画面淡入时长，秒）
- CURSOR_PERIOD = 0.5（光标亮灭一个整周期，秒；前半亮）

整段时长由上面几个数推导（六行时 3.22 秒）。文字块边距、行高、光标宽高
在 boot.py 里，不常动；想关掉整段：SAMMY_BOOT=off（写 .env 也行，语义和
SAMMY_ANIM 一套）。真启动才播 —— 快照 / 自检脚本不播，素材永远拍稳态；
素材重生成：`make boot-media`（帧带 + 放大图 + 短视频，进 docs/8h-b2/）。

---

改完任何一条：跑一遍 make check（全绿再提交）。这页自己的判据在
tests/test_tuning_doc.py；给 Rowan 的清单在 docs/CHECKLIST-8H.md（第二轮：docs/CHECKLIST-8H-B2.md），
总结在 docs/REPORT-8H.md —— 都随仓库走。
