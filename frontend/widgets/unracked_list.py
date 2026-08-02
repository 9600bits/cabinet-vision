"""待上架设备列表。作为拖拽源，把设备拖到机柜空位即可上架。"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDrag, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.constants import type_color
from backend.models import Device

from .. import theme
from .rack_view import DragPayload

_ROLE_DEVICE = int(Qt.ItemDataRole.UserRole) + 1


class _DragList(QListWidget):
    """只负责把选中项打包成拖拽数据。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(3)
        self.setUniformItemSizes(False)
        self.setStyleSheet(
            f"""
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.BORDER};
                border-radius: 5px;
                padding: 6px 8px;
                color: {theme.TEXT};
            }}
            QListWidget::item:hover {{ border-color: {theme.PRIMARY}; background: #f0f7ff; }}
            QListWidget::item:selected {{ border-color: {theme.PRIMARY}; background: #e6f4ff;
                                          color: {theme.TEXT}; }}
            """
        )

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        device: Device = item.data(_ROLE_DEVICE)
        if device is None:
            return

        payload = DragPayload(
            device_id=device.id,
            u_size=device.u_size,
            name=device.name,
            from_cabinet_id=device.cabinet_id,
        )
        drag = QDrag(self)
        drag.setMimeData(payload.to_mime())

        pixmap = QPixmap(190, max(20, device.u_size * 20))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(type_color(device.dev_type))
        color.setAlpha(215)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, pixmap.width() - 1, pixmap.height() - 1, 3, 3)
        font = QFont()
        font.setPointSizeF(8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            pixmap.rect().adjusted(6, 0, -4, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{device.name}  {device.u_size}U",
        )
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(20, pixmap.height() // 2))
        # QDrag 的构造参数是拖拽源，同时也成了父对象，所以它不会自动消失。
        # 不显式删的话每拖一次就在控件上挂一个，拖久了攒一堆；而 Qt 拖拽
        # 期间会建一个无标题的原生窗口来画跟随鼠标的方块，跟着一起漏。
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            drag.deleteLater()


class UnrackedList(QWidget):
    """搜索 + 列表 + 一键上架。"""

    edit_requested = pyqtSignal(int)  # device_id
    auto_rack_requested = pyqtSignal(list)  # device_ids
    refresh_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设备名 / 型号 / 项目")
        self.search.setClearButtonEnabled(True)
        # 击键别立刻整表查询 + 重建列表，停手 280ms 才刷，和设备台账页一致
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self.refresh_requested.emit)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        search_row.addWidget(self.search, 1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        search_row.addWidget(refresh_btn)
        root.addLayout(search_row)

        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.list = _DragList()
        self.list.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self.list, 1)

        self.rack_selected_btn = QPushButton("把选中的上架到当前机柜")
        self.rack_selected_btn.clicked.connect(self._emit_selected)
        root.addWidget(self.rack_selected_btn)

        self.rack_all_btn = QPushButton("全部自动上架到当前机柜")
        self.rack_all_btn.clicked.connect(self._emit_all)
        root.addWidget(self.rack_all_btn)

    # ---------- 数据 ----------

    def keyword(self) -> str:
        return self.search.text().strip()

    def set_devices(self, devices: list[Device]) -> None:
        self.list.clear()
        for device in devices:
            item = QListWidgetItem()
            meta = " · ".join(filter(None, (device.model, device.vendor, device.project)))
            cab = f"（在 {device.cabinet_name} 未定位）" if device.cabinet_name else ""
            item.setText(
                f"{device.dev_type}  {device.name}   {device.u_size}U{cab}\n"
                f"{meta or '无型号信息'}"
            )
            item.setData(_ROLE_DEVICE, device)
            item.setSizeHint(QSize(0, 46))
            item.setToolTip("拖到左边机柜的空位即可上架，双击可编辑")
            self.list.addItem(item)

        self.summary.setText(
            f"共 {len(devices)} 台待上架，拖到机柜空位即可放置"
            if devices
            else "没有待上架设备"
        )
        has_items = bool(devices)
        self.rack_all_btn.setEnabled(has_items)
        self.rack_selected_btn.setEnabled(has_items)

    def set_target_enabled(self, enabled: bool) -> None:
        """没选中机柜时禁用批量上架。"""
        count = self.list.count()
        self.rack_all_btn.setEnabled(enabled and count > 0)
        self.rack_selected_btn.setEnabled(enabled and count > 0)

    # ---------- 事件 ----------

    def _device_ids(self, selected_only: bool) -> list[int]:
        items = (
            self.list.selectedItems()
            if selected_only
            else [self.list.item(i) for i in range(self.list.count())]
        )
        ids = []
        for item in items:
            device: Device = item.data(_ROLE_DEVICE)
            if device is not None:
                ids.append(device.id)
        return ids

    def _emit_selected(self) -> None:
        ids = self._device_ids(True)
        if ids:
            self.auto_rack_requested.emit(ids)

    def _emit_all(self) -> None:
        ids = self._device_ids(False)
        if ids:
            self.auto_rack_requested.emit(ids)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        device: Device = item.data(_ROLE_DEVICE)
        if device is not None:
            self.edit_requested.emit(device.id)
