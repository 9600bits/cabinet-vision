"""设置页：数据库位置、备份、切库、清空、关于。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError

from ..widgets.common import Card, Hint, muted


class SettingsPage(QWidget):
    data_changed = pyqtSignal()
    database_switched = pyqtSignal()

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_storage_card())
        root.addWidget(self._build_danger_card())
        root.addWidget(self._build_about_card())
        root.addStretch(1)
        self.setMaximumWidth(900)

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
