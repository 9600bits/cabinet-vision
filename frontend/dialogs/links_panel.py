"""连接关系面板。对端可以从台账里选，也可以直接写文本。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import LINK_TYPES
from backend.models import DeviceLink, DeviceQuery

from ..widgets.common import muted

_ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1


class LinksPanel(QWidget):
    def __init__(self, backend: Backend, device_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.device_id = device_id

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 10, 4, 4)
        root.setSpacing(8)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["类型", "本端口", "对端设备", "对端口", "速率", "介质", "备注"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for col, width in enumerate((60, 110, 150, 110, 60, 60)):
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        editor = QHBoxLayout()
        editor.setSpacing(6)
        self.type_combo = QComboBox()
        self.type_combo.addItems(LINK_TYPES)
        self.type_combo.setFixedWidth(76)
        self.local_port = QLineEdit()
        self.local_port.setPlaceholderText("本端口")
        self.local_port.setFixedWidth(104)
        self.peer_combo = QComboBox()
        self.peer_combo.setEditable(True)
        self.peer_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.peer_combo.setPlaceholderText("对端设备，可搜索或直接输入")
        self.peer_combo.lineEdit().textEdited.connect(self._search_peers)
        self.peer_port = QLineEdit()
        self.peer_port.setPlaceholderText("对端口")
        self.peer_port.setFixedWidth(96)
        self.speed_edit = QLineEdit()
        self.speed_edit.setPlaceholderText("速率")
        self.speed_edit.setFixedWidth(62)
        self.medium_edit = QLineEdit()
        self.medium_edit.setPlaceholderText("介质")
        self.medium_edit.setFixedWidth(62)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_link)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected)

        for widget in (
            self.type_combo, self.local_port, self.peer_combo, self.peer_port,
            self.speed_edit, self.medium_edit,
        ):
            editor.addWidget(widget, 1 if widget is self.peer_combo else 0)
        editor.addWidget(add_btn)
        editor.addWidget(del_btn)
        root.addLayout(editor)

        self.incoming_label = muted("")
        self.incoming_label.setWordWrap(True)
        root.addWidget(self.incoming_label)
        root.addWidget(
            muted("对端在台账里就从下拉选，不在台账里（比如运营商设备）直接输入名称即可。")
        )

        self.reload()

    # ---------- 数据 ----------

    def reload(self) -> None:
        try:
            outgoing, incoming = self.backend.list_links(self.device_id)
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return

        self.table.setRowCount(len(outgoing))
        for row, link in enumerate(outgoing):
            values = (
                link.link_type,
                link.local_port or "",
                link.peer_resolved_name or "",
                link.peer_port or "",
                link.speed or "",
                link.medium or "",
                link.remark or "",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(_ROLE_ID, link.id)
                self.table.setItem(row, col, item)

        if incoming:
            parts = [
                f"{i.device_name}"
                f"{' ' + i.local_port if i.local_port else ''}"
                f" → {i.peer_port or ''}"
                for i in incoming
            ]
            self.incoming_label.setText("被以下设备连接：" + "；".join(parts))
            self.incoming_label.show()
        else:
            self.incoming_label.hide()

    def _search_peers(self, text: str) -> None:
        keyword = text.strip()
        if len(keyword) < 1:
            return
        devices = self.backend.query_devices(DeviceQuery(keyword=keyword, limit=20))
        current = self.peer_combo.currentText()
        self.peer_combo.blockSignals(True)
        self.peer_combo.clear()
        for device in devices:
            if device.id == self.device_id:
                continue
            label = device.name + (f" · {device.cabinet_name}" if device.cabinet_name else "")
            self.peer_combo.addItem(label, device.id)
        self.peer_combo.setEditText(current)
        self.peer_combo.blockSignals(False)
        if self.peer_combo.count():
            self.peer_combo.showPopup()

    # ---------- 操作 ----------

    def _resolve_peer(self) -> tuple[int | None, str | None]:
        text = self.peer_combo.currentText().strip()
        index = self.peer_combo.findText(text)
        if index >= 0:
            data = self.peer_combo.itemData(index)
            if data is not None:
                return int(data), None
        return None, text or None

    def _add_link(self) -> None:
        peer_id, peer_name = self._resolve_peer()
        link = DeviceLink(
            id=0,
            device_id=self.device_id,
            local_port=self.local_port.text().strip() or None,
            peer_device_id=peer_id,
            peer_device_name=peer_name,
            peer_port=self.peer_port.text().strip() or None,
            link_type=self.type_combo.currentText(),
            speed=self.speed_edit.text().strip() or None,
            medium=self.medium_edit.text().strip() or None,
        )
        try:
            self.backend.save_link(link)
        except BackendError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        for widget in (self.local_port, self.peer_port, self.speed_edit, self.medium_edit):
            widget.clear()
        self.peer_combo.setEditText("")
        self.reload()

    def _delete_selected(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return
        link_ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                link_ids.append(int(item.data(_ROLE_ID)))
        if not link_ids:
            return
        if QMessageBox.question(
            self, "删除连接", f"确定删除选中的 {len(link_ids)} 条连接记录？"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            for link_id in link_ids:
                self.backend.delete_link(link_id)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
        self.reload()
