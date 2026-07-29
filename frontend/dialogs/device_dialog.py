"""设备新增 / 编辑对话框，含连接关系。"""

from __future__ import annotations

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import DEVICE_STATUSES, DEVICE_TYPES
from backend.models import Device

from ..widgets.common import Hint, muted
from .links_panel import LinksPanel

_NO_CABINET = -1


class DeviceDialog(QDialog):
    """新增时可以带预设位置（点机柜空位进来的情况）。"""

    def __init__(
        self,
        backend: Backend,
        device_id: int | None = None,
        preset_cabinet_id: int | None = None,
        preset_u_start: int | None = None,
        copy_from: Device | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.device_id = device_id
        # 复制模式：device_id 保持 None，所以保存时走新增；
        # 字段用源设备预填，改几处就能存
        self.copy_from = copy_from
        self.saved_device: Device | None = None

        if device_id:
            title = "编辑设备"
        elif copy_from is not None:
            title = "复制设备"
        else:
            title = "新增设备"
        self.setWindowTitle(title)
        self.setMinimumWidth(660)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "基本信息")
        self.tabs.addTab(self._build_extra_tab(), "资产与责任")
        if device_id:
            self.links_panel = LinksPanel(backend, device_id)
            self.tabs.addTab(self.links_panel, "连接关系")
        root.addWidget(self.tabs, 1)

        self.hint = Hint("", "error")
        self.hint.hide()
        root.addWidget(self.hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_cabinets()
        if device_id:
            self._load_device(device_id)
        elif copy_from is not None:
            self._fill(copy_from)
            self.name_edit.selectAll()      # 名字最可能要改，进来就选中
            self.name_edit.setFocus()
        else:
            self._apply_preset(preset_cabinet_id, preset_u_start)

    # ---------- 构建界面 ----------

    def _build_basic_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("SW-CORE-01")
        self.type_combo = QComboBox()
        self.type_combo.addItems(DEVICE_TYPES)
        self.status_combo = QComboBox()
        self.status_combo.addItems(DEVICE_STATUSES)

        grid.addWidget(QLabel("设备名 *"), 0, 0)
        grid.addWidget(self.name_edit, 1, 0)
        grid.addWidget(QLabel("类型"), 0, 1)
        grid.addWidget(self.type_combo, 1, 1)
        grid.addWidget(QLabel("状态"), 0, 2)
        grid.addWidget(self.status_combo, 1, 2)

        self.cabinet_combo = QComboBox()
        self.cabinet_combo.currentIndexChanged.connect(self._on_cabinet_changed)
        self.u_start_spin = QSpinBox()
        self.u_start_spin.setRange(0, 100)
        self.u_start_spin.setSpecialValueText("未上架")
        self.u_size_spin = QSpinBox()
        self.u_size_spin.setRange(1, 60)

        grid.addWidget(QLabel("机柜"), 2, 0)
        grid.addWidget(self.cabinet_combo, 3, 0)
        grid.addWidget(QLabel("起始U位（底部为1）"), 2, 1)
        u_row = QHBoxLayout()
        u_row.setSpacing(6)
        u_row.addWidget(self.u_start_spin, 1)
        self.find_slot_btn = QPushButton("自动找位")
        self.find_slot_btn.clicked.connect(self._find_slot)
        u_row.addWidget(self.find_slot_btn)
        u_wrap = QWidget()
        u_wrap.setLayout(u_row)
        grid.addWidget(u_wrap, 3, 1)
        grid.addWidget(QLabel("占用U数"), 2, 2)
        grid.addWidget(self.u_size_spin, 3, 2)

        self.model_edit = QLineEdit()
        self.vendor_edit = QLineEdit()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("10.0.0.11")
        grid.addWidget(QLabel("型号"), 4, 0)
        grid.addWidget(self.model_edit, 5, 0)
        grid.addWidget(QLabel("厂商"), 4, 1)
        grid.addWidget(self.vendor_edit, 5, 1)
        grid.addWidget(QLabel("管理IP"), 4, 2)
        grid.addWidget(self.ip_edit, 5, 2)

        layout.addLayout(grid)

        self.slot_hint = muted("")
        self.slot_hint.setWordWrap(True)
        layout.addWidget(self.slot_hint)

        layout.addWidget(QLabel("备注"))
        self.remark_edit = QPlainTextEdit()
        self.remark_edit.setFixedHeight(60)
        layout.addWidget(self.remark_edit)
        layout.addStretch(1)
        return page

    def _build_extra_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 12, 4, 4)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        self.sn_edit = QLineEdit()
        self.asset_edit = QLineEdit()
        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(0, 100000)
        self.power_spin.setDecimals(0)
        self.power_spin.setSuffix(" W")
        self.power_spin.setSpecialValueText("未填")
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0, 5000)
        self.weight_spin.setDecimals(1)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setSpecialValueText("未填")

        self.install_date = self._date_edit()
        self.warranty_date = self._date_edit()
        self.owner_edit = QLineEdit()
        self.project_edit = QLineEdit()

        form.addRow("序列号", self.sn_edit)
        form.addRow("资产编号", self.asset_edit)
        form.addRow("功耗", self.power_spin)
        form.addRow("重量", self.weight_spin)
        form.addRow("上架日期", self.install_date)
        form.addRow("保修到期", self.warranty_date)
        form.addRow("责任人", self.owner_edit)
        form.addRow("项目/业务", self.project_edit)
        form.addRow(muted("功耗和重量会汇总到机柜容量里，建议填上"))
        return page

    @staticmethod
    def _date_edit() -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setSpecialValueText("未填")
        edit.setMinimumDate(QDate(1990, 1, 1))
        edit.setDate(edit.minimumDate())
        return edit

    # ---------- 数据 ----------

    def _load_cabinets(self) -> None:
        self.cabinet_combo.clear()
        self.cabinet_combo.addItem("未上架（待分配位置）", _NO_CABINET)
        for cab in self.backend.list_cabinets():
            place = " / ".join(filter(None, (cab.room_name, cab.row_name)))
            self.cabinet_combo.addItem(f"{place} / {cab.name}（{cab.u_total}U）", cab.id)

    def _apply_preset(self, cabinet_id: int | None, u_start: int | None) -> None:
        if cabinet_id:
            index = self.cabinet_combo.findData(cabinet_id)
            if index >= 0:
                self.cabinet_combo.setCurrentIndex(index)
        if u_start:
            self.u_start_spin.setValue(u_start)
        self.type_combo.setCurrentText("交换机")

    def _load_device(self, device_id: int) -> None:
        try:
            device = self.backend.get_device(device_id)
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self._fill(device)

    def _fill(self, device: Device) -> None:
        """把 Device 铺到各个输入框。

        编辑走这里，复制也走这里 —— 复制传进来的是后端造好的副本
        （已改名、SN / 资产号 / 管理 IP 已清空），没落库，所以拿到的
        是同一套字段，不用两份填充代码。
        """
        self.name_edit.setText(device.name)
        self.type_combo.setCurrentText(device.dev_type)
        self.status_combo.setCurrentText(device.status)
        index = self.cabinet_combo.findData(device.cabinet_id or _NO_CABINET)
        self.cabinet_combo.setCurrentIndex(max(0, index))
        self.u_start_spin.setValue(device.u_start or 0)
        self.u_size_spin.setValue(device.u_size)
        self.model_edit.setText(device.model or "")
        self.vendor_edit.setText(device.vendor or "")
        self.ip_edit.setText(device.mgmt_ip or "")
        self.remark_edit.setPlainText(device.remark or "")
        self.sn_edit.setText(device.sn or "")
        self.asset_edit.setText(device.asset_no or "")
        self.power_spin.setValue(device.power_w or 0)
        self.weight_spin.setValue(device.weight_kg or 0)
        self.owner_edit.setText(device.owner or "")
        self.project_edit.setText(device.project or "")
        for edit, value in ((self.install_date, device.install_date),
                            (self.warranty_date, device.warranty_end)):
            if value:
                edit.setDate(QDate.fromString(value, "yyyy-MM-dd"))

    def _on_cabinet_changed(self) -> None:
        has_cabinet = self.cabinet_combo.currentData() != _NO_CABINET
        self.u_start_spin.setEnabled(has_cabinet)
        self.find_slot_btn.setEnabled(has_cabinet)
        if not has_cabinet:
            self.u_start_spin.setValue(0)
            self.slot_hint.setText("未上架的设备会进入「待上架」列表，之后可以拖到机柜里")
        else:
            self.slot_hint.setText("")

    def _find_slot(self) -> None:
        cabinet_id = self.cabinet_combo.currentData()
        if cabinet_id == _NO_CABINET:
            return
        u_size = self.u_size_spin.value()
        slots = self.backend.free_slots(int(cabinet_id))
        fit = next((s for s in slots if s.u_size >= u_size), None)
        text = "、".join(f"{s.u_start}-{s.u_end}U" for s in slots) or "无"
        if fit is None:
            self.slot_hint.setText(f"放不下 {u_size}U。当前空闲区间：{text}")
            return
        self.u_start_spin.setValue(fit.u_start)
        self.slot_hint.setText(f"已选 {fit.u_start}U。当前空闲区间：{text}")

    def _collect(self) -> Device:
        cabinet_id = self.cabinet_combo.currentData()
        u_start = self.u_start_spin.value()
        install = self.install_date.date()
        warranty = self.warranty_date.date()

        return Device(
            id=self.device_id or 0,
            name=self.name_edit.text().strip(),
            cabinet_id=None if cabinet_id == _NO_CABINET else int(cabinet_id),
            u_start=None if u_start <= 0 else u_start,
            u_size=self.u_size_spin.value(),
            dev_type=self.type_combo.currentText(),
            status=self.status_combo.currentText(),
            model=self.model_edit.text().strip() or None,
            vendor=self.vendor_edit.text().strip() or None,
            sn=self.sn_edit.text().strip() or None,
            asset_no=self.asset_edit.text().strip() or None,
            mgmt_ip=self.ip_edit.text().strip() or None,
            power_w=self.power_spin.value() or None,
            weight_kg=self.weight_spin.value() or None,
            install_date=(
                install.toString("yyyy-MM-dd")
                if install != self.install_date.minimumDate()
                else None
            ),
            warranty_end=(
                warranty.toString("yyyy-MM-dd")
                if warranty != self.warranty_date.minimumDate()
                else None
            ),
            owner=self.owner_edit.text().strip() or None,
            project=self.project_edit.text().strip() or None,
            remark=self.remark_edit.toPlainText().strip() or None,
        )

    def _on_save(self) -> None:
        try:
            self.saved_device = self.backend.save_device(self._collect())
        except BackendError as exc:
            self.hint.set_kind("error", str(exc))
            self.hint.show()
            self.tabs.setCurrentIndex(0)
            return
        self.accept()
