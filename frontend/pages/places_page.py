"""机房机柜管理页：左侧机房和列，右侧机柜表。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.models import Cabinet, RackRow, Room

from ..dialogs import BatchCabinetDialog, CabinetDialog, RoomDialog, RowDialog
from ..widgets.common import Card, muted

_ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1

_CAB_HEADERS = (
    ("编号", 110),
    ("列", 90),
    ("列内序号", 80),
    ("总U数", 74),
    ("功率上限", 96),
    ("承重上限", 96),
    ("状态", 70),
    ("备注", 200),
)


class PlacesPage(QWidget):
    data_changed = pyqtSignal()
    cabinet_requested = pyqtSignal(int)

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._rooms: list[Room] = []
        self._rows: list[RackRow] = []
        self._cabinets: list[Cabinet] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        root.addWidget(splitter)

    # ---------- 左侧 ----------

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)

        room_card = Card("机房")
        add_room = QPushButton("新增")
        add_room.clicked.connect(self._add_room)
        room_card.add_header_widget(add_room)
        self.room_list = QListWidget()
        self.room_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.room_list.currentItemChanged.connect(lambda *_: self._on_room_selected())
        self.room_list.itemDoubleClicked.connect(lambda _: self._edit_room())
        room_card.add(self.room_list, 1)

        room_btns = QHBoxLayout()
        room_btns.setSpacing(6)
        edit_room = QPushButton("编辑")
        edit_room.clicked.connect(self._edit_room)
        del_room = QPushButton("删除")
        del_room.setObjectName("danger")
        del_room.clicked.connect(self._delete_room)
        room_btns.addWidget(edit_room)
        room_btns.addWidget(del_room)
        room_btns.addStretch(1)
        room_card.add_layout(room_btns)
        layout.addWidget(room_card, 1)

        row_card = Card("列")
        add_row = QPushButton("新增")
        add_row.clicked.connect(self._add_row)
        row_card.add_header_widget(add_row)
        self.row_list = QListWidget()
        self.row_list.currentItemChanged.connect(lambda *_: self._reload_cabinets())
        self.row_list.itemDoubleClicked.connect(lambda _: self._edit_row())
        row_card.add(self.row_list, 1)

        row_btns = QHBoxLayout()
        row_btns.setSpacing(6)
        edit_row = QPushButton("编辑")
        edit_row.clicked.connect(self._edit_row)
        del_row = QPushButton("删除")
        del_row.setObjectName("danger")
        del_row.clicked.connect(self._delete_row)
        row_btns.addWidget(edit_row)
        row_btns.addWidget(del_row)
        row_btns.addStretch(1)
        row_card.add_layout(row_btns)
        layout.addWidget(row_card, 1)
        return panel

    # ---------- 右侧 ----------

    def _build_right(self) -> QWidget:
        self.cabinet_card = Card("机柜")
        batch_btn = QPushButton("批量建柜")
        batch_btn.clicked.connect(self._batch_create)
        add_btn = QPushButton("新增机柜")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_cabinet)
        self.cabinet_card.add_header_widget(batch_btn)
        self.cabinet_card.add_header_widget(add_btn)

        self.cab_table = QTableWidget(0, len(_CAB_HEADERS))
        self.cab_table.setHorizontalHeaderLabels([h for h, _ in _CAB_HEADERS])
        self.cab_table.verticalHeader().setVisible(False)
        self.cab_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cab_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cab_table.setAlternatingRowColors(True)
        self.cab_table.verticalHeader().setDefaultSectionSize(28)
        for index, (_, width) in enumerate(_CAB_HEADERS):
            self.cab_table.setColumnWidth(index, width)
        self.cab_table.horizontalHeader().setSectionResizeMode(
            len(_CAB_HEADERS) - 1, QHeaderView.ResizeMode.Stretch
        )
        self.cab_table.doubleClicked.connect(lambda _: self._edit_cabinet())
        self.cabinet_card.add(self.cab_table, 1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        view_btn = QPushButton("在机柜视图打开")
        view_btn.clicked.connect(self._open_in_rack_view)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_cabinet)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_cabinet)
        btns.addWidget(view_btn)
        btns.addWidget(edit_btn)
        btns.addWidget(del_btn)
        btns.addStretch(1)
        self.hint = muted("删除机房或机柜时，柜内设备会自动转为「待上架」，不会被删掉。")
        btns.addWidget(self.hint)
        self.cabinet_card.add_layout(btns)
        return self.cabinet_card

    # ---------- 数据加载 ----------

    def reload_all(self) -> None:
        self._reload_rooms()

    def _reload_rooms(self) -> None:
        current = self._current_room_id()
        self.room_list.blockSignals(True)
        self.room_list.clear()
        self._rooms = self.backend.list_rooms()
        for room in self._rooms:
            label = room.name + (f"（{room.code}）" if room.code else "")
            item = QListWidgetItem(label)
            item.setData(_ROLE_ID, room.id)
            if room.location:
                item.setToolTip(room.location)
            self.room_list.addItem(item)
        self.room_list.blockSignals(False)

        if self._rooms:
            index = next(
                (i for i, r in enumerate(self._rooms) if r.id == current), 0
            )
            self.room_list.setCurrentRow(index)
        self._on_room_selected()

    def _on_room_selected(self) -> None:
        self._reload_rows()

    def _reload_rows(self) -> None:
        room_id = self._current_room_id()
        current = self._current_row_id()
        self.row_list.blockSignals(True)
        self.row_list.clear()
        all_item = QListWidgetItem("全部列")
        all_item.setData(_ROLE_ID, None)
        self.row_list.addItem(all_item)
        self._rows = self.backend.list_rows(room_id) if room_id else []
        for row in self._rows:
            item = QListWidgetItem(row.name)
            item.setData(_ROLE_ID, row.id)
            self.row_list.addItem(item)
        self.row_list.blockSignals(False)

        target = 0
        if current is not None:
            for i in range(self.row_list.count()):
                if self.row_list.item(i).data(_ROLE_ID) == current:
                    target = i
                    break
        self.row_list.setCurrentRow(target)
        self._reload_cabinets()

    def _reload_cabinets(self) -> None:
        room_id = self._current_room_id()
        row_id = self._current_row_id()
        self._cabinets = self.backend.list_cabinets(room_id, row_id)

        room_name = next((r.name for r in self._rooms if r.id == room_id), "未选机房")
        self.cabinet_card.set_title(f"机柜（{room_name} · {len(self._cabinets)} 个）")

        table = self.cab_table
        table.setRowCount(len(self._cabinets))
        row_names = {r.id: r.name for r in self._rows}
        for index, cab in enumerate(self._cabinets):
            values = (
                cab.name,
                row_names.get(cab.row_id, "未分列") if cab.row_id else "未分列",
                str(cab.position_in_row),
                f"{cab.u_total}U",
                f"{cab.power_limit_w:g}W" if cab.power_limit_w else "—",
                f"{cab.weight_limit_kg:g}kg" if cab.weight_limit_kg else "—",
                cab.status,
                cab.remark or "",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(_ROLE_ID, cab.id)
                if col in (2, 3, 4, 5):
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                if col == 6:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                table.setItem(index, col, item)

    # ---------- 当前选中 ----------

    def _current_room_id(self) -> int | None:
        item = self.room_list.currentItem()
        if item is None:
            return None
        data = item.data(_ROLE_ID)
        return int(data) if data is not None else None

    def _current_row_id(self) -> int | None:
        item = self.row_list.currentItem()
        if item is None:
            return None
        data = item.data(_ROLE_ID)
        return int(data) if data is not None else None

    def _current_cabinet(self) -> Cabinet | None:
        rows = {index.row() for index in self.cab_table.selectedIndexes()}
        if not rows:
            return None
        index = min(rows)
        return self._cabinets[index] if index < len(self._cabinets) else None

    def _current_room(self) -> Room | None:
        room_id = self._current_room_id()
        return next((r for r in self._rooms if r.id == room_id), None)

    def _current_row(self) -> RackRow | None:
        row_id = self._current_row_id()
        return next((r for r in self._rows if r.id == row_id), None)

    # ---------- 机房操作 ----------

    def _after_change(self) -> None:
        self._reload_rooms()
        self.data_changed.emit()

    def _add_room(self) -> None:
        if RoomDialog(self.backend, parent=self).exec():
            self._after_change()

    def _edit_room(self) -> None:
        room = self._current_room()
        if room is None:
            QMessageBox.information(self, "提示", "先选中一个机房")
            return
        if RoomDialog(self.backend, room=room, parent=self).exec():
            self._after_change()

    def _delete_room(self) -> None:
        room = self._current_room()
        if room is None:
            return
        answer = QMessageBox.warning(
            self,
            "删除机房",
            f"确定删除机房「{room.name}」？\n"
            f"该机房下的列和机柜会一起删除，柜内设备会转为「待上架」保留在台账里。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = self.backend.delete_room(room.id)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        if moved:
            QMessageBox.information(self, "已删除", f"{moved} 台设备已转为待上架")
        self._after_change()

    # ---------- 列操作 ----------

    def _add_row(self) -> None:
        room_id = self._current_room_id()
        if room_id is None:
            QMessageBox.information(self, "提示", "先建一个机房")
            return
        if RowDialog(self.backend, default_room_id=room_id, parent=self).exec():
            self._after_change()

    def _edit_row(self) -> None:
        row = self._current_row()
        if row is None:
            QMessageBox.information(self, "提示", "先选中一个具体的列")
            return
        if RowDialog(self.backend, row=row, parent=self).exec():
            self._after_change()

    def _delete_row(self) -> None:
        row = self._current_row()
        if row is None:
            return
        answer = QMessageBox.question(
            self,
            "删除列",
            f"确定删除列「{row.name}」？该列下的机柜会变成「未分列」，不会被删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.delete_row(row.id)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._after_change()

    # ---------- 机柜操作 ----------

    def _add_cabinet(self) -> None:
        room_id = self._current_room_id()
        if room_id is None:
            QMessageBox.information(self, "提示", "先建一个机房")
            return
        if CabinetDialog(self.backend, default_room_id=room_id, parent=self).exec():
            self._after_change()

    def _edit_cabinet(self) -> None:
        cabinet = self._current_cabinet()
        if cabinet is None:
            QMessageBox.information(self, "提示", "先选中一个机柜")
            return
        if CabinetDialog(self.backend, cabinet=cabinet, parent=self).exec():
            self._after_change()

    def _delete_cabinet(self) -> None:
        cabinet = self._current_cabinet()
        if cabinet is None:
            return
        answer = QMessageBox.warning(
            self,
            "删除机柜",
            f"确定删除机柜「{cabinet.name}」？柜内设备会转为「待上架」保留在台账里。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = self.backend.delete_cabinet(cabinet.id)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        if moved:
            QMessageBox.information(self, "已删除", f"{moved} 台设备已转为待上架")
        self._after_change()

    def _batch_create(self) -> None:
        room_id = self._current_room_id()
        if room_id is None:
            QMessageBox.information(self, "提示", "先建一个机房")
            return
        dialog = BatchCabinetDialog(self.backend, default_room_id=room_id, parent=self)
        if dialog.exec():
            message = f"已创建 {dialog.created} 个机柜。"
            if dialog.skipped:
                message += f"\n\n以下编号已存在，已跳过：\n{'、'.join(dialog.skipped)}"
            QMessageBox.information(self, "批量建柜", message)
            self._after_change()

    def _open_in_rack_view(self) -> None:
        cabinet = self._current_cabinet()
        if cabinet is None:
            QMessageBox.information(self, "提示", "先选中一个机柜")
            return
        self.cabinet_requested.emit(cabinet.id)
