"""设备类型的新增 / 编辑对话框。

配色除了调色板还留了手填框：机房方案有时要跟甲方的图例对齐，
预设色板未必够用。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PyQt6.QtCore import pyqtSignal

from backend import Backend, BackendError
from backend.constants import DEFAULT_TYPE_COLOR, DEVICE_TYPES, FALLBACK_DEVICE_TYPE
from backend.models import DeviceType

from ..widgets.common import Hint, muted

# 机柜图是深底白字，色板只放中深色，浅色配上白字看不清
_PALETTE: tuple[str, ...] = (
    "#1668dc", "#642ab5", "#d32029", "#08979c", "#389e0d",
    "#5b8c00", "#8c6b52", "#d46b08", "#c41d7f", "#0958d9",
    "#13c2c2", "#722ed1", "#eb2f96", "#ad4e00", "#595959",
)


class _Swatch(QPushButton):
    """色板里的一个小方块。"""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        border = "#000000" if selected else "#d9d9d9"
        width = 2 if selected else 1
        self.setStyleSheet(
            f"background: {self.color}; border: {width}px solid {border};"
            f"border-radius: 4px;"
        )


class DeviceTypeDialog(QDialog):
    """dev_type 为空表示新增，否则是编辑现有类型。"""

    def __init__(
        self,
        backend: Backend,
        dev_type: DeviceType | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.dev_type = dev_type
        self.saved_name: str = ""
        self.moved_devices: int = 0

        self.setWindowTitle("编辑设备类型" if dev_type else "新增设备类型")
        self.setMinimumWidth(420)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("动环监控")
        self.name_edit.setMaxLength(16)
        form.addRow("类型名称 *", self.name_edit)

        self._color = DEFAULT_TYPE_COLOR
        form.addRow("配色", self._build_color_row())
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(30)
        root.addWidget(muted("机柜图里的样子"))
        root.addWidget(self.preview)
        self.name_edit.textChanged.connect(self._refresh_preview)

        self.hint = Hint("", "error")
        self.hint.hide()
        root.addWidget(self.hint)

        # 改名会连带刷台账，事先说清楚
        if dev_type is not None and dev_type.device_count:
            root.addWidget(
                Hint(
                    f"当前有 {dev_type.device_count} 台设备是这个类型。"
                    "改名会同步更新它们，台账不会丢。",
                    "info",
                )
            )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if dev_type is not None:
            self.name_edit.setText(dev_type.name)
            self._set_color(dev_type.color)
            if dev_type.name == FALLBACK_DEVICE_TYPE:
                # 兜底类型只能改色，名字锁住
                self.name_edit.setReadOnly(True)
                self.name_edit.setToolTip("兜底类型不能改名，只能改配色")
        else:
            self._set_color(_PALETTE[0])
        self._refresh_preview()

    # ---------- 界面 ----------

    def _build_color_row(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        grid = QHBoxLayout()
        grid.setSpacing(4)
        self._swatches: list[_Swatch] = []
        for color in _PALETTE:
            swatch = _Swatch(color)
            swatch.clicked.connect(lambda _=False, c=color: self._set_color(c))
            grid.addWidget(swatch)
            self._swatches.append(swatch)
        grid.addStretch(1)
        layout.addLayout(grid)

        manual = QHBoxLayout()
        manual.setSpacing(6)
        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("#1668dc")
        self.color_edit.setMaxLength(7)
        self.color_edit.setFixedWidth(96)
        self.color_edit.textChanged.connect(self._on_color_typed)
        pick_btn = QPushButton("取色…")
        pick_btn.clicked.connect(self._pick_color)
        manual.addWidget(self.color_edit)
        manual.addWidget(pick_btn)
        manual.addStretch(1)
        layout.addLayout(manual)
        return wrap

    def _set_color(self, color: str) -> None:
        self._color = color
        if self.color_edit.text().lower() != color.lower():
            self.color_edit.blockSignals(True)
            self.color_edit.setText(color)
            self.color_edit.blockSignals(False)
        for swatch in self._swatches:
            swatch.set_selected(swatch.color.lower() == color.lower())
        self._refresh_preview()

    def _on_color_typed(self, text: str) -> None:
        text = text.strip()
        if QColor(text).isValid():
            self._set_color(text)

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "选择配色")
        if chosen.isValid():
            self._set_color(chosen.name())

    def _refresh_preview(self) -> None:
        name = self.name_edit.text().strip() or "示例设备"
        self.preview.setText(f"{name}  ·  2U")
        self.preview.setStyleSheet(
            f"background: {self._color}; color: #ffffff; border-radius: 4px;"
            f"font-size: 12px; font-weight: 600;"
        )

    def _fail(self, message: str) -> None:
        self.hint.set_kind("error", message)
        self.hint.show()

    # ---------- 保存 ----------

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._fail("类型名称不能为空")
            return
        try:
            if self.dev_type is None:
                created = self.backend.create_device_type(name, self._color)
                self.saved_name = created.name
            else:
                updated, moved = self.backend.update_device_type(
                    self.dev_type.name, name, self._color
                )
                self.saved_name = updated.name
                self.moved_devices = moved
        except BackendError as exc:
            self._fail(str(exc))
            return
        self.accept()


# 下拉里那一项「就地加类型」的入口文字。用 userData 认它，不靠比文字
_ADD_MARKER = "__add_device_type__"


class DeviceTypeCombo(QComboBox):
    """设备类型下拉，末尾带一个「＋ 新增类型…」。

    为什么不只放在设置页：录设备的时候人就在这个框里，遇到清单里
    没有的类型，让他退出去、跑到设置页加完、再回来重填一遍，
    这个流程没人会走。所以就地能加。
    """

    types_changed = pyqtSignal()

    def __init__(
        self,
        backend: Backend,
        parent: QWidget | None = None,
        keep_option: str = "",
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        # 批量修改那边要一个「保持原值」占位，普通新增不需要
        self._keep_option = keep_option
        self._last_index = 0
        self.reload_types()
        # activated 只在用户点选时发，programmatic 改动不发；
        # 用 currentIndexChanged 会在重建下拉时自己触发自己
        self.activated.connect(self._on_activated)

    # ---------- 选项 ----------

    def reload_types(self, select: str = "") -> None:
        """按当前注册表重建选项。select 指定重建后选中谁。"""
        keep = select or self.current_type()
        self.blockSignals(True)
        self.clear()
        if self._keep_option:
            self.addItem(self._keep_option, "")
        for name in DEVICE_TYPES:
            self.addItem(name, name)
        self.insertSeparator(self.count())
        self.addItem("＋ 新增类型…", _ADD_MARKER)
        self.blockSignals(False)
        self.set_current_type(keep)

    def current_type(self) -> str:
        """当前选中的类型名。「保持原值」和入口项都返回空串。"""
        data = self.currentData()
        if data in (None, "", _ADD_MARKER):
            return ""
        return str(data)

    def set_current_type(self, name: str) -> None:
        index = self.findData(name) if name else -1
        if index < 0:
            index = 0
        self.setCurrentIndex(index)
        self._last_index = index

    # ---------- 就地新增 ----------

    def _on_activated(self, index: int) -> None:
        if self.itemData(index) != _ADD_MARKER:
            self._last_index = index
            return

        # 入口项本身不是一个可选的值，弹框前先把选择退回去，
        # 这样用户取消时下拉不会停在「＋ 新增类型…」上
        self.setCurrentIndex(self._last_index)

        dialog = DeviceTypeDialog(self.backend, None, self)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return
        # 新加的类型直接选上 —— 用户加它就是为了用它
        self.reload_types(select=dialog.saved_name)
        self.types_changed.emit()
