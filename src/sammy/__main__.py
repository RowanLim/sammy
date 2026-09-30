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
    parser.add_argument("--consolidate", action="store_true", help="立刻跑一次「夜里整理」")
    parser.add_argument("--day", help="配合 --consolidate 指定整理哪一天（YYYY-MM-DD）")
    args = parser.parse_args(argv)

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

        brain = SammyBrain()
        result = brain.chat(args.ask)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.snapshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from .pet import SammyWindow

    app = QApplication(sys.argv[:1])
    win = SammyWindow()

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
