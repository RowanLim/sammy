# Sammy

> 住在你桌面上的小家伙。

Sammy 是一个有脸、有声音、有记忆的**个人 AI agent**。它不只是陪着你，它真能帮你把事想明白、把问题解决掉。

**独立大脑** —— Sammy 不挂在 Hermes 上，它自己接大模型、自己攒能力。

---

## 状态

🟡 **M1 进行中 —— 骨架已跑通**

已经能跑：对话（平均 2.0s）、情绪驱动表情、35 张表情渲染、透明浮窗、拖拽、戳一下有反应、空闲会犯困会睡着、**记忆（槽位+日记+夜间整理，重启不丢）**、出错不崩。

还没做：双击即开的 `.app`、TTS、唤醒词、休息提醒、驱力系统、主动心跳、MCP 工具层。

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

## 铁律

1. **PRD 是唯一事实来源** —— 想加功能，先改 PRD，再写代码。
2. **每个改动一个 commit** —— 旧项目 7959 行零 git 的教训。
3. **凭证永不硬编码** —— 走 `.env`，不进仓库。
4. **旧代码在 `/Volumes/Mac mini/Sammy`，只读参考** —— 需要哪个资产就搬哪个进来，不再就地改。

## 相关

- 旧项目（只读）：`/Volumes/Mac mini/Sammy` —— 7959 行 Python，4 个版本，0 个 git 仓库
- 硬件方案：树莓派 4B + 5寸 IPS 触控屏 + MG90S×2 + PCA9685，≈¥400（M2 之后采购）
- 协作方：Max（Mac）、Nex（Linux）
