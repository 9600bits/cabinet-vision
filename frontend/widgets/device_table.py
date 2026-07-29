"""设备台账表格模型。

1000+ 行用 QTableView + 自定义模型：筛选和排序都下推到 SQL，
模型只持有当前页的 Device 列表，滚动时不做额外计算。
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QVariant
from PyQt6.QtGui import QBrush, QColor, QFont

from backend.constants import DEVICE_TYPE_COLORS, STATUS_COLORS
from backend.models import Device

from .. import theme

# (表头, 字段名, 宽度, 是否可排序, 对齐)
COLUMNS: tuple[tuple[str, str, int, bool, Qt.AlignmentFlag], ...] = (
    ("设备名", "name", 170, True, Qt.AlignmentFlag.AlignLeft),
    ("类型", "dev_type", 80, True, Qt.AlignmentFlag.AlignCenter),
    ("状态", "status", 70, True, Qt.AlignmentFlag.AlignCenter),
    ("机房", "room_name", 110, True, Qt.AlignmentFlag.AlignLeft),
    ("列", "row_name", 64, True, Qt.AlignmentFlag.AlignCenter),
    ("机柜", "cabinet_name", 84, True, Qt.AlignmentFlag.AlignCenter),
    ("U位", "u_position", 86, True, Qt.AlignmentFlag.AlignCenter),
    ("型号", "model", 150, True, Qt.AlignmentFlag.AlignLeft),
    ("厂商", "vendor", 84, True, Qt.AlignmentFlag.AlignLeft),
    ("管理IP", "mgmt_ip", 116, True, Qt.AlignmentFlag.AlignLeft),
    ("序列号", "sn", 140, True, Qt.AlignmentFlag.AlignLeft),
    ("资产编号", "asset_no", 126, True, Qt.AlignmentFlag.AlignLeft),
    ("功耗W", "power_w", 74, True, Qt.AlignmentFlag.AlignRight),
    ("重量kg", "weight_kg", 76, True, Qt.AlignmentFlag.AlignRight),
    ("责任人", "owner", 80, True, Qt.AlignmentFlag.AlignLeft),
    ("项目/业务", "project", 130, True, Qt.AlignmentFlag.AlignLeft),
    ("上架日期", "install_date", 100, True, Qt.AlignmentFlag.AlignCenter),
    ("保修到期", "warranty_end", 100, True, Qt.AlignmentFlag.AlignCenter),
    ("备注", "remark", 180, False, Qt.AlignmentFlag.AlignLeft),
)

# 排序时给后端的字段名，u_position 要落到真实列
SORT_FIELDS: dict[str, str] = {name: name for _, name, _, _, _ in COLUMNS}
SORT_FIELDS["u_position"] = "u_start"


class DeviceTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[Device] = []

    # ---------- 数据装载 ----------

    def set_devices(self, devices: list[Device]) -> None:
        self.beginResetModel()
        self._rows = devices
        self.endResetModel()

    def device_at(self, row: int) -> Device | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def ids_at(self, rows: list[int]) -> list[int]:
        return [self._rows[r].id for r in rows if 0 <= r < len(self._rows)]

    # ---------- Qt 模型接口 ----------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return QVariant()
        if orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][0]
        return section + 1

    @staticmethod
    def _display(device: Device, field: str) -> str:
        if field == "u_position":
            if device.u_start is None:
                return "未上架"
            span = f"-{device.u_end}" if device.u_size > 1 else ""
            return f"{device.u_start}{span}U"
        value = getattr(device, field, None)
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        device = self._rows[index.row()]
        _, field, _, _, align = COLUMNS[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(device, field)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(align | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if field == "dev_type":
                return QBrush(QColor(DEVICE_TYPE_COLORS.get(device.dev_type, theme.TEXT)))
            if field == "status":
                return QBrush(QColor(STATUS_COLORS.get(device.status, theme.TEXT)))
            if field == "u_position" and device.u_start is None:
                return QBrush(QColor(theme.TEXT_FAINT))
            if device.status == "已下架":
                return QBrush(QColor(theme.TEXT_MUTED))
            return QVariant()

        if role == Qt.ItemDataRole.FontRole:
            if field in ("dev_type", "status"):
                font = QFont()
                font.setBold(True)
                return font
            if field in ("mgmt_ip", "sn", "asset_no", "u_position"):
                font = QFont("Consolas")
                font.setPointSizeF(9.5)
                return font
            return QVariant()

        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"{device.name}"]
            if device.model:
                parts.append(f"型号：{device.model}")
            if device.cabinet_name:
                pos = self._display(device, "u_position")
                parts.append(f"位置：{device.cabinet_name} {pos}")
            if device.remark:
                parts.append(f"备注：{device.remark}")
            return "\n".join(parts)

        return QVariant()

    def sort_field(self, column: int) -> str | None:
        header, field, _, sortable, _ = COLUMNS[column]
        return SORT_FIELDS.get(field) if sortable else None
