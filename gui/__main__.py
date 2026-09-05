"""Launch the GUI: ``python -m gui`` from the repo root.

Requires PySide6 (see requirements.txt). The generator core stays stdlib-only; only this
gui/ package imports Qt.
"""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PySide6 is not installed. Install the GUI dependency with:\n"
            "  .venv/Scripts/python -m pip install -r requirements.txt\n")
        return 1

    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
