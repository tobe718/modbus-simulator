"""Global configuration panel (top-left of the main window)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.slave_config import FramerMode


@dataclass
class GlobalSettings:
    framer_mode: FramerMode = FramerMode.TCP
    base_port: int = 5020
    slave_count: int = 1
    default_coil_count: int = 100
    default_discrete_count: int = 100
    default_input_count: int = 100
    default_holding_count: int = 100
    default_delay_ms: int = 0


class GlobalConfigPanel(QWidget):
    """Panel with all global knobs."""

    applyRequested = Signal(object)       # emits GlobalSettings snapshot
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = GlobalSettings()
        self._running = False

        # -- framer mode
        framer_box = QGroupBox("协议帧格式")
        self._tcp_radio = QRadioButton("Modbus TCP")
        self._rtu_radio = QRadioButton("Modbus RTU over TCP")
        self._tcp_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self._tcp_radio)
        group.addButton(self._rtu_radio)
        framer_layout = QVBoxLayout(framer_box)
        framer_layout.addWidget(self._tcp_radio)
        framer_layout.addWidget(self._rtu_radio)

        # -- network
        net_box = QGroupBox("网络 / Slave 数量")
        self._base_port = QSpinBox()
        self._base_port.setRange(1, 65535)
        self._base_port.setValue(self._settings.base_port)

        self._slave_count = QSpinBox()
        self._slave_count.setRange(1, 250)
        self._slave_count.setValue(self._settings.slave_count)

        net_form = QFormLayout(net_box)
        net_form.addRow("起始端口 (offset):", self._base_port)
        net_form.addRow("Slave 数量:", self._slave_count)
        net_form.addRow(QLabel("每个 slave 依次监听 offset, offset+1, ..."))

        # -- defaults
        defaults_box = QGroupBox("默认寄存器与延迟")
        self._coil_count = QSpinBox()
        self._discrete_count = QSpinBox()
        self._input_count = QSpinBox()
        self._holding_count = QSpinBox()
        for sp, val in (
            (self._coil_count, self._settings.default_coil_count),
            (self._discrete_count, self._settings.default_discrete_count),
            (self._input_count, self._settings.default_input_count),
            (self._holding_count, self._settings.default_holding_count),
        ):
            sp.setRange(0, 65535)
            sp.setValue(val)

        self._delay = QSpinBox()
        self._delay.setRange(0, 60_000)
        self._delay.setSuffix(" ms")
        self._delay.setValue(self._settings.default_delay_ms)

        defaults_form = QFormLayout(defaults_box)
        defaults_form.addRow("Coils (0xxxx):", self._coil_count)
        defaults_form.addRow("Discrete (1xxxx):", self._discrete_count)
        defaults_form.addRow("Input (3xxxx):", self._input_count)
        defaults_form.addRow("Holding (4xxxx):", self._holding_count)
        defaults_form.addRow("响应延迟:", self._delay)

        # -- actions
        self._apply_btn = QPushButton("应用配置")
        self._apply_btn.clicked.connect(self._on_apply)
        self._start_btn = QPushButton("启动全部")
        self._start_btn.clicked.connect(self.startRequested)
        self._stop_btn = QPushButton("停止全部")
        self._stop_btn.clicked.connect(self.stopRequested)
        self._stop_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(framer_box)
        layout.addWidget(net_box)
        layout.addWidget(defaults_box)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    # -- public ------------------------------------------------------------

    def snapshot(self) -> GlobalSettings:
        return GlobalSettings(
            framer_mode=(
                FramerMode.TCP if self._tcp_radio.isChecked() else FramerMode.RTU_OVER_TCP
            ),
            base_port=self._base_port.value(),
            slave_count=self._slave_count.value(),
            default_coil_count=self._coil_count.value(),
            default_discrete_count=self._discrete_count.value(),
            default_input_count=self._input_count.value(),
            default_holding_count=self._holding_count.value(),
            default_delay_ms=self._delay.value(),
        )

    def set_running(self, running: bool) -> None:
        self._running = running
        for w in (
            self._tcp_radio,
            self._rtu_radio,
            self._base_port,
            self._slave_count,
            self._coil_count,
            self._discrete_count,
            self._input_count,
            self._holding_count,
            self._delay,
            self._apply_btn,
            self._start_btn,
        ):
            w.setEnabled(not running)
        self._stop_btn.setEnabled(running)

    # -- events ------------------------------------------------------------

    def _on_apply(self) -> None:
        self.applyRequested.emit(self.snapshot())
