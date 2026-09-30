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
    args = parser.parse_args(argv)

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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
