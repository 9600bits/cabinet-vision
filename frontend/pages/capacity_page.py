"""容量规划页：机房 / 列 / 机柜三级汇总 + 预留清单。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.models import CapacityRow, Reservation

from .. import theme
from ..dialogs import ReservationDialog
from ..widgets.common import UsageBar, muted

_ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1

_CAP_HEADERS = (
    ("名称", 150),
    ("所属", 120),
    ("机柜数", 66),
    ("设备数", 66),
    ("U位占用", 150),
    ("U位明细", 170),
    ("功率", 150),
    ("承重", 150),
    ("状态", 70),
)

_RV_HEADERS = (
    ("标签", 160),
    ("机房", 110),
    ("机柜", 100),
    ("U位", 120),
    ("项目", 140),
    ("责任人", 90),
    ("计划上架", 110),
    ("备注", 200),
)


class CapacityPage(QWidget):
    cabinet_requested = pyqtSignal(int)
    data_changed = pyqtSignal()

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._scope = "机柜"
        self._rows: list[CapacityRow] = []
        self._reservations: list[Reservation] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_capacity_table())
        self.stack.addWidget(self._build_reservation_table())
        root.addWidget(self.stack, 1)

        self.summary = muted("")
        root.addWidget(self.summary)

    # ---------- 界面 ----------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        group = QButtonGroup(self)
        for label in ("机房", "列", "机柜", "预留清单"):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(78 if label == "预留清单" else 56)
            btn.clicked.connect(lambda _, s=label: self._set_scope(s))
            group.addButton(btn)
            bar.addWidget(btn)
            if label == "机柜":
                btn.setChecked(True)

        bar.addSpacing(12)
        bar.addWidget(QLabel("机房"))
        self.room_combo = QComboBox()
        self.room_combo.setFixedWidth(140)
        self.room_combo.currentIndexChanged.connect(lambda _: self.reload())
        bar.addWidget(self.room_combo)

        self.overload_only = QPushButton("只看超限")
        self.overload_only.setCheckable(True)
        self.overload_only.clicked.connect(lambda _: self.reload())
        bar.addWidget(self.overload_only)

        bar.addStretch(1)

        new_rv_btn = QPushButton("新增预留")
        new_rv_btn.clicked.connect(self._new_reservation)
        bar.addWidget(new_rv_btn)

        export_btn = QPushButton("导出容量报表")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export)
        bar.addWidget(export_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload_all)
        bar.addWidget(refresh_btn)
        return bar

    @staticmethod
    def _make_table(headers: tuple[tuple[str, int], ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels([h for h, _ in headers])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(30)
        for index, (_, width) in enumerate(headers):
            table.setColumnWidth(index, width)
        table.horizontalHeader().setSectionResizeMode(
            len(headers) - 1, QHeaderView.ResizeMode.Stretch
        )
        return table

    def _build_capacity_table(self) -> QWidget:
        self.cap_table = self._make_table(_CAP_HEADERS)
        self.cap_table.doubleClicked.connect(self._on_capacity_double_click)
        return self.cap_table

    def _build_reservation_table(self) -> QWidget:
        self.rv_table = self._make_table(_RV_HEADERS)
        self.rv_table.doubleClicked.connect(self._on_reservation_double_click)
        return self.rv_table

    # ---------- 数据 ----------

    def reload_all(self) -> None:
        self._load_rooms()
        self.reload()

    def _load_rooms(self) -> None:
        current = self.room_combo.currentData()
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        self.room_combo.addItem("全部机房", None)
        for room in self.backend.list_rooms():
            self.room_combo.addItem(room.name, room.id)
        if current is not None:
            index = self.room_combo.findData(current)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        self.room_combo.blockSignals(False)

    def _set_scope(self, scope: str) -> None:
        self._scope = scope
        self.stack.setCurrentIndex(1 if scope == "预留清单" else 0)
        self.overload_only.setVisible(scope != "预留清单")
        self.reload()

    def reload(self) -> None:
        if self._scope == "预留清单":
            self._reload_reservations()
            return

        room_id = self.room_combo.currentData()
        try:
            report = self.backend.capacity_report(int(room_id) if room_id else None)
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return

        key = {"机房": "rooms", "列": "rows", "机柜": "cabinets"}[self._scope]
        rows = report[key]
        if self.overload_only.isChecked():
            rows = [r for r in rows if r.overload]
        self._rows = rows
        self._fill_capacity_table(rows)

    def _fill_capacity_table(self, rows: list[CapacityRow]) -> None:
        table = self.cap_table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            name_item = QTableWidgetItem(row.name)
            name_item.setData(_ROLE_ID, row.id)
            if row.scope != "cabinet":
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
            else:
                name_item.setToolTip("双击可跳到机柜视图")
            table.setItem(index, 0, name_item)
            table.setItem(index, 1, QTableWidgetItem(row.parent_name or ""))

            for col, value in ((2, row.cabinet_count), (3, row.device_count)):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
                table.setItem(index, col, item)

            used = row.u_used + row.u_reserved
            table.setCellWidget(
                index,
                4,
                UsageBar(used, row.u_total, f"{used}/{row.u_total}U", row.u_used + row.u_reserved > row.u_total),
            )
            detail = QTableWidgetItem(
                f"用{row.u_used} 留{row.u_reserved} 空{row.u_free} · {row.u_usage_pct}%"
            )
            detail.setForeground(Qt.GlobalColor.darkGray)
            table.setItem(index, 5, detail)

            if row.power_limit_w > 0:
                table.setCellWidget(
                    index,
                    6,
                    UsageBar(
                        row.power_used_w,
                        row.power_limit_w,
                        f"{row.power_used_w:g}/{row.power_limit_w:g}W",
                        row.power_used_w > row.power_limit_w,
                    ),
                )
            else:
                table.setCellWidget(index, 6, QLabel(f" {row.power_used_w:g}W / 未设上限"))

            if row.weight_limit_kg > 0:
                table.setCellWidget(
                    index,
                    7,
                    UsageBar(
                        row.weight_used_kg,
                        row.weight_limit_kg,
                        f"{row.weight_used_kg:g}/{row.weight_limit_kg:g}kg",
                        row.weight_used_kg > row.weight_limit_kg,
                    ),
                )
            else:
                table.setCellWidget(index, 7, QLabel(f" {row.weight_used_kg:g}kg / 未设上限"))

            status = QTableWidgetItem("超限" if row.overload else "")
            status.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            if row.overload:
                from PyQt6.QtGui import QBrush, QColor

                status.setForeground(QBrush(QColor(theme.DANGER)))
                font = status.font()
                font.setBold(True)
                status.setFont(font)
            table.setItem(index, 8, status)

        totals = {
            "cabinets": sum(r.cabinet_count for r in rows),
            "devices": sum(r.device_count for r in rows),
            "u_total": sum(r.u_total for r in rows),
            "u_used": sum(r.u_used for r in rows),
            "u_reserved": sum(r.u_reserved for r in rows),
            "power": sum(r.power_used_w for r in rows),
        }
        pct = (
            round((totals["u_used"] + totals["u_reserved"]) / totals["u_total"] * 100, 1)
            if totals["u_total"]
            else 0
        )
        overloads = sum(1 for r in rows if r.overload)
        self.summary.setText(
            f"合计：{totals['cabinets']} 个机柜，{totals['devices']} 台设备，"
            f"U 位 {totals['u_used']} 用 + {totals['u_reserved']} 留 / {totals['u_total']} 总"
            f"（占用 {pct}%），总功耗 {totals['power']:g}W"
            + (f" · {overloads} 项超限" if overloads else "")
        )

    def _reload_reservations(self) -> None:
        try:
            self._reservations = self.backend.list_reservations()
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return

        room_id = self.room_combo.currentData()
        rows = self._reservations
        if room_id:
            room_name = self.room_combo.currentText()
            rows = [r for r in rows if r.room_name == room_name]

        table = self.rv_table
        table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            values = (
                item.label,
                item.room_name or "",
                item.cabinet_name or "",
                f"{item.u_start}-{item.u_end}U（{item.u_size}U）"
                if item.u_size > 1
                else f"{item.u_start}U",
                item.project or "",
                item.owner or "",
                item.planned_date or "",
                item.remark or "",
            )
            for col, text in enumerate(values):
                cell = QTableWidgetItem(text)
                if col == 0:
                    cell.setData(_ROLE_ID, item.id)
                    cell.setToolTip("双击可编辑预留")
                table.setItem(index, col, cell)

        total_u = sum(r.u_size for r in rows)
        self.summary.setText(f"共 {len(rows)} 条预留，合计占用 {total_u}U")

    # ---------- 交互 ----------

    def _on_capacity_double_click(self, index) -> None:
        if index.row() >= len(self._rows):
            return
        row = self._rows[index.row()]
        if row.scope == "cabinet":
            self.cabinet_requested.emit(row.id)

    def _on_reservation_double_click(self, index) -> None:
        item = self.rv_table.item(index.row(), 0)
        if item is None:
            return
        reservation_id = int(item.data(_ROLE_ID))
        target = next((r for r in self._reservations if r.id == reservation_id), None)
        if target is None:
            return
        dialog = ReservationDialog(self.backend, reservation=target, parent=self)
        if dialog.exec():
            self.reload()
            self.data_changed.emit()

    def _new_reservation(self) -> None:
        dialog = ReservationDialog(self.backend, parent=self)
        if dialog.exec():
            self.reload()
            self.data_changed.emit()

    def _export(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出容量报表",
            str(Path.home() / "Downloads" / f"容量报表-{stamp}.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            self.backend.export_capacity(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")
