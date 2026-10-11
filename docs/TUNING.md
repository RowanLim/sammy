# Sammy · 调参速查（改哪个数 → 会怎样）

> 缘起：8 小时报告（REPORT-8H.md）里 6 个「待拍板」的答案基本都是「调一个数」。
> 这页把「哪一个数」落到确切的文件与常量上：**表里的每个值都由
> tests/test_tuning_doc.py 与代码对账**（代码改了忘改这页，测试会红）。
> 第二轮（UI 优先）的拍板点也并进来了：第 8~11 节（字体 / 打字机 / 凝视 / 淡化）。
> 第 12 节是后来的自选小步：开机自检序列；第 13 节关机序列、第 14 节光标凝视、
> 第 15 节搬运凝视、第 16 节说话动脸也同属后续小步。

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
- **输入框也是像素字了**（QLineEdit 子控件）：家族取 layout.FAMILY（字体丢失时
  跟着回落），字号 = FONT_INPUT 乘缩放 —— 都写在样式表里（pet.py 的 _layout_input 那段）。
  U1 当时漏了家族、静默回落系统字体，后续小步补上（判据在 tests/test_input_font.py
  里，对比图见 docs/8h-b2/input-font.png）

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


## 13. 关机序列（自选小步·第二次）

文件：src/sammy/boot.py（和开机同一条时间轴家族，共用 SAMMY_BOOT 这个开关）

- COLLAPSE_DUR = 0.40（画面纵向压扁的时长，秒）
- LINE_DUR = 0.22（亮线横向收束的时长，秒）
- DOT_DUR = 0.30（光点熄灭的时长，秒）
- SQUEEZE_MIN = 0.02（纵向压扁终点系数，相对面板高）
- SHRINK_MIN = 0.04（横向收束终点系数，相对面板宽）
- DOT_SHRINK = 0.01（熄灭段继续收窄到的系数）
- CORE_H = 5（中心亮线高度，设计单位）

整段 0.92 秒；点一下（或双击）跳过，直接退。只在关闭钮 / 右键菜单的
「退出 Sammy」里播 —— w.close()（素材脚本、测试）永远是直接关。
整段由 SAMMY_BOOT=off 关掉（和开机同一个开关）；素材重生成：
`make shutdown-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 14. 光标凝视「它在看着你」（自选小步·第三次）

文件：src/sammy/anim.py

- LOOK_MOVE_MIN = 6（光标累计动这么多设备像素才算「在动」；贴身手抖不算）
- LOOK_HOLD_S = 2.5（光标停下后还朝它看多久，秒；之后回去发自己的呆）
- LOOK_RETARGET_MIN_S = 0.45（追光标时两次转视的最小间隔，秒；再快像扫视机器）

视线目标 = 光标方向按比例压进凝视盒（就是第 10 节那套 ±10 横向、±6 纵向
的盒子）：方向不扭曲、近了如实、远了贴边。整体开关：环境变量 SAMMY_LOOK
设 off（写 .env 也行，语义和 SAMMY_ANIM 一套）。素材重生成：
`make look-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 15. 搬运凝视「被带去哪儿就看哪儿」（自选小步·第五次）

文件：src/sammy/anim.py

- CARRY_GAIN = 0.08（搬动位移 → 凝视目标的增益；慢挪只有小小一瞥，快搬直接贴边）
- CARRY_MOVE_MIN = 12（累计搬这么多设备像素才转一次视线；贴着手的小抖动不算）
- CARRY_RETARGET_MIN_S = 0.35（搬运时两次转视的最小间隔，秒）

拖动窗口 = 被搬动：脸看向「被带去的方向」——和光标凝视共用同一个 ±10 / ±6 的
凝视盒与 0.55 秒缓动；放手时最后一小段零头作废（不然收尾会从满幅往回泄一截）。
按住不动 = 什么都没发生；整段挂在 SAMMY_LOOK 之下（关掉就既不看光标、被搬也不看）。
素材重生成：`make carry-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 16. 说话动脸「字在往外冒，脸跟着动」（自选小步·第六次）

文件：src/sammy/anim.py

- TALK_PERIOD = 0.44（说话「嘴动」的一拍多长，秒；约 2.3 拍每秒）
- TALK_BOB_Y = 2.6（上下弹幅，设备像素，正负）
- TALK_SQUASH = 0.02（一鼓一收的幅度，正负 2 个百分点）
- TALK_EASE_IN = 0.18（开口渐入，秒）
- TALK_EASE_OUT = 0.26（收口渐出，秒）

打字机在吐字 = 它在说话：脸按说话节奏轻轻起伏（上下弹 + 极轻一鼓一收）；
打完停住 = 闭嘴（翻页停留段与第二遍整页重放都不弹）；思考点、开机 / 关机、
睡着时都不弹。整段挂在动画总开关 SAMMY_ANIM 之下（关掉 = 没有时间轴 = 不动）。
素材重生成：`make talk-media`（帧带 + 短视频，进 docs/8h-b2/）。

---

改完任何一条：跑一遍 make check（全绿再提交）。这页自己的判据在
tests/test_tuning_doc.py；给 Rowan 的清单在 docs/CHECKLIST-8H.md（第二轮：docs/CHECKLIST-8H-B2.md），
总结在 docs/REPORT-8H.md —— 都随仓库走。

## 17. 作息与睡相（自选小步·第七次）

| 常量 | 在哪 | 现在 | 含义 |
|---|---|---|---|
| `NIGHT_FROM_H` / `NIGHT_TO_H` | drives.py | 23 / 7 | 几点到几点算"夜里"（它的作息，不是我的高峰规矩） |
| `NIGHT_DRAIN_FACTOR` | drives.py | 1.6 | 夜里精力掉得快多少倍 |
| `Z_PERIOD` | anim.py | 2.6s | 一个 Z 从冒出来到消失 |
| `Z_RISE_PX` | anim.py | 9 | 期间升起多少设备像素 |
| `Z_SHOW_FRAC` | anim.py | 0.62 | 周期里可见的比例（其余时间空着，才有"一个一个冒"） |

想让它**更早犯困**：调大 `NIGHT_DRAIN_FACTOR`（2.0 = 夜里两倍速）。
想让它**睡得更沉/更浅**：改 `Z_PERIOD`（越大越慢）。想让 Z 更显眼：调大 `Z_RISE_PX`。
⚠️ Z 的**位置**不是审美参数：它必须落在脸框（`_face_region`）内，否则局部重绘不会刷新它 ——
`test_doze.py::test_z_stays_inside_the_repainted_region` 钉着这条，别为了"挪好看点"把它挪出去。
