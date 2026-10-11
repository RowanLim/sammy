# Sammy 常用任务 —— make <目标>
#
# 原则：**本地检查与 CI 跑同一套命令**，避免"本地过了、CI 挂了"。

VENV := .venv/bin/python

.PHONY: help check check-live fmt backup app run models memory set-key drives accept soak history clear-history home mood recall face-only watchdog watchdog-status mcp mcp-demo

help:
	@echo "make run        跑起来（桌面浮窗）"
	@echo "make models     看各档位模型配置状态"
	@echo "make drives     看它此刻的驱力（精力/无聊/亲近）"
	@echo "make attention  看它此刻会不会先开口、卡在哪一条闸门"
	@echo "make recall     看它会不会想起旧事（候选池/闸门/额度）"
	@echo "make screens    列出所有屏幕，以及铺满后的结果"
	@echo "make kiosk      小屏模式：无边框铺满指定屏幕（接小屏后用这个）"
	@echo "make face-only  face-only 形态：只有一张脸 + 一行状态（复古壳那种小屏用）"
	@echo "make watchdog   看门狗：崩了自动拉起 + 崩溃日志（长期挂桌面用这个）"
	@echo "make watchdog-status 看门狗状态：在不在盯着、崩过几次"
	@echo "make mcp        看 MCP 工具层：配了哪些外挂服务（data/mcp.json）"
	@echo "make mcp-demo   MCP 全链路演示：假 server + 自家工具挂服务 + 挂进工具表（离线）"
	@echo "make report-media 重生成 8 小时报告素材（截图+视频，进 docs/8h/）"
	@echo "make ui-media       重生成第二轮 UI 素材（对比图 + 短视频，进 docs/8h-b2/）"
	@echo "make boot-media     重生成开机自检素材（帧带 + 放大图 + 短视频，进 docs/8h-b2/）"
	@echo "make shutdown-media 重生成关机序列素材（帧带 + 短视频，进 docs/8h-b2/）"
	@echo "make watchdog-demo 看门狗全流程演示（约 1 分钟，全在 .tmp/）"
	@echo "make wake       看唤醒词状态（会认哪些说法）"
	@echo "make voice-demo 语音闭环演示：唤醒→听懂→回答→说出来（用音频文件代替麦克风）"
	@echo "make fetch-models 下语音模型（唤醒词/识别/VAD，几百 MB）"
	@echo "make memory     看 Sammy 记得什么"
	@echo "make set-key    把 API key 安全写进 .env（不回显、不进日志）"
	@echo "make accept     跑 M1 验收（PRD P0 逐条，出数字）"
	@echo "make app        打包成双击即开的 .app"
	@echo "make soak       八小时稳定性压测（后台，可放心跑一夜）"
	@echo "make check      本地跑一遍 CI 会跑的全部检查"
	@echo "make check-live 联网验收（要凭证，慢）"
	@echo "make fmt        格式化 + 自动修"
	@echo "make backup     立即备份（git bundle + 记忆库）并推远程"

accept:
	$(VENV) scripts/accept_m1.py

app:
	$(VENV) scripts/build_app.py

soak:
	$(VENV) scripts/soak.py --hours 8

set-key:
	$(VENV) scripts/set_key.py --verify

run:
	./run.sh

models:
	./run.sh --models

memory:
	./run.sh --memory

attention:
	./run.sh --attention

screens:
	./run.sh --screens

wake:
	./run.sh --wake

# 语音闭环演示（没有麦克风时用音频文件代替，链路完全一样）
voice-demo:
	./run.sh --voice-demo tests/audio/wake-zh-3.wav

# 下语音模型（唤醒词 / 识别 / VAD，几百 MB，不进仓库）
fetch-models:
	./scripts/fetch_models.sh

# 小屏模式：铺满记住的那块屏（没记住就用主屏）
# 指定屏：./run.sh --kiosk --display 1
kiosk:
	./run.sh --kiosk

fmt:
	$(VENV) -m ruff check --fix src tests scripts
	$(VENV) -m ruff format src tests scripts

# 与 .gitea/workflows/ci.yml 保持一致
check:
	$(VENV) -m pytest -m "not live" -q
	$(VENV) -m ruff check src tests scripts
	$(VENV) -m ruff format --check src tests scripts
	python3 scripts/audit_repo.py

check-live:
	$(VENV) -m pytest -m live -q

backup:
	python3 scripts/backup.py
	git push origin main --tags

history:
	./run.sh --history

clear-history:
	./run.sh --clear-history

home:
	./run.sh --home

mood:
	./run.sh --mood

recall:
	./run.sh --recall

# face-only：只有一张脸 + 一行状态（复古壳那台 4:3 小屏用这个）
# 指定屏：./run.sh --kiosk --face-only --display 1
face-only:
	./run.sh --kiosk --face-only

# 看门狗：崩了自动拉起 + 崩溃日志（长期挂桌面用这个）
watchdog:
	./run.sh --watchdog

# 看门狗状态：在不在盯着、崩过几次、最近一次崩溃
watchdog-status:
	./run.sh --watchdog-status

# MCP 工具层：看配了哪些外挂服务（配置文件 data/mcp.json）
mcp:
	./run.sh --mcp

# MCP 全链路演示：三条链路全离线，还都是真子进程
mcp-demo:
	$(VENV) scripts/mcp_demo.py

# 8 小时报告的素材：截图 + 脸谱 + 短视频（进 docs/8h/，可随时重生成）
report-media:
	$(VENV) scripts/report_8h_media.py

# 第二轮 UI 素材：前后对比图 + 短视频（可反复重生成）
ui-media:
	$(VENV) scripts/u5_preview.py

# 开机自检素材（上电扫掠 + 自检行 + 唤醒淡入）
boot-media:
	$(VENV) scripts/boot_preview.py

# 关机序列素材（收束成一条线、一个点、熄灭）
shutdown-media:
	$(VENV) scripts/shutdown_preview.py

# 看门狗演示：三条真命令路径（约 1 分钟，全部落在 .tmp/）
watchdog-demo:
	$(VENV) scripts/watchdog_demo.py

.PHONY: report-media watchdog-demo ui-media boot-media shutdown-media
