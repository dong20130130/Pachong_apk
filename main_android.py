"""Android 应用入口（buildozer 的 entrypoint）。

与桌面版 main.py 的区别：调用 Kivy 版的 GUI，不再依赖 tkinter。
崩溃时把堆栈写入 crash.log（位于应用私有目录），便于排查。
"""
import sys
import traceback


def _run():
    from crawler_app.gui_kivy import main
    return main()


if __name__ == "__main__":
    try:
        sys.exit(_run())
    except Exception:
        tb = traceback.format_exc()
        try:
            with open("crash.log", "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        sys.exit(1)
