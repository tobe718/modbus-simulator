"""Log display panel with level / slave filtering, coloring and export."""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Optional, Set, Tuple

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.log_bus import LogRecord


LEVEL_OPTIONS = [
    ("ALL", logging.DEBUG),
    ("DEBUG", logging.DEBUG),
    ("INFO", logging.INFO),
    ("WARNING", logging.WARNING),
    ("ERROR", logging.ERROR),
]

LEVEL_COLORS = {
    logging.DEBUG: QColor("#808080"),
    logging.INFO: QColor("#d4d4d4"),
    logging.WARNING: QColor("#e0a030"),
    logging.ERROR: QColor("#e04040"),
}

MAX_BUFFER = 5000


class LogPanel(QWidget):
    """A QPlainTextEdit-backed log viewer with filtering."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._buffer: Deque[LogRecord] = deque(maxlen=MAX_BUFFER)
        self._min_level = logging.DEBUG
        self._slave_filter: Optional[Tuple[int, int]] = None  # (unit_id, port)
        self._known_slaves: Set[Tuple[int, int]] = set()

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_BUFFER)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self._view.setFont(font)

        self._level_combo = QComboBox()
        for name, _ in LEVEL_OPTIONS:
            self._level_combo.addItem(name)
        self._level_combo.setCurrentText("ALL")
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)

        self._slave_combo = QComboBox()
        self._slave_combo.addItem("ALL", userData=None)
        self._slave_combo.currentIndexChanged.connect(self._on_slave_changed)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.clear)
        export_btn = QPushButton("导出...")
        export_btn.clicked.connect(self._on_export)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("等级:"))
        toolbar.addWidget(self._level_combo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Slave:"))
        toolbar.addWidget(self._slave_combo)
        toolbar.addStretch(1)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(export_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self._view)

    # -- public ------------------------------------------------------------

    @Slot(object)
    def append_record(self, record: LogRecord) -> None:
        self._buffer.append(record)
        self._register_slave(record)
        if self._passes_filter(record):
            self._render(record)

    def clear(self) -> None:
        self._buffer.clear()
        self._view.clear()

    # -- filtering ---------------------------------------------------------

    def _on_level_changed(self, _idx: int) -> None:
        name = self._level_combo.currentText()
        self._min_level = dict(LEVEL_OPTIONS)[name]
        self._rerender()

    def _on_slave_changed(self, _idx: int) -> None:
        data = self._slave_combo.currentData()
        self._slave_filter = data
        self._rerender()

    def _passes_filter(self, record: LogRecord) -> bool:
        if record.level < self._min_level:
            return False
        if self._slave_filter is not None:
            if record.slave_id is None or record.port is None:
                return False
            if (record.slave_id, record.port) != self._slave_filter:
                return False
        return True

    def _register_slave(self, record: LogRecord) -> None:
        if record.slave_id is None or record.port is None:
            return
        key = (record.slave_id, record.port)
        if key in self._known_slaves:
            return
        self._known_slaves.add(key)
        self._slave_combo.addItem(f"unit={key[0]} @ :{key[1]}", userData=key)

    def _rerender(self) -> None:
        self._view.clear()
        for record in self._buffer:
            if self._passes_filter(record):
                self._render(record)

    def _render(self, record: LogRecord) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(LEVEL_COLORS.get(record.level, QColor("#d4d4d4")))
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(record.format_line() + "\n", fmt)
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

    # -- export ------------------------------------------------------------

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            "modbus-simulator.log",
            "Log files (*.log);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for record in self._buffer:
                    fh.write(record.format_line() + "\n")
        except OSError as exc:
            from ..core.log_bus import get_logger

            get_logger(category="error").error("failed to export log: %s", exc)
