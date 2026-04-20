"""Per-slave configuration tab."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.slave_config import RegisterType, SlaveConfig


class _RegisterTable(QWidget):
    """A table widget bound to a register list for a specific type."""

    valuesChanged = Signal()
    cellEdited = Signal(int, int)  # zero-based address, new value

    def __init__(
        self,
        register_type: RegisterType,
        values: List[int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._register_type = register_type
        self._values: List[int] = list(values)
        self._suspend_signal = False

        self._table = QTableWidget(0, 2, self)
        self._table.setHorizontalHeaderLabels(["Address", "Value"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self._table.itemChanged.connect(self._on_item_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

        self.set_values(values)

    @property
    def register_type(self) -> RegisterType:
        return self._register_type

    @property
    def values(self) -> List[int]:
        return list(self._values)

    def set_values(self, values: List[int]) -> None:
        self._values = list(values)
        self._suspend_signal = True
        try:
            self._table.setRowCount(len(self._values))
            address_base = _address_base(self._register_type)
            for row, value in enumerate(self._values):
                addr_item = QTableWidgetItem(str(address_base + row))
                addr_item.setFlags(addr_item.flags() & ~Qt.ItemIsEditable)
                addr_item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(row, 0, addr_item)

                val_item = QTableWidgetItem(str(value))
                val_item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(row, 1, val_item)
        finally:
            self._suspend_signal = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suspend_signal or item.column() != 1:
            return
        row = item.row()
        text = item.text().strip()
        try:
            parsed = int(text, 0) if text else 0
        except ValueError:
            parsed = 0
        if self._register_type in (RegisterType.COIL, RegisterType.DISCRETE):
            parsed = 1 if parsed else 0
        parsed = max(0, min(parsed, 0xFFFF))
        self._suspend_signal = True
        try:
            item.setText(str(parsed))
        finally:
            self._suspend_signal = False
        if 0 <= row < len(self._values):
            self._values[row] = parsed
            self.valuesChanged.emit()
            self.cellEdited.emit(row, parsed)


def _address_base(rt: RegisterType) -> int:
    return {
        RegisterType.COIL: 1,
        RegisterType.DISCRETE: 10001,
        RegisterType.INPUT: 30001,
        RegisterType.HOLDING: 40001,
    }[rt]


class SlaveTab(QWidget):
    """Widget that shows and edits a single :class:`SlaveConfig`."""

    configChanged = Signal()
    # Emitted when the user edits a single register value: (unit_id, port,
    # register_type, zero-based address, new value). Used by MainWindow to push
    # the change into a running slave's datastore without re-starting it.
    liveEditRequested = Signal(int, int, object, int, int)

    def __init__(self, config: SlaveConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._config.ensure_values()

        self._unit_spin = QSpinBox()
        self._unit_spin.setRange(1, 247)
        self._unit_spin.setValue(config.unit_id)
        self._unit_spin.valueChanged.connect(self._on_unit_changed)

        self._port_label = QLabel(str(config.port))
        self._port_label.setStyleSheet("font-weight: bold;")

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 60_000)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.setValue(config.delay_ms)
        self._delay_spin.valueChanged.connect(self._on_delay_changed)

        count_layout = QHBoxLayout()
        self._count_spins = {}
        for rt, label in [
            (RegisterType.COIL, "Coils"),
            (RegisterType.DISCRETE, "Discrete"),
            (RegisterType.INPUT, "Input"),
            (RegisterType.HOLDING, "Holding"),
        ]:
            spin = QSpinBox()
            spin.setRange(0, 65535)
            spin.setValue(_count_for(config, rt))
            spin.valueChanged.connect(
                lambda v, r=rt: self._on_count_changed(r, v)
            )
            self._count_spins[rt] = spin
            count_layout.addWidget(QLabel(f"{label}:"))
            count_layout.addWidget(spin)
            count_layout.addSpacing(8)
        count_layout.addStretch(1)

        form = QFormLayout()
        form.addRow("Unit ID:", self._unit_spin)
        form.addRow("监听端口:", self._port_label)
        form.addRow("响应延迟:", self._delay_spin)

        header = QGroupBox("基本信息")
        header_layout = QVBoxLayout(header)
        header_layout.addLayout(form)
        header_layout.addWidget(QLabel("寄存器数量:"))
        header_layout.addLayout(count_layout)

        self._tables = {
            rt: _RegisterTable(rt, _values_for(config, rt))
            for rt in RegisterType
        }
        for rt, table in self._tables.items():
            table.valuesChanged.connect(
                lambda r=rt: self._on_values_changed(r)
            )
            table.cellEdited.connect(
                lambda addr, val, r=rt: self._on_cell_edited(r, addr, val)
            )

        self._tabs = QTabWidget()
        for rt in (
            RegisterType.COIL,
            RegisterType.DISCRETE,
            RegisterType.INPUT,
            RegisterType.HOLDING,
        ):
            self._tabs.addTab(self._tables[rt], rt.display_name)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self._tabs, 1)

    # -- public ------------------------------------------------------------

    @property
    def config(self) -> SlaveConfig:
        return self._config

    def set_port(self, port: int) -> None:
        self._config.port = port
        self._port_label.setText(str(port))

    def set_running(self, running: bool) -> None:
        # Changing unit id or register counts requires rebuilding the
        # datastore, so those are locked while the slave is running.
        self._unit_spin.setEnabled(not running)
        for spin in self._count_spins.values():
            spin.setEnabled(not running)
        # Register value tables and the delay spin stay interactive so the
        # user can keep editing live values while the slave is serving
        # requests.

    # -- handlers ----------------------------------------------------------

    def _on_unit_changed(self, value: int) -> None:
        self._config.unit_id = value
        self.configChanged.emit()

    def _on_delay_changed(self, value: int) -> None:
        self._config.delay_ms = value
        self.configChanged.emit()

    def _on_count_changed(self, rt: RegisterType, value: int) -> None:
        _set_count(self._config, rt, value)
        self._config.ensure_values()
        self._tables[rt].set_values(_values_for(self._config, rt))
        self.configChanged.emit()

    def _on_values_changed(self, rt: RegisterType) -> None:
        _set_values(self._config, rt, self._tables[rt].values)
        self.configChanged.emit()

    def _on_cell_edited(self, rt: RegisterType, address: int, value: int) -> None:
        self.liveEditRequested.emit(
            self._config.unit_id, self._config.port, rt, address, value
        )


# -- helpers to map RegisterType <-> SlaveConfig fields --------------------

def _count_for(cfg: SlaveConfig, rt: RegisterType) -> int:
    return {
        RegisterType.COIL: cfg.coil_count,
        RegisterType.DISCRETE: cfg.discrete_count,
        RegisterType.INPUT: cfg.input_count,
        RegisterType.HOLDING: cfg.holding_count,
    }[rt]


def _set_count(cfg: SlaveConfig, rt: RegisterType, value: int) -> None:
    if rt == RegisterType.COIL:
        cfg.coil_count = value
    elif rt == RegisterType.DISCRETE:
        cfg.discrete_count = value
    elif rt == RegisterType.INPUT:
        cfg.input_count = value
    else:
        cfg.holding_count = value


def _values_for(cfg: SlaveConfig, rt: RegisterType) -> List[int]:
    return {
        RegisterType.COIL: cfg.coil_values,
        RegisterType.DISCRETE: cfg.discrete_values,
        RegisterType.INPUT: cfg.input_values,
        RegisterType.HOLDING: cfg.holding_values,
    }[rt]


def _set_values(cfg: SlaveConfig, rt: RegisterType, values: List[int]) -> None:
    if rt == RegisterType.COIL:
        cfg.coil_values = values
    elif rt == RegisterType.DISCRETE:
        cfg.discrete_values = values
    elif rt == RegisterType.INPUT:
        cfg.input_values = values
    else:
        cfg.holding_values = values
