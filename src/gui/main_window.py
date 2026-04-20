"""Top-level application window."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.log_bus import get_handler, get_logger, install_qt_handler
from ..core.server_manager import ServerManager
from ..core.slave_config import SlaveConfig
from .global_config import GlobalConfigPanel, GlobalSettings
from .log_panel import LogPanel
from .slave_tab import SlaveTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Modbus Slave 模拟器")
        self.resize(1200, 800)

        install_qt_handler()
        self._log = get_logger(category="lifecycle")

        self._manager = ServerManager()
        self._manager.slave_started.connect(self._on_slave_started)
        self._manager.slave_failed.connect(self._on_slave_failed)
        self._manager.slave_stopped.connect(self._on_slave_stopped)
        self._manager.all_stopped.connect(self._on_all_stopped)

        self._global_panel = GlobalConfigPanel()
        self._global_panel.applyRequested.connect(self._on_apply_settings)
        self._global_panel.startRequested.connect(self._on_start)
        self._global_panel.stopRequested.connect(self._on_stop)

        self._slave_tabs = QTabWidget()
        self._slave_tabs.setTabsClosable(False)

        self._log_panel = LogPanel()
        handler = get_handler()
        handler.record_emitted.connect(
            self._log_panel.append_record, Qt.QueuedConnection
        )

        # -- layout -----------------------------------------------------

        top_splitter = QSplitter(Qt.Horizontal)
        left_wrap = QWidget()
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._global_panel)
        left_wrap.setMinimumWidth(320)
        top_splitter.addWidget(left_wrap)
        top_splitter.addWidget(self._slave_tabs)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([340, 860])

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self._log_panel)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([520, 280])

        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        QTimer.singleShot(0, self._initial_apply)

    # -- settings & tab management -----------------------------------------

    def _initial_apply(self) -> None:
        self._apply_settings(self._global_panel.snapshot())

    @Slot(object)
    def _on_apply_settings(self, settings: GlobalSettings) -> None:
        if self._manager.running:
            QMessageBox.warning(self, "运行中", "请先停止所有 slave 再修改配置")
            return
        self._apply_settings(settings)
        self._log.info(
            "applied settings: framer=%s base_port=%d count=%d",
            settings.framer_mode.display_name,
            settings.base_port,
            settings.slave_count,
        )

    def _apply_settings(self, settings: GlobalSettings) -> None:
        existing_tabs: List[SlaveTab] = [
            self._slave_tabs.widget(i) for i in range(self._slave_tabs.count())
        ]  # type: ignore[assignment]
        while self._slave_tabs.count() > settings.slave_count:
            self._slave_tabs.removeTab(self._slave_tabs.count() - 1)

        for idx in range(settings.slave_count):
            port = settings.base_port + idx
            if idx < len(existing_tabs):
                tab = existing_tabs[idx]
                tab.set_port(port)
            else:
                cfg = SlaveConfig(
                    unit_id=1,
                    port=port,
                    coil_count=settings.default_coil_count,
                    discrete_count=settings.default_discrete_count,
                    input_count=settings.default_input_count,
                    holding_count=settings.default_holding_count,
                    delay_ms=settings.default_delay_ms,
                )
                cfg.ensure_values()
                tab = SlaveTab(cfg)
                tab.liveEditRequested.connect(self._on_live_edit)
                self._slave_tabs.addTab(tab, f"Slave {idx + 1}")

        for idx in range(self._slave_tabs.count()):
            self._slave_tabs.setTabText(idx, f"Slave {idx + 1}")

    # -- start / stop ------------------------------------------------------

    def _collect_configs(self) -> List[SlaveConfig]:
        configs: List[SlaveConfig] = []
        for idx in range(self._slave_tabs.count()):
            tab: SlaveTab = self._slave_tabs.widget(idx)  # type: ignore[assignment]
            configs.append(tab.config)
        return configs

    @Slot()
    def _on_start(self) -> None:
        configs = self._collect_configs()
        if not configs:
            QMessageBox.warning(self, "提示", "请先配置至少一个 slave")
            return
        settings = self._global_panel.snapshot()
        self._global_panel.set_running(True)
        for idx in range(self._slave_tabs.count()):
            tab: SlaveTab = self._slave_tabs.widget(idx)  # type: ignore[assignment]
            tab.set_running(True)
        self.statusBar().showMessage("正在启动...")
        self._manager.start_all(configs, settings.framer_mode)
        if self._manager.running:
            self.statusBar().showMessage("运行中")
        else:
            self.statusBar().showMessage("启动失败")
            self._global_panel.set_running(False)
            for idx in range(self._slave_tabs.count()):
                tab: SlaveTab = self._slave_tabs.widget(idx)  # type: ignore[assignment]
                tab.set_running(False)

    @Slot()
    def _on_stop(self) -> None:
        self.statusBar().showMessage("正在停止...")
        self._manager.stop_all()

    # -- manager events ----------------------------------------------------

    @Slot(int, int)
    def _on_slave_started(self, unit_id: int, port: int) -> None:
        self.statusBar().showMessage(f"slave {unit_id}@{port} 已启动")

    @Slot(int, int, str)
    def _on_slave_failed(self, unit_id: int, port: int, reason: str) -> None:
        self.statusBar().showMessage(f"slave {unit_id}@{port} 启动失败: {reason}")

    @Slot(int, int)
    def _on_slave_stopped(self, unit_id: int, port: int) -> None:
        self.statusBar().showMessage(f"slave {unit_id}@{port} 已停止")

    @Slot(int, int, object, int, int)
    def _on_live_edit(
        self, unit_id: int, port: int, register_type, address: int, value: int
    ) -> None:
        if not self._manager.running:
            return
        self._manager.write_value(port, register_type, address, value)

    @Slot()
    def _on_all_stopped(self) -> None:
        self._global_panel.set_running(False)
        for idx in range(self._slave_tabs.count()):
            tab: SlaveTab = self._slave_tabs.widget(idx)  # type: ignore[assignment]
            tab.set_running(False)
        self.statusBar().showMessage("已全部停止")

    # -- close -------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._manager.running:
            self._manager.stop_all()
        super().closeEvent(event)
