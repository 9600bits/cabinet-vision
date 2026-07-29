"""主窗口：左侧导航 + 右侧页面栈。

页面之间通过信号联动：某个页面改了数据就通知别的页面刷新，
避免各页面互相持有引用。
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend import Backend

from .pages import (
    CabinetPage,
    CapacityPage,
    DashboardPage,
    DevicesPage,
    IoPage,
    PlacesPage,
    SettingsPage,
)

# (key, 标题, 图标字符)
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "总览", "▦"),
    ("cabinet", "机柜视图", "▥"),
    ("devices", "设备台账", "▤"),
    ("capacity", "容量规划", "◔"),
    ("places", "机房机柜", "▣"),
    ("io", "导入导出", "⇅"),
    ("settings", "设置", "⚙"),
)


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.setWindowTitle("机柜视界 —— 机柜台账与容量规划")
        self.resize(1500, 940)
        self.setMinimumSize(1180, 720)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav())
        layout.addWidget(self._build_pages(), 1)
        self.setCentralWidget(central)

        self._wire_signals()
        self.nav.setCurrentRow(0)

    # ---------- 导航 ----------

    def _build_nav(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(168)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel("▥ 机柜视界")
        brand.setObjectName("brand")
        layout.addWidget(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setIconSize(QSize(16, 16))
        for key, title, icon in NAV_ITEMS:
            item = QListWidgetItem(f"{icon}  {title}")
            item.setData(int(Qt.ItemDataRole.UserRole) + 1, key)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav, 1)

        version = QLabel("v1.1 · 本地离线")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setContentsMargins(0, 0, 0, 10)
        layout.addWidget(version)
        return panel

    def _build_pages(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        layout.addWidget(self.title_label)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.backend)
        self.cabinet = CabinetPage(self.backend)
        self.devices = DevicesPage(self.backend)
        self.capacity = CapacityPage(self.backend)
        self.places = PlacesPage(self.backend)
        self.io = IoPage(self.backend)
        self.settings = SettingsPage(self.backend)

        self._pages: dict[str, QWidget] = {
            "dashboard": self.dashboard,
            "cabinet": self.cabinet,
            "devices": self.devices,
            "capacity": self.capacity,
            "places": self.places,
            "io": self.io,
            "settings": self.settings,
        }
        for key, _, _ in NAV_ITEMS:
            self.stack.addWidget(self._pages[key])
        layout.addWidget(self.stack, 1)
        return container

    # ---------- 信号 ----------

    def _wire_signals(self) -> None:
        self.dashboard.navigate.connect(self.go_to)
        self.dashboard.cabinet_requested.connect(self._open_cabinet)
        self.capacity.cabinet_requested.connect(self._open_cabinet)
        self.places.cabinet_requested.connect(self._open_cabinet)

        # 任一页面改了数据，其他页面下次显示时重新拉
        for page in (self.cabinet, self.devices, self.capacity, self.places, self.io):
            page.data_changed.connect(self._mark_all_stale)
        self.settings.data_changed.connect(self._mark_all_stale)
        self.settings.database_switched.connect(self._on_database_switched)
        self.settings.types_changed.connect(self._on_types_changed)

        self._stale: set[str] = set(self._pages)

    def _on_types_changed(self) -> None:
        """设备类型清单变了：重建类型下拉，配色相关的视图也要重画。

        后端已经把 constants 里的注册表刷过了，这里只管界面。
        """
        self.devices.refresh_device_types()
        self._mark_all_stale()

    def _mark_all_stale(self) -> None:
        """数据变了就把所有页面标记为待刷新，切过去时才真正查库。"""
        current = self._current_key()
        self._stale = {key for key in self._pages if key != current}
        self._refresh_page(current, force=True)

    def _on_database_switched(self) -> None:
        self._stale = set(self._pages)
        self._refresh_page(self._current_key(), force=True)

    def _current_key(self) -> str:
        row = self.nav.currentRow()
        return NAV_ITEMS[row][0] if 0 <= row < len(NAV_ITEMS) else "dashboard"

    def _on_nav_changed(self, row: int) -> None:
        if not 0 <= row < len(NAV_ITEMS):
            return
        key, title, _ = NAV_ITEMS[row]
        self.title_label.setText(title)
        self.stack.setCurrentWidget(self._pages[key])
        self._refresh_page(key)

    def _refresh_page(self, key: str, force: bool = False) -> None:
        if not force and key not in self._stale:
            return
        self._stale.discard(key)
        page = self._pages[key]
        # 结构类页面要重建选择器，其余只刷数据
        if hasattr(page, "reload_all"):
            page.reload_all()
        elif hasattr(page, "reload"):
            page.reload()

    def go_to(self, key: str) -> None:
        for index, (item_key, _, _) in enumerate(NAV_ITEMS):
            if item_key == key:
                self.nav.setCurrentRow(index)
                return

    def _open_cabinet(self, cabinet_id: int) -> None:
        self.go_to("cabinet")
        self.cabinet.reload_all()
        self.cabinet.focus_cabinet(cabinet_id)

    # ---------- 关闭 ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        self.backend.close()
        super().closeEvent(event)
