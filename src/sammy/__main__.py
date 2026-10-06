"""Sammy 入口。

用法:
  python -m sammy              # 跑起来，桌面上出现 Sammy
  python -m sammy --ask "今天好累"   # 只测大脑（无界面），打印回复+情绪+耗时
  python -m sammy --snapshot out.png # 渲染一张脸存成 PNG，用来验证绘制
  python -m sammy --voices     # 列出全部表情编号与名称
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def voice_demo(wav_path: str) -> int:
    """语音闭环演示：一段音频 → 听见名字 → 听懂 → 回答 → 说出声。

    用音频文件代替麦克风（这台机器上没话筒），**链路完全一样** ——
    等话筒到位，把 WavSource 换成 MicSource 就是真机。
    这也是 Rowan 说的"没有麦克风没关系，你先找东西代替"。
    """
    import time as _time
    from pathlib import Path as _Path

    from .audio import list_input_devices, pad_for_context, read_wav
    from .brain import SammyBrain
    from .ears import Ears
    from .voice import Speaker, prepare_speech
    from .wake import WakeWord, strip_wake

    path = _Path(wav_path)
    if not path.is_file():
        print(f"❌ 找不到音频：{path}")
        return 2

    samples = read_wav(path)
    secs = len(samples) / 16000

    def stage(n: str, title: str, detail: str, cost: float | None = None) -> None:
        print(f"{n} {title:<12} {detail}" + (f"   ({cost:.2f}s)" if cost is not None else ""))

    print("=== Sammy 语音闭环演示 ===")
    print(f"音频：{path.name}（{secs:.1f}s）")
    devs = list_input_devices()
    if devs:
        print(f"输入：这台机器有 {len(devs)} 个录音设备（{devs[0]['name']}）")
    else:
        print("输入：**没有麦克风 → 用音频文件代替**（同一套链路，换 MicSource 即真机）")
    print()

    # ① 唤醒
    t0 = _time.perf_counter()
    hits = WakeWord().load().detect(pad_for_context(samples))
    if not hits:
        stage("①", "听唤醒词", "❌ 没听到「嗨萨米 / Hi Sammy」", _time.perf_counter() - t0)
        print("\n（没被叫名字就不该答应 —— 这是对的。）")
        return 1
    stage("①", "听唤醒词", f"✅ 听到「{hits[0]}」", _time.perf_counter() - t0)

    # ② 听懂
    t0 = _time.perf_counter()
    heard = Ears().load().transcribe(samples)
    stage("②", "听懂你说什么", f"“{heard}”", _time.perf_counter() - t0)
    ask = strip_wake(heard) or heard
    if ask != heard:
        print(f"{'':<15}去掉唤醒词 → “{ask}”")

    # ③ 回答
    t0 = _time.perf_counter()
    try:
        result = SammyBrain().chat(ask)
    except RuntimeError as e:
        stage("③", "想怎么回", f"❌ 连不上大模型：{e}")
        return 3
    stage(
        "③",
        "想怎么回",
        f"“{result['reply']}”  emotion={result.get('emotion')}",
        _time.perf_counter() - t0,
    )

    # ④ 说出来
    # 这里直接调后端（同步）—— 界面上走的是异步 Speaker，同一个后端；
    # 同步调用让"念了多久"能算准，也避免演示脚本抢在声音前面结束。
    speaker = Speaker()
    text = prepare_speech(result["reply"])
    t0 = _time.perf_counter()
    speaker.backend.speak(text)
    stage("④", "说出来", f"{type(speaker.backend).__name__}：{text}", _time.perf_counter() - t0)

    print()
    print(f"✅ 全链路通了：{secs:.1f}s 的音频 → 听见名字 → 听懂 → 回答 → 说出声")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sammy", description="Sammy —— 桌面上的小家伙")
    parser.add_argument("--ask", metavar="TEXT", help="无界面测试大脑")
    parser.add_argument("--snapshot", metavar="PATH", help="渲染一张脸存成 PNG")
    parser.add_argument("--expr", type=int, default=3, help="快照用的表情编号")
    parser.add_argument("--reply", default="", help="快照里显示的回复文本")
    parser.add_argument("--voices", action="store_true", help="列出所有表情")
    parser.add_argument(
        "--selftest", metavar="PATH", help="真实显示窗口，2.5 秒后自检窗口状态并截图，然后退出"
    )
    parser.add_argument("--memory", action="store_true", help="看看 Sammy 记得什么")
    parser.add_argument("--models", action="store_true", help="看各档位模型配置状态")
    parser.add_argument("--drives", action="store_true", help="看它此刻的驱力（精力/无聊/亲近）")
    parser.add_argument(
        "--attention", action="store_true", help="看它此刻会不会先开口、卡在哪一条闸门"
    )
    parser.add_argument("--care", action="store_true", help="看休息提醒的计时状态")
    parser.add_argument("--say", metavar="TEXT", help="试听：把文本洗一遍再念出来")
    parser.add_argument("--voice-name", help="配合 --say 指定声音（默认 Tingting）")
    parser.add_argument("--wake", action="store_true", help="看唤醒词状态（模型、会认哪些说法）")
    parser.add_argument("--screens", action="store_true", help="列出所有屏幕，以及铺满后的结果")
    parser.add_argument("--ears", action="store_true", help="看耳朵状态（VAD / 语音识别模型）")
    parser.add_argument("--voice-demo", metavar="WAV", help="语音闭环演示：唤醒→听懂→回答→说出来")
    parser.add_argument("--kiosk", action="store_true", help="小屏模式：无边框铺满指定屏幕")
    parser.add_argument("--display", help="配合 --kiosk：屏幕序号或名字（不给就用记住的/主屏）")
    parser.add_argument("--silent", type=float, help="配合 --attention：假装已经安静多少分钟")
    parser.add_argument("--consolidate", action="store_true", help="立刻跑一次「夜里整理」")
    parser.add_argument("--day", help="配合 --consolidate 指定整理哪一天（YYYY-MM-DD）")
    parser.add_argument(
        "--history",
        nargs="?",
        type=int,
        const=20,
        metavar="N",
        help="看最近的对话记录（默认 20 条）",
    )
    parser.add_argument(
        "--clear-history", action="store_true", help="清空对话记录（**不动记忆** —— 那是另一件事）"
    )
    args = parser.parse_args(argv)

    if args.models:
        from .models import describe_all

        print(describe_all())
        return 0

    if args.drives:
        from .drives import Drives, status_text

        d = Drives.load().tick()
        print(json.dumps(d.snapshot(), ensure_ascii=False, indent=2))
        print(f"\n它现在的样子：{status_text(d)}")
        return 0

    if args.say:
        from .voice import default_backend, prepare_speech

        cleaned = prepare_speech(args.say)
        print(f"原话：{args.say!r}")
        print(f"念出来：{cleaned!r}")
        if not cleaned:
            print("（洗完之后没剩下能念的内容）")
            return 0
        # 必须走 default_backend()：否则 `SAMMY_TTS=edge` 这类开关在这条路径上不起作用，
        # 而 `--say` 正是用来试听、用来定声音的地方 —— 试听用的和后端用的不是同一个，
        # 那这个试听就是假的（实测踩过一次）。
        backend = default_backend()
        if args.voice_name:
            if hasattr(backend, "voice"):
                backend.voice = args.voice_name
            else:
                from .voice import MacSayBackend

                backend = MacSayBackend(voice=args.voice_name)
        print(f"声音：{getattr(backend, 'voice', type(backend).__name__)}")
        backend.speak(cleaned)
        print("念完了")
        return 0

    if args.care:
        from .care import ACTIVE_WINDOW_MINUTES, REMIND_AFTER_MINUTES, SNOOZE_MINUTES, Care

        c = Care.load()
        gate = c.due()
        print(f"你已经连续坐了：{c.session_minutes():.0f} 分钟")
        if c.snooze_until:
            import time as _t

            print(
                f"（你推后过，到 {_t.strftime('%H:%M', _t.localtime(c.snooze_until))} 为止不打扰）"
            )
        print(f"现在该不该提醒你：{'该' if gate.ok else '不该'}")
        print(f"  理由：{gate.reason}")
        print(
            f"\n参数：连续 {REMIND_AFTER_MINUTES} 分钟提醒 / "
            f"离开 {ACTIVE_WINDOW_MINUTES} 分钟算走开、重新计时 / 可推后 {SNOOZE_MINUTES} 分钟"
        )
        return 0

    if args.attention:
        import time

        from .attention import (
            MAX_PER_DAY,
            MIN_GAP_MINUTES,
            MIN_WANT,
            QUIET_END,
            QUIET_START,
            Attention,
        )
        from .attention import open_prompt as _op
        from .drives import Drives, status_text

        d = Drives.load().tick()
        a = Attention.load()
        silent = args.silent if args.silent is not None else 9999.0
        gate = a.decide(want_to_talk=d.want_to_talk, silent_minutes=silent)

        print(f"它现在的样子：{status_text(d)}")
        print(
            f"  精力 {d.energy:.2f} / 无聊 {d.boredom:.2f} / 亲近 {d.closeness:.2f}"
            f" → 想开口 {d.want_to_talk:.2f}"
        )
        print(f"\n现在会不会先开口：{'会' if gate.ok else '不会'}")
        print(f"  理由：{gate.reason}   ← **每次拒绝都能说出理由，才好调参**")
        last = (
            "从没开过口"
            if not a.last_spoke
            else time.strftime("%m-%d %H:%M", time.localtime(a.last_spoke))
        )
        print(f"\n今天额度：已用 {a.spoken_today}/{MAX_PER_DAY}；上次开口：{last}")
        print(
            f"闸门参数：免打扰 {QUIET_START}:00–{QUIET_END}:00 / 最小间隔 {MIN_GAP_MINUTES} 分钟"
            f" / 想开口门槛 {MIN_WANT}"
        )
        print(
            f"\n如果它现在开口，会拿到这个指令：\n  {_op(d.want_to_talk, d.closeness, d.boredom)}"
        )
        return 0

    if args.history is not None:
        from . import chatlog

        print(f"── 最近的对话记录 ──\n{chatlog.format_recent(args.history)}")
        return 0

    if args.clear_history:
        from . import chatlog

        n = chatlog.clear()
        print(f"  已清空对话记录：{n} 条")
        print("  （记忆没动 —— 槽位/日记在 sammy.db 里，那是 Sammy「记住的事」。）")
        return 0

    if args.memory:
        from .memory import Memory

        mem = Memory()
        st = mem.stats()
        slots = mem.slots()
        print(f"记忆库: {st['db']}")
        print(
            f"槽位 {st['slots']} 条 / 日记 {st['journal']} 条 / 摘要 {st['digests']} 篇"
            + (f" / 始于 {st['since']}" if st["since"] else "")
        )
        print()
        print("── 槽位（结构化事实）──")
        for k, v in slots.items():
            print(f"  {k}：{v}")
        if not slots:
            print("  （空）")
        print()
        print("── 最近三天 ──")
        rows = mem.recent(days=3)
        if rows:
            cur = ""
            for r in rows:
                if r["day"] != cur:
                    cur = r["day"]
                    print(f"  {cur}")
                mark = {"explicit": "★", "digest": "◈"}.get(r["kind"], "·")
                print(f"    {mark} {r['text']}")
        else:
            print("  （空）")
        return 0

    if args.consolidate:
        from .brain import SammyBrain
        from .memory import Memory, consolidate_now

        mem = Memory()
        info = consolidate_now(SammyBrain(), mem, args.day)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if args.voices:
        from .expressions import EXPR_EMOJI, EXPR_NAMES

        for i in sorted(EXPR_NAMES):
            print(f"{i:>3}  {EXPR_EMOJI[i]}  {EXPR_NAMES[i]}")
        return 0

    if args.ask:
        from .brain import SammyBrain

        try:
            brain = SammyBrain()
            result = brain.chat(args.ask)
        except RuntimeError as e:
            # PRD P0-1「断网给友好提示不崩」：别把 Python 回溯砸到用户脸上。
            print(f"😵 我连不上大模型：{e}")
            print("   检查一下网络，或用 ./run.sh --models 看凭证配置。")
            return 3
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.wake:
        from .wake import WakeWord

        print(WakeWord().load().describe())
        return 0

    if args.ears:
        from .ears import Ears

        print(Ears().describe())
        return 0

    if args.voice_demo:
        return voice_demo(args.voice_demo)

    if args.screens:
        from .faces import DEV_H, DEV_W
        from .screen import describe_screens

        print(describe_screens(DEV_W, DEV_H))
        return 0

    if args.snapshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from .pet import SammyWindow

    app = QApplication(sys.argv[:1])
    win = SammyWindow(kiosk=args.kiosk, display=args.display)
    if args.kiosk:
        from .screen import remember

        which = str(args.display) if args.display else str(win.target_screen["index"])
        remember(which)  # 选过一次就记住，下次不用再问
        f = win._kiosk_geom
        print(
            f"小屏模式：屏 [{win.target_screen['index']}] {win.target_screen['name']} "
            f"{win.target_screen['width']}×{win.target_screen['height']}"
            f" → 窗口 {f.width}×{f.height}（缩放 {f.scale:.2f}，居中留边 {f.x}/{f.y}）"
        )

    if args.snapshot:
        from .expressions import name_of

        win.set_expression(args.expr)
        win.reply = None  # 占位，避免误用
        win.sammy_line = args.reply or f"这是 {name_of(args.expr)} 的表情。"
        win.my_line = "今天好累啊，不想干活。"
        win.status = "在线 · 1.8s"
        win.update()
        app.processEvents()
        win.grab().save(args.snapshot)
        print(f"已保存: {args.snapshot}")
        return 0

    if args.kiosk:
        # 小屏模式：由窗管铺满**绑定的那块屏**。
        # 不用 show()+move()：多显示器下 move() 会被窗管摆走（实测被摆到屏外虚空）。
        win.showFullScreen()
    else:
        win.show()
    if args.selftest:
        return _selftest(app, win, args.selftest)
    return app.exec()


def _selftest(app, win, out_path: str) -> int:
    """真实显示窗口后自检 —— 证明「非离屏」这条路径真的能出窗口。"""
    from PySide6.QtCore import Qt, QTimer

    def inspect() -> None:
        win.poke()  # 顺带走一遍交互代码路径（戳一下 + 换表情）
        handle = win.windowHandle()
        screen = handle.screen() if handle else None
        flags = win.windowFlags()
        print("── 窗口自检 ──")
        print(f"  是否可见       : {win.isVisible()}")
        print(f"  窗口尺寸       : {win.width()}×{win.height()}")
        print(f"  屏幕位置       : ({win.x()}, {win.y()})")
        print(f"  所在显示器     : {screen.name() if screen else '?'}")
        print(f"  缩放比         : {win.devicePixelRatio()}")
        print(f"  无边框         : {bool(flags & Qt.FramelessWindowHint)}")
        print(f"  始终置顶       : {bool(flags & Qt.WindowStaysOnTopHint)}")
        print(f"  背景透明       : {win.testAttribute(Qt.WA_TranslucentBackground)}")
        print(f"  当前表情       : {win.expression}")
        win.grab().save(out_path)
        print(f"  截图已存       : {out_path}")
        app.quit()

    QTimer.singleShot(2500, inspect)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
