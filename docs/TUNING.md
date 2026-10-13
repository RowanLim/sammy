# Sammy · 调参速查（改哪个数 → 会怎样）

> 缘起：8 小时报告（REPORT-8H.md）里 6 个「待拍板」的答案基本都是「调一个数」。
> 这页把「哪一个数」落到确切的文件与常量上：**表里的每个值都由
> tests/test_tuning_doc.py 与代码对账**（代码改了忘改这页，测试会红）。
> 第二轮（UI 优先）的拍板点也并进来了：第 8~11 节（字体 / 打字机 / 凝视 / 淡化）。
> 第 12 节是后来的自选小步：开机自检序列；第 13 节关机序列、第 14 节光标凝视、
> 第 15 节搬运凝视、第 16 节说话动脸、第 17 节作息与睡相、第 18 节醒来的哈欠、
> 第 19 节无聊的叹气、第 20 节困得点头、第 21 节打字凝视、第 22 节睡梦抽动、
> 第 23 节思考凝视 也同属后续小步。

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

## 18. 醒来的哈欠（自选小步·第八次）

文件：src/sammy/anim.py

两条曲线：**拉高**（撑起来 / 撑住 / 收回去 —— 管纵向拉高和拔高）与**眯眼**
（晚一拍起步 —— 管压扁、眼睛合上）。先抻后眯才像哈欠；两条一起动会像被从中间捏住
—— 第一版就是这么翻车的，DEVLOG 有记。

- YAWN_RISE_S = 0.45（拉高：撑起来用时，秒）
- YAWN_HOLD_S = 0.45（拉高：撑住的那一小段，秒）
- YAWN_SETTLE_S = 0.70（拉高：收回去用时，秒）
- YAWN_STRETCH = 0.10（纵向拉高上限 —— 10%）
- YAWN_LIFT_PX = 3（整脸往上顶几像素）
- YAWN_SQUINT_DELAY_S = 0.55（眯眼：比拉高晚多久起步，秒）
- YAWN_SQUINT_RISE_S = 0.35（眯眼：合上用时，秒）
- YAWN_SQUINT_FALL_S = 0.70（眯眼：松开用时，秒 —— 比合上慢，像慢慢睁眼）
- YAWN_SQUINT_MIN = 0.30（眯到原来的 30%；眨眼到 14%，哈欠的眯眼浅一点、慢一点）

触发：只在「睡着 → 醒着」那一刻打一次（自己睡饱 / 被戳醒 / 被叫醒三条路共用）；
睡着时不做（calm 优先）。整段 1.60 秒 = 拉高 0.45+0.45+0.70，眯眼 0.55+0.35+0.70，
两条曲线同一条终点。
想让它更夸张：先看 tests/test_yawn.py 的几何判据（脸的局部重绘区留量按最大形变
钉着 —— 拉太猛会把额头画到框外）；想更慢：两条曲线一起加长，终点要对齐。
素材重生成：`make yawn-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 19. 无聊的叹气（自选小步·第九次）

文件：src/sammy/anim.py（形状与节奏）；门槛在 src/sammy/pet.py

无聊（boredom 驱力）过线、又没在忙的时候，它隔一会儿叹一口气：脸**缓缓沉下去、
瘪一点、屏住一下、再慢慢回起来**。和 Z（睡着）、哈欠（醒来）同一条思路 ——
状态要能被眼睛读出来。想关掉/少叹：把 SIGH_MIN_GAP / SIGH_MAX_GAP 一起调大。

- SIGH_BOREDOM_ABOVE = 0.55（无聊过这条线才叹；比「无聊脸」的 0.65 松一点）
- SIGH_MIN_GAP = 20（两次叹气之间最短，秒）
- SIGH_MAX_GAP = 60（最长；与最短之间随机 —— 别像节拍器）
- SIGH_SINK_S = 0.6（沉下去用时，秒）
- SIGH_HOLD_S = 0.3（沉住的那一小段，秒 ——「……」的停顿）
- SIGH_RISE_S = 1.1（慢慢回起来用时，秒 —— 比沉下去慢：撒气快、缓回来）
- SIGH_DEFLATE = 0.94（沉到底时纵向压到 94%）
- SIGH_SINK_PX = 4（整脸往下沉几像素；和压扁叠在一起读成「塌下来」）

整段 2.0 秒。触发闸门：睡着 / 累趴 / 刚交互完的 5 秒 / 思考中 / 动画关 —— 都不叹；
不无聊了排期清掉，但**正在叹的那口让它叹完**。想调幅度：先看 tests/test_yawn.py
的几何判据（脸的重绘区留量按最大形变钉着 —— 叹气通道也在里面）与
tests/test_sigh.py（逐点对账）。素材重生成：`make sigh-media`（帧带 + 短视频，
进 docs/8h-b2/）。

## 20. 困得点头（自选小步·第十次）

文件：src/sammy/anim.py（形状与节奏）；犯困的判定在 src/sammy/pet.py
（门槛沿用驱力自己的犯困线 —— 和「有点困了」那行字、那张脸是同一条线）。

犯困（还没睡着）的时候，它隔一会儿**点一下头**（小鸡啄米）：脸慢慢沉下去、
眼皮掉下来、撑住一下，再猛地弹回来。和 Z（睡着）、哈欠（醒来）、叹气（无聊）
同一条思路：状态要能被眼睛读出来。想更少打盹：把 NOD_MIN_GAP 与 NOD_MAX_GAP
一起调大。

- NOD_MIN_GAP = 35（两次点头之间最短，秒）
- NOD_MAX_GAP = 90（最长；两者之间随机 —— 别像节拍器）
- NOD_SAG_S = 1.40（沉下去用时，秒 —— 慢：是「扛不住」，不是「点头称是」）
- NOD_HOLD_S = 0.30（撑住的一小段，秒 ——「睡着了一瞬」）
- NOD_SNAP_S = 0.28（弹回来用时，秒 —— 猛地惊醒，比沉下去快一个量级）
- NOD_SQUINT_MIN = 0.50（沉到底时压到 50%：眼皮快合上；眨眼 14%、哈欠眯眼 30%）
- NOD_SINK_PX = 5（整脸往下沉几像素；和压扁叠在一起读成「头一点」）

整段 1.98 秒。触发闸门：睡着 / 不够困 / 刚交互完的 5 秒 / 思考中 / 动画关 ——
都不点；不困了排期清掉，但**正在点的那下让它点完**（半路掐掉像被抽了一下）。
想调幅度：先看 tests/test_yawn.py 的几何判据（脸的重绘区留量按最大形变钉着 ——
点头通道也在里面）与 tests/test_nod.py（逐点对账）。素材重生成：
`make nod-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 21. 打字凝视「看着你写」（自选小步·第十一次）

文件：src/sammy/anim.py（凝视与节奏）；喂它的是 src/sammy/pet.py 的 `_on_typing`
（输入框 textChanged 真信号链）。

你在输入框里敲字 = 在跟它说话（还没说完）：它把四处看的视线收回来，落到
输入框上（正下方）；你停手 `TYPING_HOLD_S` 秒，它才回去发自己的呆。优先级：
光标（手在指东西）第一 —— 刚指过的那一眼先看够，打字垫底；睡着 / 动画关不做；
写字这段时间不叹气、不栽头（两条空闲闸门也钉着）。

- TYPING_HOLD_S = 4（最后一个键之后还看多久，秒 —— 和「刚交互 5 秒」一个量级）
- TYPING_RETARGET_MIN_S = 0.35（发现你在写后的转视最小间隔，秒；别一敲字就弹）
- TYPING_GAZE_Y = 6（视线落点：纵向拉满凝视盒 = 看正下方那行；输入框就在脸正下方）

想让它「看一眼就回来」：调小 TYPING_HOLD_S；想让它更早/更迟转过去：动
TYPING_RETARGET_MIN_S；想看得别那么低：调小 TYPING_GAZE_Y（0 = 回正中）。
素材重生成：`make typing-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 22. 睡梦抽动（自选小步·第十二次）

文件：src/sammy/anim.py（形状与节奏）；喂它的是 src/sammy/pet.py 的 `_tick`
（`self.anim.note_asleep(self.anim_t, self.drives.asleep)`，和驱力钟同一拍）。

睡着不只是「不动 + 一个 Z」：真的活物睡着会做梦 —— 偶尔轻轻抽一下（一激灵），
然后接着睡。这是第一条**只在睡着时**出现的通道（别的全是醒着时的）；醒了立刻
就不画了（calm 优先 —— 醒来有醒来该做的事，比如哈欠）。方向一左一右交替
（不掷随机数：抽动本身很稀疏看不出交替，而且不占随机流 —— 同种子的孪生对比
才拼得上）。想更少抽：把 TWITCH_MIN_GAP / TWITCH_MAX_GAP 一起调大。

- TWITCH_MIN_GAP = 25（两次抽动之间最短，秒）
- TWITCH_MAX_GAP = 70（最长；两者之间随机 —— 别像节拍器）
- TWITCH_JOLT_S = 0.07（抽上去用时，秒 —— 快：肌肉一激灵）
- TWITCH_HOLD_S = 0.05（顶住的一瞬，秒 —— 让眼睛来得及看见）
- TWITCH_SETTLE_S = 0.28（松回来用时，秒 —— 比抽上去慢得多，像又睡过去了）
- TWITCH_SHIFT_PX = 3（横向一激灵的幅度，设备像素；方向一左一右交替）
- TWITCH_DEFLATE = 0.91（抽到顶时纵向压到 91% —— 全身一缩）

整段 0.40 秒；刚睡着先等一个间隔再抽第一下（立刻抽 = 痉挛，不是做梦）。
「刚交互 5 秒」这类空闲闸门不管它 —— 睡着时它不在忙任何别的事。
想调幅度：先看 tests/test_yawn.py 的几何判据（睡时最坏组合 = 定格凝视 +
一激灵，单独一条）与 tests/test_twitch.py（逐点对账）。素材重生成：
`make twitch-media`（帧带 + 短视频，进 docs/8h-b2/）。

## 23. 思考凝视「想事情的时候，抬起头来」（自选小步·第十三次）

文件：src/sammy/anim.py（凝视与节奏）；喂它的是 src/sammy/pet.py 的 `_anim_tick`
（`self.thinking` 电平每帧折算成「想没想」喂给动画层）；发送那一刻还顺手结束了
「看着你写」的阶段（`end_typing`，在 pet.py 的 `send()` 里）—— 话交出去了，
视线不该还钉在输入框上。

你按下发送、它开始想（思考点转起来）的时候，把视线抬到上方 —— 像人回忆 /
盘算时那样；想完了把视线收回来（缓动回正中 = 看回你），再回去发自己的呆。
优先级垫底（光标 > 打字 > 思考）：被叫到先看你，看够 / 你停手之后接着想；
睡着 / 动画关 / 被搬着时都不做。

- THINKING_RETARGET_MIN_S = 0.35（想 / 收两次转视的最小间隔，秒；和光标 / 打字共用一条限速）
- THINKING_GAZE_Y = -6（抬头的落点：纵向拉满凝视盒；负 = 看上方 —— 和打字的「看正下方」对称）

嫌它反应太快或太黏：动 THINKING_RETARGET_MIN_S 这个数（两次转视的最小间隔，秒）。
落点想改高度：它现在就是负的 `GAZE_MAX_Y`（即 -6），要更高得先动凝视盒的上限本身。
这两条改动都先看 tests/test_yawn.py 的几何守卫（重绘区留量）与
tests/test_thinking.py 的逐点对账。素材重生成：`make thinking-media`
（帧带 + 短视频，进 docs/8h-b2/）。


## 24. 摸摸头「手停在脸上的时候，眯起眼呼噜一下」（自选小步·第十四次）

文件：动画层的摸摸头包络与呼噜在 anim.py 里；喂它的是 pet.py 的 _poll_cursor
（光标在不在脸框里，设备坐标，每帧一次）；「停够才算」在动画层里判（PET_DWELL_S
这个数）。开关语义：SAMMY_LOOK 设 off 时光标功能整个关掉，摸摸头一并关
（连读都不读）。

光标**停进脸框**、停够 0.6 秒 = 在摸它：慢慢眯起眼（舒服）、配一层轻轻的呼噜
起伏；手拿开从当前档位缓出（不跳）。路过 / 划过去都不算（没停够什么都不留）；
睡着 / 动画关 / 被搬着都不做。它是脸的形变通道，不和凝视抢优先级。

- PET_DWELL_S = 0.6（光标在脸上停这么久才算「在摸」，秒）
- PET_EASE_IN_S = 0.35（眯起来用时，秒）
- PET_EASE_OUT_S = 0.55（手拿开、睁开用时，秒）
- PET_SQUINT_MIN = 0.55（眯到 55%；眨眼 14% / 哈欠 30% / 点头 50%）
- PET_PURR_PERIOD = 0.9（呼噜一拍，秒 —— 和呼吸的 4.5 秒错开，才读得出「呼噜」）
- PET_PURR_PX = 2（呼噜起伏，正负设备像素；已计入重绘区预算）

嫌它太黏（手一放上就眯）：调大 PET_DWELL_S 这个数。嫌眯得不够明显：调小
PET_SQUINT_MIN 这个数。想让它摸头更闹腾：调大 PET_PURR_PX —— 但先看
tests/test_yawn.py 的几何守卫（呼噜的纵向平移进了重绘区预算，动了会撞它）
与 tests/test_petting.py 的逐点对账。素材重生成：make petting-media （帧带 +
短视频，进 docs/8h-b2/）。
