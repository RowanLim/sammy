"""打包入口 —— PyInstaller 需要一个脚本文件，而开发时用的是 `python -m sammy`。

这个文件**只做一件事**：把 `python -m sammy` 的行为原样搬过来。
刻意不在这里加任何逻辑 —— 打包入口一旦和开发入口有分叉，
就会出现最恶心的那类 bug：「开发时好好的，双击就坏」。
"""

import sys

from sammy.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
