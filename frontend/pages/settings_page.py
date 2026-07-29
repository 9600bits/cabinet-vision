"""设置页：数据库位置、备份、切库、清空、关于。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import FALLBACK_DEVICE_TYPE
from backend.models import DeviceType

from ..dialogs import DeviceTypeDialog
from ..widgets.common import Card, Hint, muted


class SettingsPage(QWidget):
    data_changed = pyqtSignal()
    database_switched = pyqtSignal()
    # 类型清单变了：下拉框和配色都要重建，比 data_changed 影响面更大
    types_changed = pyqtSignal()

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend

        # 加了类型管理后内容超过一屏，套个滚动区
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(12)
        root.addWidget(self._build_storage_card())
        root.addWidget(self._build_types_card())
        root.addWidget(self._build_danger_card())
        root.addWidget(self._build_about_card())
        root.addStretch(1)
        inner.setMaximumWidth(900)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ---------- 存储 ----------

    def _build_storage_card(self) -> Card:
        card = Card("数据存储")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.path_label = QLabel()
        # 路径要能选中复制，方便手动去备份
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)
        self.size_label = QLabel()
        form.addRow("数据库文件", self.path_label)
        form.addRow("文件大小", self.size_label)
        card.add_layout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        backup_btn = QPushButton("备份数据库")
        backup_btn.setObjectName("primary")
        backup_btn.clicked.connect(self._backup)
        open_btn = QPushButton("打开其他数据库文件")
        open_btn.clicked.connect(self._switch_db)
        reveal_btn = QPushButton("在资源管理器中显示")
        reveal_btn.clicked.connect(self._reveal)
        for btn in (backup_btn, open_btn, reveal_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        card.add_layout(buttons)

        card.add(
            Hint(
                "所有数据都在这一个 .db 文件里，复制走就是完整备份。"
                "建议定期备份到网盘或共享盘。恢复时用「打开其他数据库文件」指向备份即可。",
                "info",
            )
        )
        return card

    # ---------- 设备类型 ----------

    def _build_types_card(self) -> Card:
        card = Card("设备类型")
        card.add(
            muted(
                "机柜图按类型配色，台账和筛选也按类型分组。"
                "内置 11 种，可以自己加、改名、换色、删除。"
            )
        )

        self.types_table = QTableWidget(0, 4)
        self.types_table.setHorizontalHeaderLabels(["类型名称", "配色", "设备数", "来源"])
        self.types_table.verticalHeader().setVisible(False)
        self.types_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.types_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.types_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.types_table.setAlternatingRowColors(True)
        header = self.types_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 96), (2, 74), (3, 64)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.types_table.setColumnWidth(col, width)
        self.types_table.setFixedHeight(240)
        self.types_table.itemSelectionChanged.connect(self._on_type_selected)
        self.types_table.doubleClicked.connect(lambda _: self._edit_type())
        card.add(self.types_table)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_btn = QPushButton("新增类型")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_type)
        self.edit_type_btn = QPushButton("编辑")
        self.edit_type_btn.clicked.connect(self._edit_type)
        self.delete_type_btn = QPushButton("删除")
        self.delete_type_btn.setObjectName("danger")
        self.delete_type_btn.clicked.connect(self._delete_type)
        restore_btn = QPushButton("恢复默认类型")
        restore_btn.clicked.connect(self._restore_types)
        for btn in (add_btn, self.edit_type_btn, self.delete_type_btn, restore_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        card.add_layout(buttons)

        card.add(
            Hint(
                f"改名会同步更新台账里用这个类型的设备，不会丢数据。"
                f"删除时那些设备归到「{FALLBACK_DEVICE_TYPE}」。"
                f"「{FALLBACK_DEVICE_TYPE}」本身不能删也不能改名 —— "
                f"识别不出的类型都要有地方归。",
                "info",
            )
        )
        self._on_type_selected()
        return card

    def _selected_type(self) -> DeviceType | None:
        rows = self.types_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.types_table.item(rows[0].row(), 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_type_selected(self) -> None:
        dev_type = self._selected_type()
        self.edit_type_btn.setEnabled(dev_type is not None)
        # 兜底类型可以改色（走编辑），但不能删
        self.delete_type_btn.setEnabled(
            dev_type is not None and dev_type.name != FALLBACK_DEVICE_TYPE
        )

    def reload_types(self) -> None:
        keep = self._selected_type()
        keep_name = keep.name if keep else ""
        try:
            types = self.backend.list_device_types()
        except BackendError as exc:
            QMessageBox.warning(self, "读取类型失败", str(exc))
            return

        self.types_table.blockSignals(True)
        self.types_table.setRowCount(len(types))
        for row, dev_type in enumerate(types):
            name_item = QTableWidgetItem(dev_type.name)
            name_item.setData(Qt.ItemDataRole.UserRole, dev_type)
            self.types_table.setItem(row, 0, name_item)

            color_item = QTableWidgetItem(f"  {dev_type.color}")
            color_item.setBackground(QColor(dev_type.color))
            color_item.setForeground(QColor("#ffffff"))
            color_item.setToolTip(dev_type.color)
            self.types_table.setItem(row, 1, color_item)

            count_item = QTableWidgetItem(str(dev_type.device_count))
            count_item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            )
            self.types_table.setItem(row, 2, count_item)

            source_item = QTableWidgetItem("内置" if dev_type.builtin else "自定义")
            source_item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            )
            self.types_table.setItem(row, 3, source_item)
        self.types_table.blockSignals(False)

        if keep_name:
            for row in range(self.types_table.rowCount()):
                item = self.types_table.item(row, 0)
                if item is not None and item.text() == keep_name:
                    self.types_table.selectRow(row)
                    break
        self._on_type_selected()

    def _add_type(self) -> None:
        dialog = DeviceTypeDialog(self.backend, None, self)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return
        self.reload_types()
        self.types_changed.emit()

    def _edit_type(self) -> None:
        dev_type = self._selected_type()
        if dev_type is None:
            return
        dialog = DeviceTypeDialog(self.backend, dev_type, self)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return
        self.reload_types()
        self.types_changed.emit()
        if dialog.moved_devices:
            QMessageBox.information(
                self,
                "已更新",
                f"类型已改为「{dialog.saved_name}」，"
                f"同时更新了 {dialog.moved_devices} 台设备的类型。",
            )

    def _delete_type(self) -> None:
        dev_type = self._selected_type()
        if dev_type is None:
            return
        if dev_type.device_count:
            question = (
                f"「{dev_type.name}」下面还有 {dev_type.device_count} 台设备。\n"
                f"删除后它们的类型会变成「{FALLBACK_DEVICE_TYPE}」，设备本身不会删。\n\n"
                "确定删除吗？"
            )
        else:
            question = f"确定删除类型「{dev_type.name}」吗？"
        answer = QMessageBox.warning(
            self,
            "删除设备类型",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = self.backend.delete_device_type(dev_type.name)
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self.reload_types()
        self.types_changed.emit()
        if moved:
            self.data_changed.emit()
            QMessageBox.information(
                self,
                "已删除",
                f"类型已删除，{moved} 台设备归到「{FALLBACK_DEVICE_TYPE}」。",
            )

    def _restore_types(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认类型",
            "会把缺失的 11 种内置类型补回来。\n"
            "自己加的类型和改过的配色都不动。\n\n继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            added = self.backend.restore_default_device_types()
        except BackendError as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))
            return
        self.reload_types()
        self.types_changed.emit()
        QMessageBox.information(
            self,
            "已恢复",
            f"补回了 {added} 种内置类型。" if added else "内置类型都在，没有需要补的。",
        )

    def _build_danger_card(self) -> Card:
        card = Card("危险操作")
        card.add(
            muted(
                "清空会删除全部机房、列、机柜、设备、预留和连接记录，只保留空的表结构。"
                "首次启动生成的示例数据也可以用它清掉。"
            )
        )
        row = QHBoxLayout()
        clear_btn = QPushButton("清空所有数据")
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(self._clear_all)
        row.addWidget(clear_btn)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _build_about_card(self) -> Card:
        card = Card("关于")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        form.addRow("名称", QLabel("机柜视界"))
        form.addRow("用途", QLabel("机柜台账与容量规划，单机离线运行，数据只存本地"))
        form.addRow("U 位编号", QLabel("从机柜底部往上数，1U 在最下方"))
        form.addRow("架构", QLabel("PyQt6 前端 + 独立后端服务层，界面不直接碰数据库"))
        self.stats_label = QLabel()
        form.addRow("当前数据", self.stats_label)
        card.add_layout(form)
        return card

    # ---------- 数据 ----------

    def reload(self) -> None:
        self.path_label.setText(str(self.backend.db_path))
        self.size_label.setText(f"{self.backend.db_size_kb()} KB")
        self.reload_types()
        try:
            stats = self.backend.stats()
        except BackendError:
            return
        self.stats_label.setText(
            f"{stats.rooms} 个机房 · {stats.cabinets} 个机柜 · "
            f"{stats.devices} 台设备 · {stats.reservations} 条预留"
        )

    # ---------- 操作 ----------

    def _backup(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "备份数据库",
            str(Path.home() / "Downloads" / f"机柜视界备份-{stamp}.db"),
            "SQLite 数据库 (*.db)",
        )
        if not path:
            return
        try:
            target = self.backend.backup(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "备份失败", str(exc))
            return
        QMessageBox.information(self, "备份完成", f"已备份到：\n{target}")
        self.reload()

    def _switch_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开数据库文件",
            str(Path.home()),
            "SQLite 数据库 (*.db *.sqlite *.sqlite3)",
        )
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "切换数据库",
            f"将切换到：\n{path}\n\n当前库不会被修改，随时可以切回来。继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.switch_database(path)
        except BackendError as exc:
            QMessageBox.warning(self, "切换失败", str(exc))
            return
        self.reload()
        # 新库有自己的类型清单，注册表已在 Backend 里重灌，界面也要跟上
        self.types_changed.emit()
        self.database_switched.emit()
        QMessageBox.information(self, "已切换", f"当前数据库：\n{self.backend.db_path}")

    def _reveal(self) -> None:
        path = self.backend.db_path
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _clear_all(self) -> None:
        answer = QMessageBox.warning(
            self,
            "清空所有数据",
            "这会删掉全部台账数据且无法撤销。\n建议先点上面的「备份数据库」。\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        confirm = QMessageBox.warning(
            self,
            "再确认一次",
            "真的要清空吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.clear_all_data()
        except BackendError as exc:
            QMessageBox.warning(self, "清空失败", str(exc))
            return
        self.reload()
        self.data_changed.emit()
        QMessageBox.information(self, "已清空", "数据已清空，可以开始录入自己的台账了")
