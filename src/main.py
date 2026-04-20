"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .core.log_bus import install_qt_handler
from .gui.main_window import MainWindow


def main() -> int:
    install_qt_handler()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
