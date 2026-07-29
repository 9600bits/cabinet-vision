"""总览页：关键数字、容量偏紧的机柜、类型分布、待办提醒。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import DEVICE_TYPE_COLORS

from .. import theme
from ..widgets.common import Card, StatCard, UsageBar, muted

_ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1


class DashboardPage(QWidget):
    navigate = pyqtSignal(str)
    cabinet_requested = pyqtSignal(int)

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 4, 4)
        root.setSpacing(12)

        root.addLayout(self._build_stats())

        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_tight_card(), 3)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._build_type_card(), 1)
        right.addWidget(self._build_todo_card())
        wrapper = QWidget()
        wrapper.setLayout(right)
        middle.addWidget(wrapper, 2)
        root.addLayout(middle, 1)

        self.footer = muted("")
        root.addWidget(self.footer)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ---------- 界面 ----------

    def _build_stats(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        self.stat_cards: dict[str, StatCard] = {}
        specs = (
            ("rooms", "机房", "places"),
            ("cabinets", "机柜", "places"),
            ("devices", "设备总数", "devices"),
            ("unracked", "待上架", "cabinet"),
            ("faulty", "故障设备", "devices"),
            ("reservations", "U位预留", "capacity"),
        )
        for index, (key, title, target) in enumerate(specs):
            card = StatCard(title)
            card.clicked.connect(lambda t=target: self.navigate.emit(t))
            grid.addWidget(card, 0, index)
            self.stat_cards[key] = card
        return grid

    def _build_tight_card(self) -> Card:
        card = Card("容量偏紧的机柜")
        link = QLabel(f'<a href="capacity" style="color:{theme.PRIMARY};'
                      f'text-decoration:none;">查看全部 ›</a>')
        link.linkActivated.connect(lambda _: self.navigate.emit("capacity"))
        card.add_header_widget(link)

        self.tight_table = QTableWidget(0, 5)
        self.tight_table.setHorizontalHeaderLabels(["机柜", "所属", "设备", "U位占用", "状态"])
        self.tight_table.verticalHeader().setVisible(False)
        self.tight_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tight_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tight_table.setAlternatingRowColors(True)
        self.tight_table.verticalHeader().setDefaultSectionSize(30)
        for index, width in enumerate((110, 120, 60)):
            self.tight_table.setColumnWidth(index, width)
        self.tight_table.setColumnWidth(4, 60)
        self.tight_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.tight_table.doubleClicked.connect(self._on_tight_double_click)
        card.add(self.tight_table, 1)
        card.add(muted("双击机柜可跳到机柜视图"))
        return card

    def _build_type_card(self) -> Card:
        card = Card("设备类型分布")
        self.type_container = QWidget()
        self.type_layout = QVBoxLayout(self.type_container)
        self.type_layout.setContentsMargins(0, 0, 0, 0)
        self.type_layout.setSpacing(6)
        card.add(self.type_container, 1)
        return card

    def _build_todo_card(self) -> Card:
        card = Card("待办提醒")
        self.todo_container = QWidget()
        self.todo_layout = QVBoxLayout(self.todo_container)
        self.todo_layout.setContentsMargins(0, 0, 0, 0)
        self.todo_layout.setSpacing(6)
        card.add(self.todo_container)
        return card

    # ---------- 数据 ----------

    def reload(self) -> None:
        try:
            stats = self.backend.stats()
            tight = self.backend.tightest_cabinets(8)
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return

        accents = {
            "unracked": theme.WARNING if stats.unracked else "",
            "faulty": theme.DANGER if stats.faulty else "",
        }
        for key in self.stat_cards:
            self.stat_cards[key].set_value(getattr(stats, key), accents.get(key, ""))

        self._fill_tight(tight)
        self._fill_types(stats.by_type, stats.devices)
        self._fill_todos(stats)
        self.footer.setText(
            f"数据库：{stats.db_path}（{stats.db_size_kb} KB） · "
            f"U 位编号从机柜底部往上数，1U 在最下方"
        )

    def _fill_tight(self, rows) -> None:
        table = self.tight_table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            name_item = QTableWidgetItem(row.name)
            name_item.setData(_ROLE_ID, row.id)
            table.setItem(index, 0, name_item)
            table.setItem(index, 1, QTableWidgetItem(row.parent_name or ""))
            count = QTableWidgetItem(str(row.device_count))
            count.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            table.setItem(index, 2, count)
            used = row.u_used + row.u_reserved
            table.setCellWidget(
                index, 3, UsageBar(used, row.u_total, f"{used}/{row.u_total}U", row.overload)
            )
            status = QTableWidgetItem("超限" if row.overload else "")
            status.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            if row.overload:
                from PyQt6.QtGui import QBrush, QColor

                status.setForeground(QBrush(QColor(theme.DANGER)))
            table.setItem(index, 4, status)

    def _fill_types(self, by_type: list[tuple[str, int]], total: int) -> None:
        while self.type_layout.count():
            item = self.type_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not by_type:
            self.type_layout.addWidget(muted("还没有设备"))
            return

        for dev_type, count in by_type:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            dot = QLabel("■")
            dot.setStyleSheet(
                f"color: {DEVICE_TYPE_COLORS.get(dev_type, theme.TEXT)}; font-size: 12px;"
            )
            name = QLabel(dev_type)
            name.setFixedWidth(66)
            bar = UsageBar(count, total or 1, f"{count} 台")
            layout.addWidget(dot)
            layout.addWidget(name)
            layout.addWidget(bar, 1)
            self.type_layout.addWidget(row)
        self.type_layout.addStretch(1)

    def _fill_todos(self, stats) -> None:
        while self.todo_layout.count():
            item = self.todo_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        items: list[tuple[str, str, str]] = []
        if stats.devices == 0:
            items.append(("提示", "台账还是空的，可以用 Excel 批量导入，或先建机房机柜", "io"))
        if stats.unracked:
            items.append(("待上架", f"{stats.unracked} 台设备还没有分配机柜位置", "cabinet"))
        if stats.faulty:
            items.append(("故障", f"{stats.faulty} 台设备标记为故障", "devices"))
        if stats.warranty_soon:
            items.append(("保修", f"{stats.warranty_soon} 台设备将在 90 天内脱保", "devices"))
        if not items:
            self.todo_layout.addWidget(muted("暂无待办，台账是齐的"))
            return

        colors = {
            "待上架": theme.WARNING,
            "故障": theme.DANGER,
            "保修": "#d48806",
            "提示": theme.PRIMARY,
        }
        for tag, text, target in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            badge = QLabel(tag)
            badge.setStyleSheet(
                f"background: {colors.get(tag, theme.PRIMARY)}; color: white;"
                f"border-radius: 3px; padding: 1px 6px; font-size: 11px;"
            )
            label = QLabel(
                f'{text}　<a href="{target}" style="color:{theme.PRIMARY};'
                f'text-decoration:none;">去处理 ›</a>'
            )
            label.linkActivated.connect(lambda t: self.navigate.emit(t))
            layout.addWidget(badge)
            layout.addWidget(label, 1)
            self.todo_layout.addWidget(row)

    def _on_tight_double_click(self, index) -> None:
        item = self.tight_table.item(index.row(), 0)
        if item is not None:
            self.cabinet_requested.emit(int(item.data(_ROLE_ID)))
