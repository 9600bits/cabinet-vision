"""批量修改与批量上架对话框。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import DEVICE_STATUSES, DEVICE_TYPES

from ..widgets.common import Hint, muted

_KEEP = "（保持原值）"


class BulkEditDialog(QDialog):
    """留空的字段不动，只提交填了值的。"""

    def __init__(self, backend: Backend, device_ids: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.device_ids = device_ids
        self.changed = 0

        self.setWindowTitle(f"批量修改 {len(device_ids)} 台设备")
        self.setMinimumWidth(440)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(
            Hint("留空或选「保持原值」的字段不会被修改。机柜和 U 位请用拖拽或批量上架调整。", "info")
        )

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        self.type_combo = QComboBox()
        self.type_combo.addItem(_KEEP)
        self.type_combo.addItems(DEVICE_TYPES)
        self.status_combo = QComboBox()
        self.status_combo.addItem(_KEEP)
        self.status_combo.addItems(DEVICE_STATUSES)
        self.vendor_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.owner_edit = QLineEdit()
        self.project_edit = QLineEdit()
        self.remark_edit = QLineEdit()

        form.addRow("设备类型", self.type_combo)
        form.addRow("状态", self.status_combo)
        form.addRow("厂商", self.vendor_edit)
        form.addRow("型号", self.model_edit)
        form.addRow("责任人", self.owner_edit)
        form.addRow("项目/业务", self.project_edit)
        form.addRow("备注", self.remark_edit)
        root.addLayout(form)

        self.hint = Hint("", "error")
        self.hint.hide()
        root.addWidget(self.hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply(self) -> None:
        patch: dict[str, object] = {}
        if self.type_combo.currentText() != _KEEP:
            patch["dev_type"] = self.type_combo.currentText()
        if self.status_combo.currentText() != _KEEP:
            patch["status"] = self.status_combo.currentText()
        for key, widget in (
            ("vendor", self.vendor_edit),
            ("model", self.model_edit),
            ("owner", self.owner_edit),
            ("project", self.project_edit),
            ("remark", self.remark_edit),
        ):
            text = widget.text().strip()
            if text:
                patch[key] = text

        if not patch:
            self.hint.set_kind("warn", "至少填一个要修改的字段")
            self.hint.show()
            return

        try:
            self.changed = self.backend.bulk_update_devices(self.device_ids, patch)
        except BackendError as exc:
            self.hint.set_kind("error", str(exc))
            self.hint.show()
            return
        self.accept()


class BulkRackDialog(QDialog):
    """选一个目标机柜，按设备高度自动找连续空位。"""

    def __init__(self, backend: Backend, device_ids: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.device_ids = device_ids
        self.placed: list[tuple[int, int]] = []
        self.failed: list[tuple[str, str]] = []

        self.setWindowTitle(f"批量上架 {len(device_ids)} 台设备")
        self.setMinimumWidth(460)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(
            Hint("从机柜底部往上找连续空位，放不下的会单独列出，不影响其他设备。", "info")
        )

        self.cabinet_combo = QComboBox()
        for cab in backend.list_cabinets():
            place = " / ".join(filter(None, (cab.room_name, cab.row_name)))
            self.cabinet_combo.addItem(f"{place} / {cab.name}（{cab.u_total}U）", cab.id)
        self.cabinet_combo.currentIndexChanged.connect(self._update_preview)
        root.addWidget(self.cabinet_combo)

        self.preview = muted("")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        self.hint = Hint("", "error")
        self.hint.hide()
        root.addWidget(self.hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("开始上架")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_preview()

    def _update_preview(self) -> None:
        cabinet_id = self.cabinet_combo.currentData()
        if cabinet_id is None:
            self.preview.setText("还没有机柜，先去「机房机柜」建一个")
            return
        slots = self.backend.free_slots(int(cabinet_id))
        text = "、".join(f"{s.u_start}-{s.u_end}U" for s in slots) or "无空位"
        self.preview.setText(f"目标机柜当前空闲区间：{text}")

    def _apply(self) -> None:
        cabinet_id = self.cabinet_combo.currentData()
        if cabinet_id is None:
            self.hint.set_kind("error", "请先选择目标机柜")
            self.hint.show()
            return
        try:
            self.placed, self.failed = self.backend.auto_rack(self.device_ids, int(cabinet_id))
        except BackendError as exc:
            self.hint.set_kind("error", str(exc))
            self.hint.show()
            return
        self.accept()
