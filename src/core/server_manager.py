"""Manages lifetime of multiple Modbus TCP slaves, one per thread.

Each slave runs its own :mod:`asyncio` event loop inside a dedicated thread.
This keeps per-slave request delay (``time.sleep``) from blocking other slaves
and avoids interleaving of pymodbus internals across loops.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext

from .delayed_datastore import DelayedDataBlock
from .log_bus import get_logger
from .slave_config import FramerMode, RegisterType, SlaveConfig


# Map RegisterType -> ModbusSlaveContext attribute used by pymodbus
_REGISTER_KIND = {
    RegisterType.COIL: "co",
    RegisterType.DISCRETE: "di",
    RegisterType.INPUT: "ir",
    RegisterType.HOLDING: "hr",
}


# -- pymodbus version compatibility ------------------------------------------------

def _resolve_framer(mode: FramerMode):
    """Return a framer argument accepted by ModbusTcpServer for this pymodbus."""
    try:
        from pymodbus.framer import FramerType  # pymodbus >= 3.7
        return FramerType.SOCKET if mode == FramerMode.TCP else FramerType.RTU
    except Exception:
        pass
    try:
        from pymodbus.transaction import (  # pymodbus 3.6.x
            ModbusRtuFramer,
            ModbusSocketFramer,
        )
        return ModbusSocketFramer if mode == FramerMode.TCP else ModbusRtuFramer
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Unable to locate Modbus framer classes in pymodbus"
        ) from exc


def _import_tcp_server_cls():
    from pymodbus.server import ModbusTcpServer  # present in 3.6+
    return ModbusTcpServer


# -- Runtime state -----------------------------------------------------------------

@dataclass
class _SlaveRuntime:
    config: SlaveConfig
    thread: threading.Thread
    loop: Optional[asyncio.AbstractEventLoop] = None
    server: object = None
    ready: threading.Event = None
    started_ok: bool = False
    error: Optional[BaseException] = None
    blocks: Dict[RegisterType, DelayedDataBlock] = None  # type: ignore[assignment]


class ServerManager(QObject):
    """Starts, tracks and stops Modbus TCP slaves."""

    slave_started = Signal(int, int)   # unit_id, port
    slave_stopped = Signal(int, int)
    slave_failed = Signal(int, int, str)
    all_stopped = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._runtimes: Dict[int, _SlaveRuntime] = {}
        self._log = get_logger(category="lifecycle")
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    # ---------------------------------------------------------------- public API

    def start_all(self, configs: List[SlaveConfig], framer_mode: FramerMode) -> None:
        if self._running:
            self._log.warning("start_all called but servers are already running")
            return
        if not configs:
            self._log.warning("no slaves configured; nothing to start")
            return

        self._runtimes.clear()
        for cfg in configs:
            cfg.ensure_values()
            ready = threading.Event()
            runtime = _SlaveRuntime(config=cfg, thread=None, ready=ready)  # type: ignore[arg-type]
            thread = threading.Thread(
                target=self._thread_main,
                args=(runtime, framer_mode),
                name=f"modbus-slave-{cfg.unit_id}@{cfg.port}",
                daemon=True,
            )
            runtime.thread = thread
            self._runtimes[cfg.port] = runtime
            thread.start()

        for runtime in self._runtimes.values():
            assert runtime.ready is not None
            runtime.ready.wait(timeout=5.0)
            cfg = runtime.config
            if runtime.started_ok:
                self.slave_started.emit(cfg.unit_id, cfg.port)
            else:
                err = str(runtime.error) if runtime.error else "unknown error"
                self.slave_failed.emit(cfg.unit_id, cfg.port, err)

        self._running = any(r.started_ok for r in self._runtimes.values())

    def write_value(
        self,
        port: int,
        register_type: RegisterType,
        address: int,
        value: int,
    ) -> bool:
        """Update a single register on a running slave (no delay, UI-safe).

        Returns True if the runtime was found and the write was dispatched.
        """
        runtime = self._runtimes.get(port)
        if runtime is None or not runtime.started_ok or not runtime.blocks:
            return False
        block = runtime.blocks.get(register_type)
        if block is None:
            return False
        try:
            block.setValues_internal(address, [value])
            return True
        except Exception as exc:
            log = get_logger(
                slave_id=runtime.config.unit_id,
                port=port,
                category="error",
            )
            log.warning("gui write failed: %s", exc)
            return False

    def stop_all(self) -> None:
        if not self._runtimes:
            return

        for runtime in list(self._runtimes.values()):
            self._shutdown_runtime(runtime)

        for runtime in list(self._runtimes.values()):
            if runtime.thread.is_alive():
                runtime.thread.join(timeout=5.0)
            cfg = runtime.config
            self.slave_stopped.emit(cfg.unit_id, cfg.port)

        self._runtimes.clear()
        self._running = False
        self.all_stopped.emit()

    # ---------------------------------------------------------------- internals

    def _shutdown_runtime(self, runtime: _SlaveRuntime) -> None:
        cfg = runtime.config
        log = get_logger(slave_id=cfg.unit_id, port=cfg.port, category="lifecycle")
        server = runtime.server
        loop = runtime.loop
        if server is None or loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(server.shutdown(), loop)
            future.result(timeout=5.0)
        except Exception as exc:
            log.error("error while shutting down: %s", exc, extra={"category": "error"})

    def _thread_main(self, runtime: _SlaveRuntime, framer_mode: FramerMode) -> None:
        cfg = runtime.config
        log = get_logger(slave_id=cfg.unit_id, port=cfg.port, category="lifecycle")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runtime.loop = loop

        try:
            server, blocks = loop.run_until_complete(
                self._build_server(cfg, framer_mode)
            )
            runtime.server = server
            runtime.blocks = blocks
            runtime.started_ok = True
            log.info(
                "slave started on 0.0.0.0:%d (unit=%d, framer=%s)",
                cfg.port,
                cfg.unit_id,
                framer_mode.display_name,
            )
        except Exception as exc:
            runtime.error = exc
            runtime.started_ok = False
            log.error(
                "failed to start slave: %s", exc, extra={"category": "error"}
            )
            runtime.ready.set()
            try:
                loop.close()
            finally:
                return

        runtime.ready.set()

        try:
            loop.run_until_complete(runtime.server.serve_forever())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.error("server crashed: %s", exc, extra={"category": "error"})
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            log.info("slave stopped")

    async def _build_server(self, cfg: SlaveConfig, framer_mode: FramerMode):
        context, blocks = _build_slave_context(cfg)
        server_context = ModbusServerContext(slaves={cfg.unit_id: context}, single=False)
        framer = _resolve_framer(framer_mode)
        ServerCls = _import_tcp_server_cls()
        server = ServerCls(
            context=server_context,
            framer=framer,
            address=("0.0.0.0", cfg.port),
        )
        return server, blocks


def _build_slave_context(
    cfg: SlaveConfig,
) -> Tuple[ModbusSlaveContext, Dict[RegisterType, DelayedDataBlock]]:
    """Create a pymodbus slave context wired with DelayedDataBlocks.

    Also returns the block mapping so callers can push live edits straight into
    the running datastore.
    """
    cfg.ensure_values()

    def delay_provider() -> int:
        return cfg.delay_ms

    co = DelayedDataBlock(
        0, list(cfg.coil_values),
        slave_id=cfg.unit_id, port=cfg.port,
        register_type=RegisterType.COIL, delay_provider=delay_provider,
    )
    di = DelayedDataBlock(
        0, list(cfg.discrete_values),
        slave_id=cfg.unit_id, port=cfg.port,
        register_type=RegisterType.DISCRETE, delay_provider=delay_provider,
    )
    ir = DelayedDataBlock(
        0, list(cfg.input_values),
        slave_id=cfg.unit_id, port=cfg.port,
        register_type=RegisterType.INPUT, delay_provider=delay_provider,
    )
    hr = DelayedDataBlock(
        0, list(cfg.holding_values),
        slave_id=cfg.unit_id, port=cfg.port,
        register_type=RegisterType.HOLDING, delay_provider=delay_provider,
    )
    context = ModbusSlaveContext(di=di, co=co, hr=hr, ir=ir, zero_mode=True)
    blocks = {
        RegisterType.COIL: co,
        RegisterType.DISCRETE: di,
        RegisterType.INPUT: ir,
        RegisterType.HOLDING: hr,
    }
    return context, blocks
