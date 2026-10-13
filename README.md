# Sammy

> 住在你桌面上的小家伙。

Sammy 是一个有脸、有声音、有记忆的**个人 AI agent**。它不只是陪着你，它真能帮你把事想明白、把问题解决掉。

**独立大脑** —— Sammy 不挂在 Hermes 上，它自己接大模型、自己攒能力。

---

## 状态

✅ **M1 完成** —— `make accept` 验收：**7/7 已测项通过**（8 小时稳定性按 Rowan 决定推迟）。

已经能跑：对话（**p50 1.1s**，DeepSeek）、连续 10 轮不丢上下文、情绪驱动表情（**难过必给安慰脸**）、
35 张表情、透明浮窗、拖拽、戳一下有反应、空闲会犯困会睡着、**记忆（槽位+日记+夜间整理，重启不丢）**、
**驱力系统**（精力/无聊/亲近随时间漂移）、**主动心跳**（自己判断要不要先开口，带免打扰与每日上限）、
**休息提醒**（连续用 40 分钟，可推后）、断网给一句人话不崩、**双击即开的 `.app`（278MB）**。

还没做（都差硬件）：用话筒真听你说 —— 耳朵 / 唤醒 / 语音回路的代码都已就位，M2 只差一支话筒；小屏对壳与舵机身体按原计划走。

📌 **2026-10-11 8 小时自主推进**（Max 接管）：新增**心情底色**、**回忆主动性**、**face-only 小屏形态**、**看门狗**、**MCP 工具层**；数字、截图、短视频与验收清单见 [docs/REPORT-8H.md](docs/REPORT-8H.md)。

📌 2026-10-11 第二轮 UI（像素字体 / 会看的脸 / 打字机 / CRT 质感）之后的小步：**开机自检序列** —— 上电扫掠 / 自检行 / 唤醒淡入，点一下跳过，`SAMMY_BOOT=off` 可关；关闭钮换成手画像素叉。调参见 [docs/TUNING.md](docs/TUNING.md) 第 12 节。

📌 再往后的自选小步：**关机序列**（退出时画面收束成一条线、一颗光点）与**光标凝视「它在看着你」** —— 你动鼠标它会看过来、停几秒回去发呆，`SAMMY_LOOK=off` 可关。调参见 [docs/TUNING.md](docs/TUNING.md) 第 13、14 节。

📌 再补一刀（U1 的漏网面）：**输入框**（QLineEdit 子控件）原先漏了字体家族、一直静默用系统字体 —— 现已接上 Sammy Pixel 像素字（前后对比见 [docs/8h-b2/input-font.png](docs/8h-b2/input-font.png)）。

📌 第五个自选小步：**搬运凝视「被带去哪儿就看哪儿」** —— 拖动窗口（= 被搬走）时脸看向行进方向、松手不泄气，`SAMMY_LOOK=off` 可关。对比图与短视频见 [docs/8h-b2/carry-strip.png](docs/8h-b2/carry-strip.png)；调参见 [docs/TUNING.md](docs/TUNING.md) 第 15 节。

📌 第六个自选小步：**说话动脸「字在往外冒，脸跟着动」** —— 打字机在吐字时脸跟着弹
（一拍 0.44 秒、±2.6 设备像素），字停了脸也停；`SAMMY_ANIM=off` 连时间轴都不给。
波形证据（亮像素质心 δ 实测）与短视频见 [docs/8h-b2/talk-strip.png](docs/8h-b2/talk-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 16 节。

📌 第七个自选小步（补记）：**作息与睡相** —— 它有自己的日夜（夜里精力消耗 ×1.6、自己走到犯困），
睡着时脸边慢慢冒 Z；`SAMMY_ANIM=off` 连 Z 都没有。素材 [docs/8h-b2/doze-strip.png](docs/8h-b2/doze-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 17 节。

📌 第八个自选小步：**醒来的哈欠「睡醒了先伸个懒腰」** —— 自己睡饱 / 被戳醒 / 被叫醒的那一刻
先抻高（+10%）、再眯眼撑一小会（压到 30%）、慢慢松开，1.6 秒演完；睡着时不打。
帧带与短视频见 [docs/8h-b2/yawn-strip.png](docs/8h-b2/yawn-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 18 节。

📌 第九个自选小步：**无聊的叹气「没人理的时候，隔一会儿叹一口气」** —— 无聊过线、又没在忙时，
脸缓缓沉下去（4px）、瘪一点（压到 94%）、屏住一下再慢慢回起来；每 20~60 秒一口、
2 秒演完，睡着 / 刚说完话时都不叹。帧带与短视频见
[docs/8h-b2/sigh-strip.png](docs/8h-b2/sigh-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 19 节。

📌 第十个自选小步：**困得点头「困了的时候，一点一点地打盹」** —— 犯困（还没睡着）时，
隔一会儿小鸡啄米：脸慢慢沉下去（5px）、眼皮掉下来（压到一半）、撑住一下再猛地弹回来；
每 35~90 秒一下、2 秒演完，睡着 / 刚说完话时都不点。帧带与短视频见
[docs/8h-b2/nod-strip.png](docs/8h-b2/nod-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 20 节。

📌 第十一个自选小步：**打字凝视「看着你写」** —— 你在输入框里敲字的时候，
它把四处看的视线收回来、落到输入框上（正下方）；你停手 4 秒才回去发自己的呆。
和光标凝视共用同一条凝视盒与缓动，光标刚指过时先让路；睡着 / 动画关不做；
写字时不叹气、不栽头。帧带与短视频见
[docs/8h-b2/typing-strip.png](docs/8h-b2/typing-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 21 节。

📌 第十二个自选小步：**睡梦抽动「睡着的时候，偶尔轻轻抽一下」** —— 睡着不只是「不动 + 一个 Z」：
真的活物睡着会做梦 —— 偶尔轻轻抽一下（横向 ±3px 一激灵 + 纵向一缩到 91%），
0.4 秒演完、每 25~70 秒才有一下（方向一左一右交替）；醒着时一眼都没有。帧带与短视频见
[docs/8h-b2/twitch-strip.png](docs/8h-b2/twitch-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 22 节。

📌 第十三个自选小步：**思考凝视「想事情的时候，抬起头来」** —— 你按下发送、它开始想的时候，
视线抬到正上方（像人在回忆 / 盘算）；想完了收回来（缓动回正中）；发送那一刻
「看着你写」的阶段也一并结束。优先级垫底（光标 / 打字都优先），睡着 / 动画关不做。
帧带与短视频见 [docs/8h-b2/thinking-strip.png](docs/8h-b2/thinking-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 23 节。

📌 第十四个自选小步：**摸摸头「手停在脸上的时候，眯起眼呼噜一下」** —— 光标停进
它的脸框、停够 0.6 秒 = 在摸它：慢慢眯起眼（舒服）、配一层轻轻的「呼噜」起伏
（±2px、0.9 秒一拍）；手拿开再慢慢睁开（顺带朝手看一眼）。路过、划过去都不算；
睡着 / 动画关 / 被搬着都不做。帧带与短视频见
[docs/8h-b2/petting-strip.png](docs/8h-b2/petting-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 24 节。

📌 第十五个自选小步：**打个喷嚏「偶尔呛一下的小家伙（哈啾）」** —— 醒着的时候，
隔一阵没来由地一个喷嚏：脸先皱起来（「哈——」的酝酿）、猛地一缩闭上眼
（压到 12%、上窜 3px、横向一哆嗦）、再慢慢松回来，0.64 秒演完；
喷嚏是反射不是态度 —— 不躲着交互（跟人说着话照样打），躲的只有睡着 / 被拎着 /
动画关。帧带与短视频见 [docs/8h-b2/sneeze-strip.png](docs/8h-b2/sneeze-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 25 节。

📌 第十六个自选小步：**哼小曲「心情好的时候，摇头晃脑哼两句」** —— 心情到「很好」
的时候，隔一会儿轻轻晃两下脑袋（左右各摆 ±4px、约 1.7 秒一拍、晃 3 下），
右上角冒一个像素小音符（和睡着的 Z 同一格）；它是第一条**只挂心情**的自发动作 ——
好心情也要能被眼睛读出来。睡着 / 累趴 / 被拎着 / 正在看你写字的时候不哼。
帧带与短视频见 [docs/8h-b2/hum-strip.png](docs/8h-b2/hum-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 26 节。

📌 第十七个自选小步：**歪头「被戳了，歪着脑袋看你（唔？）」** —— 戳一戳终于有了身体语言：
醒着被戳，整张脸绕中心轻转 5 度（第一下左半边沉、第二下右半边沉），停半秒再直回来 ——
它是第一条**旋转**形变（此前全是平移与缩放）。睡着被戳是「叫醒」（哈欠那条路）、累趴与
动画关都不歪。帧带与短视频见 [docs/8h-b2/tilt-strip.png](docs/8h-b2/tilt-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 27 节。

📌 第十八个自选小步：**好奇歪头「你写的时候，歪着脑袋看你在写什么」** —— 你在输入框里
写字的那段时间不再是一动不动的注视：写起来了就隔一小会儿轻轻歪一下脑袋（第一下
1.5~3 秒内就来，之后每隔 12~24 秒随机一下），停半秒再直回去继续看你写；停手或发送
之后排期作废、下一段重头起算。和歪头（第十七次）共用同一条旋转（±5 度、绕脸中心、
最近邻取样）；光标刚指过时一起让位，睡着 / 动画关不做。帧带与短视频见
[docs/8h-b2/typing-tilt-strip.png](docs/8h-b2/typing-tilt-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 28 节。

📌 第十九个自选小步：**入睡的一下「撑不住了」** —— 从醒到睡不再是瞬间换脸：
真正睡过去的那一刻，整脸慢慢沉下去（6px）、眼睛合上（压到 45%），屏一会儿（睡实了）、
再松回睡姿，2.6 秒演完；只在睡着那一瞬演（醒着一眼都没有）、动画关不演。
至此昼夜动作链闭合：困（点头）→ 睡着（这一下）→ 睡相（Z / 抽动）→ 醒（哈欠）。
帧带与短视频见 [docs/8h-b2/dozeoff-strip.png](docs/8h-b2/dozeoff-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 29 节。

📌 第二十个自选小步：**上电环顾「自检播完，先看一圈」** —— 开机自检交班之后，
它不再当场开始发呆乱看：先站定 0.35 秒，抬着头把左右两边各看一眼（横到满幅、
探头拉高），再收回正中交给随机漂移，整段 3.7 秒；点一下跳过自检也照样看。
复用既有凝视盒与缓动（半点新几何不加）、不掷随机数；动画关 / 睡着不排。
帧带与短视频见 [docs/8h-b2/survey-strip.png](docs/8h-b2/survey-strip.png)；
调参见 [docs/TUNING.md](docs/TUNING.md) 第 30 节。

## 目录结构（隔离约定）

**这个项目的一切都在这个文件夹里**（Rowan 定的约定，由 `tests/test_isolation.py` 钉住）：

| 目录 | 内容 | 进版本库？ |
|:---|:---|:---|
| `src/ docs/ tests/ scripts/ assets/ packaging/` | 代码、文档、测试、脚本、表情素材 | ✅ |
| `data/` | 记忆库、驱力/心跳/休息状态、`.env`（凭证） | ❌ gitignore |
| `backups/` | 每日备份产物与日志 | ❌ gitignore |
| `.tmp/` | 临时中间文件 | ❌ gitignore |
| `dist/` | 打包出来的 `Sammy.app` | ❌ gitignore |

**不在 `~/Library`、`~/Backups` 等机器级目录里留任何东西。**
唯一的例外是 `~/.hermes/scripts/sammy_backup.sh` —— 一个 3 行的转发
（Hermes 的定时任务只接受该目录下的文件名，不接受绝对路径）。要动机器别处的东西，先问 Rowan。

代价说明：盘拔了就**没记忆、没配置**（`data/` 在项目里）—— 而盘拔了 `.app` 本身也不在，
所以"应用和数据同生共死"是一致的。记忆库另有异地副本（每日推到 Nex，见 `scripts/backup.sh`）。

## 快速开始

```bash
cd "/Volumes/Mac mini/Max agent/Sammy"

# 第一次：建环境
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 跑起来（桌面上会出现 Sammy）
./run.sh
```

其他用法：

```bash
./run.sh --ask "今天好累啊，给我点建议"   # 命令行测大脑，打印回复+情绪+耗时
./run.sh --voices                       # 列出全部 35 个表情
./run.sh --snapshot out.png --expr 4    # 渲染一张脸存成 PNG（不弹窗）
./run.sh --selftest out.png             # 真实窗口 + 自检 + 截图后退出
./run.sh --memory                       # 看看 Sammy 记得什么
./run.sh --models                       # 看各档位模型配置状态（凭证只显示长度）
./run.sh --consolidate --day 2026-10-01 # 手动跑一次「夜里整理」

.venv/bin/python scripts/dev_check.py   # 自检：解析器 + 渲染 + 对话延迟 + 记忆
.venv/bin/python scripts/backup.py      # 立即备份（git bundle + 记忆库快照）
```

**凭证**：`.env` 里放 `DOUBAO_API_KEY`（见 `.env.example`）。`.env` 已被 git 忽略，永不进仓库。

## 目录

```
Sammy/
├── run.sh                 启动器
├── docs/
│   ├── PRD.md             ⭐ 产品需求文档（唯一事实来源）
│   ├── DEVLOG.md          工程记录：踩过的坑 + 架构决定
│   ├── REPORT-8H.md       ⭐ 8 小时自主推进总结（截图 / 视频 / 验收清单）
│   ├── preview-window.png 窗口渲染预览
│   └── preview-35-faces.png 35 张表情总览
├── src/sammy/
│   ├── __main__.py        入口 + 各种模式
│   ├── brain.py           独立大脑（豆包，一次调用拿回复+情绪）
│   ├── memory.py          记忆（槽位 + 日记 + 夜间整理，SQLite）
│   ├── expressions.py     表情目录 + 情绪→表情映射
│   ├── faces.py           渲染层（BMP → 亮像素）
│   └── pet.py             窗口（透明浮窗 + 交互 + 空闲行为 + 记忆接线）
├── assets/expressions/    35 张 OLED 表情 BMP（继承自旧项目）
└── scripts/               自检 / 凭证迁移 / 连通性验证
```

## 架构要点（一条就够）

**所有绘制都在 800×480 设备坐标系里做，最后整体按系数缩放。**

因为 800×480 就是那块 5 寸屏的分辨率 —— 二期搬到树莓派时，**把缩放系数从 0.55 改成 1.0**，元素位置一个都不用动。

## 开发

平台分工、工具链、日常流程、验收纪律 → 见 **[docs/开发流程.md](docs/开发流程.md)**。

```bash
pytest -m "not live"        # 离线单测（0.6 秒，提交时 pre-commit 自动跑）
pytest -m live              # 联网验收（延迟预算、重启后还记得）
pytest --cov=sammy          # 覆盖率
ruff check src tests scripts
ruff format src tests scripts
pre-commit run --all-files  # 手动跑一遍全部钩子
```

三层测试：**离线单测**（确定性、可断言）→ **联网验收**（PRD 里带数字的标准）→ **真机自检**（`--selftest`，看截图）。

## 版本与备份

| 项 | 位置 |
|:---|:---|
| **主仓库** | 外置盘 `/Volumes/Mac mini/Max agent/Sammy` |
| **远程仓库** | 内网 Gitea `ssh://git@192.168.110.177:2222/rowan/sammy.git`（Web: http://192.168.110.177:3000） |
| **本地备份** | 项目内 `backups/`（每日 03:00 自动，含 git bundle + 记忆库快照） |

三重保障：**外置盘（工作副本）→ 内网 Gitea（代码远程）→ 项目内 `backups/`（每日快照）**；记忆库每天另推一份到 Nex 异地（见 `scripts/backup.sh`）。

```bash
python3 scripts/audit_repo.py     # 全历史凭证审计（pre-push 也会自动跑）
python3 scripts/backup.py         # 立即本地备份（每日 03:00 自动跑，含记忆库）
git push origin main --tags       # 手动推远程
```

## MCP 工具层

Sammy 的外挂工具走 MCP（生态标准，不自研协议）。两代协议都会说：现代（2026-07-28 起，
无握手、请求自带 `_meta`）与遗留（2025-11-25 及以前，`initialize` 握手）；先探测、探不动
自动回退，对第三方服务也是这套。

- 配置文件：`data/mcp.json`（不存在 = 没配任何服务，一切照常）
- 查看状态：`make mcp` —— 逐个连一下，列出对面给的每个工具
- 全链路演示：`make mcp-demo` —— 离线、真子进程；假 server + 自家工具挂服务 + 挂进工具表 + 换目录无 PYTHONPATH 启动
- 反方向：把自己的工具挂成 MCP 服务，别的程序也能调 ——
  `.venv/bin/python -m sammy.mcp_server --tools current_time,web_search`

配置示例（把自己挂出来，验证链路最省事）：

```json
{"servers": [{"name": "net", "command": ".venv/bin/python", "args": ["-m", "sammy.mcp_server"]}]}
```

挂上的工具名字带 `mcp__服务名__工具名` 前缀（模型看得见、能调）；外挂服务起不来只打一行警告，
**不挡 Sammy 启动**。

配置里的相对路径（比如 `.venv/bin/python`）按**项目根**解析，子进程的 PYTHONPATH
默认带上项目 src —— 源码模式与打包后的 .app 同一份配置（冻结版真机验过：从「/」
启动、没有 PYTHONPATH 也照通）。

## 铁律

1. **PRD 是唯一事实来源** —— 想加功能，先改 PRD，再写代码。
2. **每个改动一个 commit** —— 旧项目 7959 行零 git 的教训。
3. **凭证永不硬编码** —— 走 `.env`，不进仓库。
4. **旧代码在 `/Volumes/Mac mini/Sammy`，只读参考** —— 需要哪个资产就搬哪个进来，不再就地改。

## 相关

- 旧项目（只读）：`/Volumes/Mac mini/Sammy` —— 7959 行 Python，4 个版本，0 个 git 仓库
- 硬件方案：树莓派 4B + 5寸 IPS 触控屏 + MG90S×2 + PCA9685，≈¥400（M2 之后采购）
- 协作方：Max（Mac）、Nex（Linux）
- 调参速查：docs/TUNING.md —— 6 个待拍板点（脸的大小 / 脾气 / 回忆频率 / 看门狗阈值 / MCP）各自对应哪个常量，值有测试对账
