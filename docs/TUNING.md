# Sammy · 调参速查（改哪个数 → 会怎样）

> 缘起：8 小时报告（REPORT-8H.md）里 6 个「待拍板」的答案基本都是「调一个数」。
> 这页把「哪一个数」落到确切的文件与常量上：**表里的每个值都由
> tests/test_tuning_doc.py 与代码对账**（代码改了忘改这页，测试会红）。

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

---

改完任何一条：跑一遍 make check（全绿再提交）。这页自己的判据在
tests/test_tuning_doc.py；给 Rowan 的清单在 docs/CHECKLIST-8H.md，
总结在 docs/REPORT-8H.md —— 都随仓库走。
