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
│   ├── faces.py           渲染层（BMP → 荧光绿像素）
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
