# GitHub 调研 · 机器人表情图形化（为 Sammy 而搜）

> 时间：2026-10-15 · 方法：GitHub 公共 API（未登录）· 16 组关键词 · 去重后约 100 个仓库 · 精读 20+
> 红线前提：**GPL/AGPL 代码一行不抄**（只借设计思路）；无许可证仓库视同不可用。
> 本文件只记录**调研结论**，不引入任何第三方代码。

---

## 一、先说结论

1. **Sammy 的路线是对的** ✓ —— 市面上"桌面机器人有表情"的技术路线基本两种：
   **① 点阵/像素脸（OLED/LCD 画眼）** 和 **② 3D/渲染脸（Live2D、GL）**。
   前者是绝大多数低成本硬件项目的选择，也是 Sammy 的选择（800×480 设备坐标系 + 像素字体 + 局部重绘）。
   **没有发现"比 Sammy 更先进"的现成方案** ✓ —— 大家解决的问题几乎一样：眼型集合、动效曲线、状态机、不阻塞播放。
2. **最值得借鉴的不是代码，是"眼型分类表"和"待机轮换"** ✓ —— 两个具体的设计模式，见第五节。
3. **最相关的两个项目恰好都是 GPL** ✗ —— `playfultechnology/esp32-eyes`(380★ GPL-3.0) 与
   `ggldnl/Procedural-Expression-Library`(23★ GPL-3.0，Cozmo/Vector 风格程序化表情)。
   **只能读思路，不能抄** —— 这一点和我 10-14 出的《许可证结论_v1》一致。

---

## 二、四类项目（按用途分组）

### A. 表情引擎 / 眼睛动画库（最贴近 Sammy 的问题）

| 项目 | ★ | 许可证 | 可采纳 | 一句话 |
|---|---|---|---|---|
| [Irisoled](https://github.com/orji123/Irisoled) | 74 | **MIT** | ✅ 可用 | Arduino 眼睛表情库，**32 个眼型位图 + 非阻塞动画播放器**（millis 驱动、不用 delay） |
| [Grobot_Animations](https://github.com/tanmaywankar/Grobot_Animations) | 13 | **MIT** | ✅ 可用 | 7 种情绪 + 3 个"动态待机"的轻量表情库，`setEmotion()` 一行切换 |
| [Procedural-Expression-Library](https://github.com/ggldnl/Procedural-Expression-Library) | 23 | **GPL-3.0** | ⚠️ 只借思路 | **程序化**生成表情（不是位图集），受 Cozmo/Vector 启发 —— 思路最贴近 Sammy |
| [esp32-eyes](https://github.com/playfultechnology/esp32-eyes) | 380 | **GPL-3.0** | ⚠️ 只借思路 | 本项目既有参考（已在 `refs/`），Cozmo 风格情感眼 |
| [Ani-Emo-Eye](https://github.com/AsutoshPati/Ani-Emo-Eye) | 50 | **MIT** | ✅ 可用 | OLED 眼睛随**情绪分数**变化（sentiment → 眼型映射）|
| [Irisoled 同族 / TeensyEyes](https://github.com/chrismiller/TeensyEyes) | 36 | **MIT** | ✅ 可用 | Uncanny Eyes 的 Teensy 移植（跟随瞳孔/虹膜渲染）|

### B. 硬件脸（双圆屏 / 圆屏 —— 和 Sammy 的硬件形态直接相关）

| 项目 | ★ | 许可证 | 一句话 |
|---|---|---|---|
| [dual_lcd_robot_eyes](https://github.com/upiir/dual_lcd_robot_eyes) | 63 | **MIT** | **Waveshare 0.71" 双圆屏** + ESP32-C3-Zero，做两只眼 |
| [ESP32LCDRound240x240Eyes](https://github.com/thelastoutpostworkshop/ESP32LCDRound240x240Eyes) | 120 | **MIT** | GC9A01 圆屏 + TFT_eSPI 的完整保姆教程 |
| [ESP32-CAM-EYES](https://github.com/mabuware/ESP32-CAM-EYES) | 24 | **GPL-3.0** | 1.28" 圆屏双眼球，**眼球跟随光源**（想法很好）|
| [lego_dasai_mochi](https://github.com/upiir/lego_dasai_mochi) | 11 | **MIT** | 乐高头盔 + XIAO ESP32S3 + 128×128 IPS 脸 |

### C. 整机桌面机器人（对手形态，看它们的"活物感"从哪来）

| 项目 | ★ | 许可证 | 一句话 |
|---|---|---|---|
| [stackchan_alive](https://github.com/RobVanProd/stackchan_alive) | 9 | **Apache-2.0** | Stack-chan 的「Character OS」：**程序化脸** + 唤醒词 + 本地小模型 |
| [stackchan-face-editor](https://github.com/zziying/stackchan-face-editor) | 17 | **MIT** | **浏览器里的参数化脸编辑器**：调参数捏脸 → 生成 URL 分享 |
| [stackchan-openapi](https://github.com/zziying/stackchan-openapi) | 89 | **MIT** | 把 Stack-chan 变成 HTTP 可控 + 人脸跟随 |
| [Tobi-esp32-robot](https://github.com/samrobotech/Tobi-esp32-robot) | 21 | **MIT** | 紧凑型桌面陪伴机器人（OLED 眼 + 电容触摸）|
| [ESP32-Pet-Robot](https://github.com/SukunDev/ESP32-Pet-Robot) | 27 | **MIT** | 触摸/声音/运动触发情绪（happy/angry…）|
| [mini-robot-face](https://github.com/EzioGraphy/mini-robot-face) | 3 | **MIT** | Cozmo 风格的脸（最小的可读参考实现）|

### D. 经典谱系（"眼睛渲染"的老祖宗，看渲染手法的来源）

| 项目 | ★ | 许可证 | 一句话 |
|---|---|---|---|
| [adafruit/Uncanny_Eyes](https://github.com/adafruit/Uncanny_Eyes) | 83 | 无明确许可 ⚠️ | 双 OLED 拟真眼（虹膜纹理 + 眨眼 + 视线），后来所有"uncanny eyes"都源自它 |
| [ESP32-UncannyEyes](https://github.com/sbouthillier/ESP32-UncannyEyes) | 18 | 无明确许可 ⚠️ | 240×240 TFT 移植 |
| [homer_robot_face](https://github.com/homer-robotics/homer_robot_face) | 15 | 无明确许可 ⚠️ | ROS 包：一个可显示多种表情的机器人脸（3D 渲染路线）|
| [Facemoji](https://github.com/huihut/Facemoji) | 456 | **GPL-3.0**（归档）| 摄像头模仿人脸表情（Live2D 路线，和 Sammy 场景不同）|

---

## 三、对标 Sammy：我们已有 vs 我们还缺

**Sammy 已经有（这次调研里没看到别人做得更好的）**：
- 35 个表情（12 情绪 + 5 系统态 + 左右不对称）· 24 个 GIF 动图 · 纯函数动画（`anim.py`）
- 只重画脸那一小块（性能）· 凝视漂移 / 好奇 / 打字机 / CRT 质感 / 作息与睡相 Z
- 800×480 设备坐标系 + 像素字体（12 的整数倍字号）· 非阻塞、无 `delay`

**Sammy 缺的（这次调研给出的三个可落地缺口）**：

| 缺口 | 别人怎么做的 | 建议 |
|---|---|---|
| **① 眼型不够"参数化"** | Irisoled 用 32 张位图穷举；Procedural-Expression-Library 用参数（眼睑开合度/眉毛角度/瞳孔位置）**算**出来 | Sammy 现在也是"整帧"路线。**短期不必改**（整帧更稳、更好审图）；但可把 Irisoled 的 32 个眼型当**对照表**，检查 Sammy 的 35 个表情有没有漏掉"眼睑半闭 / 斜视 / 单眼眨 / 困惑"这类细分 |
| **② 待机不轮换** | Grobot 有 `IDLE1 / IDLE2 / IDLE3` "动态待机"，随机轮播，避免"呆住" | **建议采纳**：Sammy 现在只有微动（±2px）+ 呼吸，缺"待机小节目"轮换。成本低、活物感提升明显 |
| **③ 没有"捏脸"工具** | stackchan-face-editor 是浏览器里调参数捏脸、生成 URL 分享 | **暂不做**（Sammy 的表情是手绘位图 + 代码生成，等表情定型后再说）。但它证明了「参数化脸 + 可视化编辑」是社区认可的形态 |

**另外两个想法（值得记一笔）**：
- **眼球跟随光源**（ESP32-CAM-EYES）：Sammy 有"看着你的鼠标"（`test_gaze`），但没有"被光吸引"。可以作为下一个自选小步。
- **情绪分数 → 眼型映射**（Ani-Emo-Eye）：Sammy 的 `mood` 是数值驱动的，方向一致 ✓，可以更明确地把"分数 → 表情档位"写进 TUNING。

---

## 四、许可证红线（重申）

| 类别 | 项目 | 处置 |
|---|---|---|
| MIT / Apache-2.0 | Irisoled、Grobot、dual_lcd、stackchan_alive、Ani-Emo-Eye、TeensyEyes 等 | 可以用，但**必须保留版权与许可声明**（若真引入代码）|
| GPL-3.0 | **esp32-eyes、Procedural-Expression-Library、ESP32-CAM-EYES、Facemoji** | **只读思路，一行不抄**；整机出货打包固件会被传染 |
| 无明确许可 | Uncanny_Eyes、ESP32-UncannyEyes、homer_robot_face、RobotDuck_Head | **视同不可用**（默认全权保留），连片段都不复制 |

---

## 五、建议动作（按性价比排序）

1. **立刻可做（低成本）**：把 Irisoled 的 32 个眼型名当**对照表**，逐条核对 Sammy 的 35 个表情 ——
   输出一张"缺哪几个细分眼型"的清单，只补真正缺的（预计 2~4 个）。
2. **下一个自选小步**：**待机小节目轮换**（借鉴 Grobot 的 IDLE1/2/3）——
   在现有微动/呼吸之上，加 3 个低频小动作（歪头看、眨眼两下、若有所思），随机 8~20 秒一次，不打断当前表情。
3. **再下一个**：**被光吸引**（借鉴 ESP32-CAM-EYES 的眼球跟随光源）——
   Sammy 已有"看着你的鼠标"，扩展成"跟着屏幕亮部/鼠标移动"，代价小、戏剧性强。
4. **暂不做**：参数化脸编辑器、Live2D/3D 路线、ROS 集成（和 Sammy 的定位/成本不匹配）。

---

## 六、附：本次搜索用到的关键词

`robot face expression` · `robot eyes animation` · `esp32 eyes` · `robot face display` ·
`lcd robot face` · `robot facial expression` · `eye animation oled` · `anime robot face` ·
`desktop robot face` · `emoji face robot` · `uncanny eyes` · `cozmo expression` ·
`procedural facial expression robot` · `facial animation library robot display` ·
`stackchan face` · `pixel face embedded display`

（检索走 `api.github.com/search/repositories`，未登录限 10 次/分钟；每条都记录 `license.spdx_id`。）
