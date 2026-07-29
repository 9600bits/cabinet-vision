"""机房 / 列 / 机柜的编辑对话框，以及批量建柜。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import CABINET_STATUSES, COMMON_U_TOTALS
from backend.models import Cabinet, RackRow, Room

from ..widgets.common import Hint, muted

_NO_ROW = -1


class _BaseDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None, width: int = 460) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setModal(True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 14, 16, 14)
        self.root.setSpacing(10)
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(9)
        self.root.addLayout(self.form)
        self.hint = Hint("", "error")
        self.hint.hide()
        self.root.addWidget(self.hint)

    def _add_buttons(self, ok_text: str = "保存") -> None:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.root.addWidget(buttons)

    def _save(self) -> None:  # 子类实现
        raise NotImplementedError

    def _fail(self, message: str) -> None:
        self.hint.set_kind("error", message)
        self.hint.show()


class RoomDialog(_BaseDialog):
    def __init__(self, backend: Backend, room: Room | None = None, parent: QWidget | None = None) -> None:
        super().__init__("编辑机房" if room else "新增机房", parent)
        self.backend = backend
        self.room = room

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("主机房")
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("IDC-A")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("园区 3 号楼 2 层")
        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 9999)
        self.remark_edit = QPlainTextEdit()
        self.remark_edit.setFixedHeight(56)

        self.form.addRow("机房名称 *", self.name_edit)
        self.form.addRow("编码", self.code_edit)
        self.form.addRow("位置", self.location_edit)
        self.form.addRow("排序", self.sort_spin)
        self.form.addRow("备注", self.remark_edit)
        self._add_buttons()

        if room:
            self.name_edit.setText(room.name)
            self.code_edit.setText(room.code or "")
            self.location_edit.setText(room.location or "")
            self.sort_spin.setValue(room.sort_order)
            self.remark_edit.setPlainText(room.remark or "")

    def _save(self) -> None:
        try:
            self.backend.save_room(
                Room(
                    id=self.room.id if self.room else 0,
                    name=self.name_edit.text().strip(),
                    code=self.code_edit.text().strip() or None,
                    location=self.location_edit.text().strip() or None,
                    remark=self.remark_edit.toPlainText().strip() or None,
                    sort_order=self.sort_spin.value(),
                )
            )
        except BackendError as exc:
            self._fail(str(exc))
            return
        self.accept()


class RowDialog(_BaseDialog):
    def __init__(
        self,
        backend: Backend,
        row: RackRow | None = None,
        default_room_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("编辑列" if row else "新增列", parent)
        self.backend = backend
        self.row = row

        self.room_combo = QComboBox()
        for room in backend.list_rooms():
            self.room_combo.addItem(room.name, room.id)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("A列")
        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 9999)
        self.remark_edit = QLineEdit()

        self.form.addRow("所属机房 *", self.room_combo)
        self.form.addRow("列名称 *", self.name_edit)
        self.form.addRow("排序", self.sort_spin)
        self.form.addRow("备注", self.remark_edit)
        self._add_buttons()

        target_room = row.room_id if row else default_room_id
        if target_room:
            index = self.room_combo.findData(target_room)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        if row:
            self.name_edit.setText(row.name)
            self.sort_spin.setValue(row.sort_order)
            self.remark_edit.setText(row.remark or "")

    def _save(self) -> None:
        room_id = self.room_combo.currentData()
        if room_id is None:
            self._fail("请先创建机房")
            return
        try:
            self.backend.save_row(
                RackRow(
                    id=self.row.id if self.row else 0,
                    room_id=int(room_id),
                    name=self.name_edit.text().strip(),
                    remark=self.remark_edit.text().strip() or None,
                    sort_order=self.sort_spin.value(),
                )
            )
        except BackendError as exc:
            self._fail(str(exc))
            return
        self.accept()


class CabinetDialog(_BaseDialog):
    def __init__(
        self,
        backend: Backend,
        cabinet: Cabinet | None = None,
        default_room_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("编辑机柜" if cabinet else "新增机柜", parent, width=520)
        self.backend = backend
        self.cabinet = cabinet

        self.room_combo = QComboBox()
        for room in backend.list_rooms():
            self.room_combo.addItem(room.name, room.id)
        self.room_combo.currentIndexChanged.connect(self._reload_rows)

        self.row_combo = QComboBox()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("A01")
        self.code_edit = QLineEdit()
        self.u_total_combo = QComboBox()
        self.u_total_combo.setEditable(True)
        for value in COMMON_U_TOTALS:
            self.u_total_combo.addItem(f"{value}U", value)
        self.position_spin = QSpinBox()
        self.position_spin.setRange(0, 999)
        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(0, 100000)
        self.power_spin.setDecimals(0)
        self.power_spin.setSuffix(" W")
        self.power_spin.setSpecialValueText("未设上限")
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0, 20000)
        self.weight_spin.setDecimals(0)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setSpecialValueText("未设上限")
        self.status_combo = QComboBox()
        self.status_combo.addItems(CABINET_STATUSES)
        self.remark_edit = QPlainTextEdit()
        self.remark_edit.setFixedHeight(52)

        self.form.addRow("所属机房 *", self.room_combo)
        self.form.addRow("所在列", self.row_combo)
        self.form.addRow("机柜编号 *", self.name_edit)
        self.form.addRow("总U数 *", self.u_total_combo)
        self.form.addRow("列内序号", self.position_spin)
        self.form.addRow("功率上限", self.power_spin)
        self.form.addRow("承重上限", self.weight_spin)
        self.form.addRow("状态", self.status_combo)
        self.form.addRow("编码", self.code_edit)
        self.form.addRow("备注", self.remark_edit)
        self.form.addRow(muted("功率和承重上限用于容量规划，超限会在容量页标红"))
        self._add_buttons()

        target_room = cabinet.room_id if cabinet else default_room_id
        if target_room:
            index = self.room_combo.findData(target_room)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        self._reload_rows()

        if cabinet:
            self.name_edit.setText(cabinet.name)
            self.code_edit.setText(cabinet.code or "")
            self.u_total_combo.setCurrentText(f"{cabinet.u_total}U")
            self.position_spin.setValue(cabinet.position_in_row)
            self.power_spin.setValue(cabinet.power_limit_w or 0)
            self.weight_spin.setValue(cabinet.weight_limit_kg or 0)
            self.status_combo.setCurrentText(cabinet.status)
            self.remark_edit.setPlainText(cabinet.remark or "")
            if cabinet.row_id:
                index = self.row_combo.findData(cabinet.row_id)
                if index >= 0:
                    self.row_combo.setCurrentIndex(index)

    def _reload_rows(self) -> None:
        room_id = self.room_combo.currentData()
        self.row_combo.clear()
        self.row_combo.addItem("未分列", _NO_ROW)
        if room_id is None:
            return
        for row in self.backend.list_rows(int(room_id)):
            self.row_combo.addItem(row.name, row.id)

    def _u_total(self) -> int:
        data = self.u_total_combo.currentData()
        if data is not None and self.u_total_combo.currentText() == f"{data}U":
            return int(data)
        digits = "".join(ch for ch in self.u_total_combo.currentText() if ch.isdigit())
        return int(digits) if digits else 42

    def _save(self) -> None:
        room_id = self.room_combo.currentData()
        if room_id is None:
            self._fail("请先创建机房")
            return
        row_id = self.row_combo.currentData()
        try:
            self.backend.save_cabinet(
                Cabinet(
                    id=self.cabinet.id if self.cabinet else 0,
                    room_id=int(room_id),
                    row_id=None if row_id in (None, _NO_ROW) else int(row_id),
                    name=self.name_edit.text().strip(),
                    code=self.code_edit.text().strip() or None,
                    u_total=self._u_total(),
                    power_limit_w=self.power_spin.value() or None,
                    weight_limit_kg=self.weight_spin.value() or None,
                    position_in_row=self.position_spin.value(),
                    status=self.status_combo.currentText(),
                    remark=self.remark_edit.toPlainText().strip() or None,
                )
            )
        except BackendError as exc:
            self._fail(str(exc))
            return
        self.accept()


class BatchCabinetDialog(_BaseDialog):
    """按编号规则一次铺一整列机柜。"""

    def __init__(
        self, backend: Backend, default_room_id: int | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__("批量建柜", parent, width=520)
        self.backend = backend
        self.created = 0
        self.skipped: list[str] = []

        self.room_combo = QComboBox()
        for room in backend.list_rooms():
            self.room_combo.addItem(room.name, room.id)
        self.room_combo.currentIndexChanged.connect(self._reload_rows)
        self.row_combo = QComboBox()

        self.prefix_edit = QLineEdit("A")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 9999)
        self.start_spin.setValue(1)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 200)
        self.count_spin.setValue(10)
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(1, 4)
        self.digits_spin.setValue(2)
        self.u_total_combo = QComboBox()
        for value in COMMON_U_TOTALS:
            self.u_total_combo.addItem(f"{value}U", value)
        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(0, 100000)
        self.power_spin.setDecimals(0)
        self.power_spin.setSuffix(" W")
        self.power_spin.setSpecialValueText("未设上限")
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0, 20000)
        self.weight_spin.setDecimals(0)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setSpecialValueText("未设上限")

        self.form.addRow("所属机房 *", self.room_combo)
        self.form.addRow("所在列", self.row_combo)
        self.form.addRow("编号前缀 *", self.prefix_edit)
        self.form.addRow("起始序号", self.start_spin)
        self.form.addRow("数量", self.count_spin)
        self.form.addRow("序号位数", self.digits_spin)
        self.form.addRow("总U数", self.u_total_combo)
        self.form.addRow("功率上限", self.power_spin)
        self.form.addRow("承重上限", self.weight_spin)

        self.preview = muted("")
        self.preview.setWordWrap(True)
        self.root.addWidget(self.preview)
        self.root.addWidget(muted("已存在的编号会自动跳过，可以用它给某一列补建缺失的柜子。"))
        self._add_buttons("创建")

        for widget in (self.prefix_edit,):
            widget.textChanged.connect(self._update_preview)
        for spin in (self.start_spin, self.count_spin, self.digits_spin):
            spin.valueChanged.connect(self._update_preview)

        if default_room_id:
            index = self.room_combo.findData(default_room_id)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        self._reload_rows()
        self._update_preview()

    def _reload_rows(self) -> None:
        room_id = self.room_combo.currentData()
        self.row_combo.clear()
        self.row_combo.addItem("未分列", _NO_ROW)
        if room_id is None:
            return
        for row in self.backend.list_rows(int(room_id)):
            self.row_combo.addItem(row.name, row.id)

    def _update_preview(self) -> None:
        names = self.backend.preview_batch_names(
            self.prefix_edit.text().strip(),
            self.start_spin.value(),
            self.count_spin.value(),
            self.digits_spin.value(),
        )
        more = f" … 共 {self.count_spin.value()} 个" if self.count_spin.value() > len(names) else ""
        self.preview.setText("将创建：" + "、".join(names) + more)

    def _save(self) -> None:
        room_id = self.room_combo.currentData()
        if room_id is None:
            self._fail("请先创建机房")
            return
        if not self.prefix_edit.text().strip():
            self._fail("编号前缀不能为空")
            return
        row_id = self.row_combo.currentData()
        try:
            self.created, self.skipped = self.backend.batch_create_cabinets(
                room_id=int(room_id),
                row_id=None if row_id in (None, _NO_ROW) else int(row_id),
                prefix=self.prefix_edit.text().strip(),
                start_no=self.start_spin.value(),
                count=self.count_spin.value(),
                digits=self.digits_spin.value(),
                u_total=int(self.u_total_combo.currentData()),
                power_limit_w=self.power_spin.value() or None,
                weight_limit_kg=self.weight_spin.value() or None,
            )
        except BackendError as exc:
            self._fail(str(exc))
            return
        self.accept()
