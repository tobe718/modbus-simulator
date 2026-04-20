"""Central logging bus bridging Python logging to Qt signals.

Every log record carries structured context (slave_id, port, category) that the
GUI can use for filtering and coloring. Thread-safe: the Qt Signal queues
records to the GUI thread automatically.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal


LOGGER_NAME = "modbus_simulator"


@dataclass
class LogRecord:
    """Structured log record delivered to the GUI."""

    timestamp: float
    level: int
    level_name: str
    message: str
    slave_id: Optional[int]
    port: Optional[int]
    category: str  # lifecycle | request | response | error | general

    @property
    def formatted_time(self) -> str:
        lt = time.localtime(self.timestamp)
        ms = int((self.timestamp - int(self.timestamp)) * 1000)
        return f"{time.strftime('%H:%M:%S', lt)}.{ms:03d}"

    def format_line(self) -> str:
        ctx = []
        if self.slave_id is not None:
            ctx.append(f"slave={self.slave_id}")
        if self.port is not None:
            ctx.append(f"port={self.port}")
        ctx_str = f"[{' '.join(ctx)}]" if ctx else ""
        return (
            f"[{self.formatted_time}] [{self.level_name:<5}] "
            f"{ctx_str} [{self.category}] {self.message}"
        )


class QtLogHandler(QObject, logging.Handler):
    """Logging handler that emits records via a Qt Signal."""

    record_emitted = Signal(object)  # emits LogRecord

    def __init__(self) -> None:
        QObject.__init__(self)
        logging.Handler.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            slave_id = getattr(record, "slave_id", None)
            port = getattr(record, "port", None)
            category = getattr(record, "category", "general")
            msg = record.getMessage()
            if record.exc_info:
                msg = f"{msg}\n{self.format(record)}"
            payload = LogRecord(
                timestamp=record.created,
                level=record.levelno,
                level_name=record.levelname,
                message=msg,
                slave_id=slave_id,
                port=port,
                category=category,
            )
            self.record_emitted.emit(payload)
        except Exception:  # pragma: no cover - never let logging crash the app
            self.handleError(record)


_handler: Optional[QtLogHandler] = None


def install_qt_handler() -> QtLogHandler:
    """Install a single QtLogHandler on the application logger tree."""
    global _handler
    if _handler is not None:
        return _handler

    handler = QtLogHandler()
    handler.setLevel(logging.DEBUG)

    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG)
    app_logger.addHandler(handler)
    app_logger.propagate = False

    pm_logger = logging.getLogger("pymodbus")
    pm_logger.setLevel(logging.INFO)
    pm_logger.addHandler(handler)

    _handler = handler
    return handler


def get_handler() -> QtLogHandler:
    if _handler is None:
        return install_qt_handler()
    return _handler


def get_logger(
    slave_id: Optional[int] = None,
    port: Optional[int] = None,
    category: str = "general",
) -> logging.LoggerAdapter:
    """Return a LoggerAdapter injecting slave context into every record."""
    base = logging.getLogger(LOGGER_NAME)
    return _ContextAdapter(
        base,
        {"slave_id": slave_id, "port": port, "category": category},
    )


class _ContextAdapter(logging.LoggerAdapter):
    """LoggerAdapter that forwards context through record.extra.

    Allows per-call override of category: ``log.info("...", extra={"category": "request"})``.
    """

    def process(self, msg, kwargs):
        extra = dict(self.extra or {})
        caller_extra = kwargs.get("extra")
        if caller_extra:
            extra.update(caller_extra)
        kwargs["extra"] = extra
        return msg, kwargs
