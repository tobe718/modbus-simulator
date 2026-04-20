"""DataBlock subclass that injects a configurable delay and logs access.

We subclass :class:`pymodbus.datastore.ModbusSequentialDataBlock` so that both
read (``getValues``) and write (``setValues``) paths trigger the configured
response delay for the owning slave and emit structured log records.
"""
from __future__ import annotations

import time
from typing import List, Optional

from pymodbus.datastore import ModbusSequentialDataBlock

from .log_bus import get_logger
from .slave_config import RegisterType


class DelayedDataBlock(ModbusSequentialDataBlock):
    """A data block that sleeps ``delay_ms`` milliseconds on every access."""

    def __init__(
        self,
        address: int,
        values: List[int],
        *,
        slave_id: int,
        port: int,
        register_type: RegisterType,
        delay_provider,
    ) -> None:
        super().__init__(address, values)
        self._slave_id = slave_id
        self._port = port
        self._register_type = register_type
        self._delay_provider = delay_provider  # callable returning current delay ms
        self._log = get_logger(slave_id=slave_id, port=port, category="request")

    def _sleep(self) -> None:
        try:
            delay_ms = int(self._delay_provider())
        except Exception:
            delay_ms = 0
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    def getValues(self, address: int, count: int = 1):  # type: ignore[override]
        self._log.debug(
            "read %s addr=%d count=%d",
            self._register_type.value,
            address,
            count,
            extra={"category": "request"},
        )
        try:
            values = super().getValues(address, count)
        except Exception as exc:
            self._log.warning(
                "read %s addr=%d count=%d failed: %s",
                self._register_type.value,
                address,
                count,
                exc,
                extra={"category": "error"},
            )
            raise
        self._sleep()
        self._log.debug(
            "resp %s addr=%d values=%s",
            self._register_type.value,
            address,
            _preview(values),
            extra={"category": "response"},
        )
        return values

    def setValues_internal(self, address: int, values) -> None:
        """Write values without triggering the configured response delay.

        Intended for GUI-driven live edits, where blocking the UI thread by
        ``time.sleep(delay_ms)`` would freeze the app. Still logs the write.
        """
        if not isinstance(values, list):
            values = [values]
        self._log.info(
            "gui-edit %s addr=%d values=%s",
            self._register_type.value,
            address,
            _preview(values),
            extra={"category": "request"},
        )
        super().setValues(address, values)

    def setValues(self, address: int, values) -> None:  # type: ignore[override]
        if not isinstance(values, list):
            values = [values]
        self._log.debug(
            "write %s addr=%d values=%s",
            self._register_type.value,
            address,
            _preview(values),
            extra={"category": "request"},
        )
        try:
            super().setValues(address, values)
        except Exception as exc:
            self._log.warning(
                "write %s addr=%d failed: %s",
                self._register_type.value,
                address,
                exc,
                extra={"category": "error"},
            )
            raise
        self._sleep()
        self._log.debug(
            "ack %s addr=%d count=%d",
            self._register_type.value,
            address,
            len(values),
            extra={"category": "response"},
        )


def _preview(values, limit: int = 16) -> str:
    values = list(values)
    if len(values) <= limit:
        return str(values)
    head = ", ".join(str(v) for v in values[:limit])
    return f"[{head}, ... ({len(values)} total)]"
