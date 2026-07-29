"""U 位预留对话框。预留占位但不是真实设备。"""

from __future__ import annotations

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.models import Reservation

from ..widgets.common import Hint, muted


class ReservationDialog(QDialog):
    def __init__(
        self,
        backend: Backend,
        reservation: Reservation | None = None,
        preset_cabinet_id: int | None = None,
        preset_u_start: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.reservation = reservation
        self.deleted = False

        self.setWindowTitle("编辑预留" if reservation else "新增 U 位预留")
        self.setMinimumWidth(480)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        self.cabinet_combo = QComboBox()
        for cab in backend.list_cabinets():
            place = " / ".join(filter(None, (cab.room_name, cab.row_name)))
            self.cabinet_combo.addItem(f"{place} / {cab.name}（{cab.u_total}U）", cab.id)

        self.u_start = QSpinBox()
        self.u_start.setRange(1, 100)
        self.u_size = QSpinBox()
        self.u_size.setRange(1, 60)
        u_row = QHBoxLayout()
        u_row.setSpacing(6)
        u_row.addWidget(self.u_start, 1)
        find_btn = QPushButton("自动找位")
        find_btn.clicked.connect(self._find_slot)
        u_row.addWidget(find_btn)
        u_wrap = QWidget()
        u_wrap.setLayout(u_row)

        self.label_edit = QLineEdit("预留")
        self.project_edit = QLineEdit()
        self.owner_edit = QLineEdit()
        self.planned_date = QDateEdit()
        self.planned_date.setCalendarPopup(True)
        self.planned_date.setDisplayFormat("yyyy-MM-dd")
        self.planned_date.setSpecialValueText("未定")
        self.planned_date.setMinimumDate(QDate(1990, 1, 1))
        self.planned_date.setDate(self.planned_date.minimumDate())
        self.remark_edit = QPlainTextEdit()
        self.remark_edit.setFixedHeight(56)

        form.addRow("机柜 *", self.cabinet_combo)
        form.addRow("起始U位（底部为1）", u_wrap)
        form.addRow("预留U数", self.u_size)
        form.addRow("标签 *", self.label_edit)
        form.addRow("项目", self.project_edit)
        form.addRow("责任人", self.owner_edit)
        form.addRow("计划上架", self.planned_date)
        form.addRow("备注", self.remark_edit)
        root.addLayout(form)

        self.slot_hint = muted("")
        self.slot_hint.setWordWrap(True)
        root.addWidget(self.slot_hint)

        self.hint = Hint("", "error")
        self.hint.hide()
        root.addWidget(self.hint)

        buttons = QDialogButtonBox()
        save_btn = buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        save_btn.setObjectName("primary")
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        if reservation:
            delete_btn = buttons.addButton("删除预留", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_btn.setObjectName("danger")
            delete_btn.clicked.connect(self._delete)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if reservation:
            self._fill(reservation)
        else:
            if preset_cabinet_id:
                index = self.cabinet_combo.findData(preset_cabinet_id)
                if index >= 0:
                    self.cabinet_combo.setCurrentIndex(index)
            if preset_u_start:
                self.u_start.setValue(preset_u_start)

    def _fill(self, item: Reservation) -> None:
        index = self.cabinet_combo.findData(item.cabinet_id)
        self.cabinet_combo.setCurrentIndex(max(0, index))
        self.u_start.setValue(item.u_start)
        self.u_size.setValue(item.u_size)
        self.label_edit.setText(item.label)
        self.project_edit.setText(item.project or "")
        self.owner_edit.setText(item.owner or "")
        self.remark_edit.setPlainText(item.remark or "")
        if item.planned_date:
            self.planned_date.setDate(QDate.fromString(item.planned_date, "yyyy-MM-dd"))

    def _find_slot(self) -> None:
        cabinet_id = self.cabinet_combo.currentData()
        if cabinet_id is None:
            return
        slots = self.backend.free_slots(int(cabinet_id))
        need = self.u_size.value()
        fit = next((s for s in slots if s.u_size >= need), None)
        text = "、".join(f"{s.u_start}-{s.u_end}U" for s in slots) or "无"
        if fit is None:
            self.slot_hint.setText(f"放不下 {need}U。当前空闲区间：{text}")
            return
        self.u_start.setValue(fit.u_start)
        self.slot_hint.setText(f"已选 {fit.u_start}U。当前空闲区间：{text}")

    def _save(self) -> None:
        cabinet_id = self.cabinet_combo.currentData()
        if cabinet_id is None:
            self.hint.set_kind("error", "请先建一个机柜再做预留")
            self.hint.show()
            return
        item = Reservation(
            id=self.reservation.id if self.reservation else 0,
            cabinet_id=int(cabinet_id),
            u_start=self.u_start.value(),
            u_size=self.u_size.value(),
            label=self.label_edit.text().strip() or "预留",
            project=self.project_edit.text().strip() or None,
            owner=self.owner_edit.text().strip() or None,
            planned_date=(
                self.planned_date.date().toString("yyyy-MM-dd")
                if self.planned_date.date() != self.planned_date.minimumDate()
                else None
            ),
            remark=self.remark_edit.toPlainText().strip() or None,
        )
        try:
            self.backend.save_reservation(item)
        except BackendError as exc:
            self.hint.set_kind("error", str(exc))
            self.hint.show()
            return
        self.accept()

    def _delete(self) -> None:
        if not self.reservation:
            return
        try:
            self.backend.delete_reservation(self.reservation.id)
        except BackendError as exc:
            self.hint.set_kind("error", str(exc))
            self.hint.show()
            return
        self.deleted = True
        self.accept()
