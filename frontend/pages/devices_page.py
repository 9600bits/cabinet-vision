"""设备台账页：筛选、排序、批量操作、导出。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import DEVICE_STATUSES, DEVICE_TYPES
from backend.models import DeviceQuery

from ..dialogs import BulkEditDialog, BulkRackDialog, DeviceDialog
from ..widgets.common import Card, muted
from ..widgets.device_table import COLUMNS, DeviceTableModel

_ALL = "全部"


class _MultiSelectCombo(QComboBox):
    """带勾选框的多选下拉，用于类型和状态筛选。"""

    changed = pyqtSignal()

    def __init__(self, options: tuple[str, ...], placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._checks: list[QCheckBox] = []
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(placeholder)

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem

        self._list = QListWidget()
        for option in options:
            item = QListWidgetItem()
            self._list.addItem(item)
            box = QCheckBox(option)
            box.stateChanged.connect(self._on_toggle)
            self._list.setItemWidget(item, box)
            self._checks.append(box)
        self.setModel(self._list.model())
        self.setView(self._list)

    def _on_toggle(self) -> None:
        selected = self.selected()
        self.lineEdit().setText("、".join(selected) if selected else "")
        self.changed.emit()

    def selected(self) -> tuple[str, ...]:
        return tuple(box.text() for box in self._checks if box.isChecked())

    def clear_selection(self) -> None:
        for box in self._checks:
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.lineEdit().setText("")


class DevicesPage(QWidget):
    data_changed = pyqtSignal()
    cabinet_requested = pyqtSignal(int)

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._sort_field: str | None = None
        self._sort_desc = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self.reload)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_bulk_bar())
        root.addWidget(self._build_table(), 1)
        root.addWidget(self._build_status_bar())

    # ---------- 界面 ----------

    def _build_toolbar(self) -> QVBoxLayout:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(8)

        first = QHBoxLayout()
        first.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设备名 / IP / 型号 / 序列号 / 资产号 / 机柜")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        first.addWidget(self.search)

        self.room_combo = QComboBox()
        self.room_combo.setFixedWidth(130)
        self.room_combo.currentIndexChanged.connect(self._on_room_changed)
        self.row_combo = QComboBox()
        self.row_combo.setFixedWidth(110)
        self.row_combo.currentIndexChanged.connect(self._on_row_changed)
        self.cabinet_combo = QComboBox()
        self.cabinet_combo.setFixedWidth(140)
        self.cabinet_combo.currentIndexChanged.connect(lambda _: self.reload())
        first.addWidget(QLabel("机房"))
        first.addWidget(self.room_combo)
        first.addWidget(QLabel("列"))
        first.addWidget(self.row_combo)
        first.addWidget(QLabel("机柜"))
        first.addWidget(self.cabinet_combo)

        self.type_combo = _MultiSelectCombo(DEVICE_TYPES, "类型")
        self.type_combo.setFixedWidth(150)
        self.type_combo.changed.connect(self.reload)
        self.status_combo = _MultiSelectCombo(DEVICE_STATUSES, "状态")
        self.status_combo.setFixedWidth(120)
        self.status_combo.changed.connect(self.reload)
        first.addWidget(self.type_combo)
        first.addWidget(self.status_combo)

        self.unracked_check = QCheckBox("仅未上架")
        self.unracked_check.stateChanged.connect(lambda _: self.reload())
        first.addWidget(self.unracked_check)
        first.addStretch(1)
        wrapper.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(8)
        self.owner_edit = QLineEdit()
        self.owner_edit.setPlaceholderText("责任人")
        self.owner_edit.setFixedWidth(110)
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("项目/业务")
        self.project_edit.setFixedWidth(140)
        self.vendor_edit = QLineEdit()
        self.vendor_edit.setPlaceholderText("厂商")
        self.vendor_edit.setFixedWidth(110)
        for widget in (self.owner_edit, self.project_edit, self.vendor_edit):
            widget.setClearButtonEnabled(True)
            widget.textChanged.connect(lambda _: self._search_timer.start())
            second.addWidget(widget)

        reset_btn = QPushButton("重置筛选")
        reset_btn.clicked.connect(self._reset_filters)
        second.addWidget(reset_btn)
        second.addStretch(1)

        add_btn = QPushButton("新增设备")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(lambda: self._open_dialog(None))
        second.addWidget(add_btn)

        # 放在工具栏而不是批量操作条里：批量条要选中才出现，
        # 藏在里面的功能没人找得到。这里常驻，没选中就置灰。
        self.copy_btn = QPushButton("复制设备")
        self.copy_btn.setEnabled(False)
        self.copy_btn.setToolTip("先在下面选一台设备")
        self.copy_btn.clicked.connect(self._copy_device)
        second.addWidget(self.copy_btn)

        export_btn = QPushButton("导出当前结果")
        export_btn.clicked.connect(self._export)
        second.addWidget(export_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload_all)
        second.addWidget(refresh_btn)
        wrapper.addLayout(second)
        return wrapper

    def _build_bulk_bar(self) -> QWidget:
        self.bulk_bar = Card(margins=(12, 8, 12, 8))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.bulk_label = QLabel("已选 0 台")
        row.addWidget(self.bulk_label)

        for text, handler, obj in (
            ("批量修改", self._bulk_edit, ""),
            ("批量上架", self._bulk_rack, ""),
            ("批量下架", self._bulk_unrack, ""),
            ("批量删除", self._bulk_delete, "danger"),
        ):
            btn = QPushButton(text)
            if obj:
                btn.setObjectName(obj)
            btn.clicked.connect(handler)
            row.addWidget(btn)

        clear_btn = QPushButton("取消选择")
        clear_btn.setObjectName("linkBtn")
        clear_btn.clicked.connect(lambda: self.table.clearSelection())
        row.addWidget(clear_btn)
        row.addStretch(1)
        self.bulk_bar.add_layout(row)
        self.bulk_bar.hide()
        return self.bulk_bar

    def _build_table(self) -> QWidget:
        self.model = DeviceTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        for index, (_, _, width, _, _) in enumerate(COLUMNS):
            self.table.setColumnWidth(index, width)
        return self.table

    def _build_status_bar(self) -> QWidget:
        self.status_label = muted("")
        return self.status_label

    # ---------- 筛选与加载 ----------

    def reload_all(self) -> None:
        self._load_places()
        self.reload()

    def _load_places(self) -> None:
        current = self.room_combo.currentData()
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        self.room_combo.addItem(_ALL, None)
        for room in self.backend.list_rooms():
            self.room_combo.addItem(room.name, room.id)
        if current is not None:
            index = self.room_combo.findData(current)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        self.room_combo.blockSignals(False)
        self._load_rows()

    def _load_rows(self) -> None:
        room_id = self.room_combo.currentData()
        self.row_combo.blockSignals(True)
        self.row_combo.clear()
        self.row_combo.addItem(_ALL, None)
        for row in self.backend.list_rows(int(room_id) if room_id else None):
            self.row_combo.addItem(row.name, row.id)
        self.row_combo.blockSignals(False)
        self._load_cabinets()

    def _load_cabinets(self) -> None:
        room_id = self.room_combo.currentData()
        row_id = self.row_combo.currentData()
        self.cabinet_combo.blockSignals(True)
        self.cabinet_combo.clear()
        self.cabinet_combo.addItem(_ALL, None)
        for cab in self.backend.list_cabinets(
            int(room_id) if room_id else None, int(row_id) if row_id else None
        ):
            self.cabinet_combo.addItem(cab.name, cab.id)
        self.cabinet_combo.blockSignals(False)

    def _on_room_changed(self) -> None:
        self._load_rows()
        self.reload()

    def _on_row_changed(self) -> None:
        self._load_cabinets()
        self.reload()

    def _reset_filters(self) -> None:
        for widget in (self.search, self.owner_edit, self.project_edit, self.vendor_edit):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self.type_combo.clear_selection()
        self.status_combo.clear_selection()
        self.unracked_check.blockSignals(True)
        self.unracked_check.setChecked(False)
        self.unracked_check.blockSignals(False)
        for combo in (self.room_combo, self.row_combo, self.cabinet_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._load_rows()
        self.reload()

    def current_query(self) -> DeviceQuery:
        return DeviceQuery(
            keyword=self.search.text().strip(),
            room_id=self.room_combo.currentData(),
            row_id=self.row_combo.currentData(),
            cabinet_id=self.cabinet_combo.currentData(),
            dev_types=self.type_combo.selected(),
            statuses=self.status_combo.selected(),
            owner=self.owner_edit.text().strip(),
            project=self.project_edit.text().strip(),
            vendor=self.vendor_edit.text().strip(),
            unracked_only=self.unracked_check.isChecked(),
            sort_by=self._sort_field,
            sort_desc=self._sort_desc,
        )

    def reload(self) -> None:
        try:
            devices = self.backend.query_devices(self.current_query())
        except BackendError as exc:
            QMessageBox.warning(self, "查询失败", str(exc))
            return
        self.model.set_devices(devices)
        total_all = self.backend.count_devices(DeviceQuery())
        racked = sum(1 for d in devices if d.is_racked)
        self.status_label.setText(
            f"当前结果 {len(devices)} 台（已上架 {racked}，未上架 {len(devices) - racked}）"
            f" · 台账共 {total_all} 台"
        )
        self._on_selection_changed()

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        field = self.model.sort_field(column)
        if field is None:
            return
        self._sort_field = field
        self._sort_desc = order == Qt.SortOrder.DescendingOrder
        self.reload()

    # ---------- 选中与批量 ----------

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _selected_ids(self) -> list[int]:
        return self.model.ids_at(self._selected_rows())

    def _on_selection_changed(self, *_args) -> None:
        count = len(self._selected_rows())
        self.bulk_label.setText(f"已选 {count} 台")
        self.bulk_bar.setVisible(count > 0)
        # 复制一次只处理一台，多选就置灰并说明原因，
        # 而不是让人点了再弹框拒绝
        self.copy_btn.setEnabled(count == 1)
        if count == 0:
            self.copy_btn.setToolTip("先在下面选一台设备")
        elif count == 1:
            self.copy_btn.setToolTip("")
        else:
            self.copy_btn.setToolTip("复制一次只能选一台")

    def _on_double_click(self, index) -> None:
        device = self.model.device_at(index.row())
        if device is not None:
            self._open_dialog(device.id)

    def _open_dialog(self, device_id: int | None) -> None:
        dialog = DeviceDialog(self.backend, device_id=device_id, parent=self)
        if dialog.exec():
            self.reload()
            self.data_changed.emit()

    def _copy_device(self) -> None:
        """以选中设备为模板开新增对话框。原设备不动。"""
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        try:
            draft = self.backend.copy_of_device(ids[0])
        except BackendError as exc:
            QMessageBox.warning(self, "复制失败", str(exc))
            return
        dialog = DeviceDialog(self.backend, copy_from=draft, parent=self)
        if dialog.exec():
            self.reload()
            self.data_changed.emit()

    def _bulk_edit(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        dialog = BulkEditDialog(self.backend, ids, parent=self)
        if dialog.exec():
            QMessageBox.information(self, "批量修改", f"已修改 {dialog.changed} 台设备")
            self.reload()
            self.data_changed.emit()

    def _bulk_rack(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        dialog = BulkRackDialog(self.backend, ids, parent=self)
        if dialog.exec():
            message = f"成功上架 {len(dialog.placed)} 台。"
            if dialog.failed:
                detail = "\n".join(f"· {name}：{reason}" for name, reason in dialog.failed)
                message += f"\n\n{len(dialog.failed)} 台没放下：\n{detail}"
            QMessageBox.information(self, "批量上架", message)
            self.reload()
            self.data_changed.emit()

    def _bulk_unrack(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        answer = QMessageBox.question(
            self,
            "批量下架",
            f"把选中的 {len(ids)} 台设备移出机柜？设备仍保留在台账里，只是清掉位置。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = self.backend.unrack_devices(ids)
        except BackendError as exc:
            QMessageBox.warning(self, "操作失败", str(exc))
            return
        QMessageBox.information(self, "批量下架", f"已下架 {moved} 台")
        self.reload()
        self.data_changed.emit()

    def _bulk_delete(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        answer = QMessageBox.warning(
            self,
            "批量删除",
            f"确定删除选中的 {len(ids)} 台设备？删除后无法恢复，建议先在设置页做一次备份。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.backend.delete_devices(ids)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        QMessageBox.information(self, "批量删除", f"已删除 {deleted} 台设备")
        self.reload()
        self.data_changed.emit()

    # ---------- 导出 ----------

    def _export(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出设备清单",
            str(Path.home() / "Downloads" / f"设备台账-{stamp}.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            self.backend.export_devices(path, self.current_query())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")
