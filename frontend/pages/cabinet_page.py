"""机柜视图页：单柜 / 整列并排、拖拽上架、预留、图片导出。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.constants import DEVICE_TYPE_COLORS
from backend.models import CabinetLayout, Device, DeviceQuery, Reservation

from .. import theme
from ..dialogs import DeviceDialog, ReservationDialog
from ..widgets.common import Card, muted
from ..widgets.rack_export import export_pdf, export_png
from ..widgets.rack_view import DragPayload, RackView
from ..widgets.unracked_list import UnrackedList


class CabinetPage(QWidget):
    data_changed = pyqtSignal()
    # 在设备对话框里现加了类型，别的页面的下拉和配色要跟上
    types_changed = pyqtSignal()

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._layouts: list[CabinetLayout] = []
        self._views: list[RackView] = []
        self._u_height = 22
        self._mode = "单柜"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_legend())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_rack_area())
        splitter.addWidget(self._build_side_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([900, 320])
        root.addWidget(splitter, 1)

    # ---------- 工具栏 ----------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.room_combo = QComboBox()
        self.room_combo.setFixedWidth(150)
        self.room_combo.currentIndexChanged.connect(self._on_room_changed)
        self.row_combo = QComboBox()
        self.row_combo.setFixedWidth(120)
        self.row_combo.currentIndexChanged.connect(self._on_row_changed)
        self.cabinet_combo = QComboBox()
        self.cabinet_combo.setFixedWidth(180)
        self.cabinet_combo.currentIndexChanged.connect(lambda _: self.reload())

        bar.addWidget(QLabel("机房"))
        bar.addWidget(self.room_combo)
        bar.addWidget(QLabel("列"))
        bar.addWidget(self.row_combo)

        self.single_btn = QPushButton("单柜")
        self.row_btn = QPushButton("整列")
        for btn, mode in ((self.single_btn, "单柜"), (self.row_btn, "整列")):
            btn.setCheckable(True)
            btn.setFixedWidth(56)
            btn.clicked.connect(lambda _, m=mode: self._set_mode(m))
        self.single_btn.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.single_btn)
        group.addButton(self.row_btn)
        bar.addWidget(self.single_btn)
        bar.addWidget(self.row_btn)

        self.cabinet_label = QLabel("机柜")
        bar.addWidget(self.cabinet_label)
        bar.addWidget(self.cabinet_combo)

        bar.addWidget(QLabel("行高"))
        self.height_slider = QSlider(Qt.Orientation.Horizontal)
        self.height_slider.setRange(14, 34)
        self.height_slider.setValue(self._u_height)
        self.height_slider.setFixedWidth(90)
        self.height_slider.valueChanged.connect(self._on_height_changed)
        bar.addWidget(self.height_slider)

        bar.addStretch(1)

        new_device_btn = QPushButton("新增设备")
        new_device_btn.setObjectName("primary")
        new_device_btn.clicked.connect(lambda: self._open_device_dialog(None))
        bar.addWidget(new_device_btn)

        new_reservation_btn = QPushButton("新增预留")
        new_reservation_btn.clicked.connect(self._new_reservation)
        bar.addWidget(new_reservation_btn)

        png_btn = QPushButton("导出PNG")
        png_btn.clicked.connect(lambda: self._export("png"))
        bar.addWidget(png_btn)
        pdf_btn = QPushButton("导出PDF")
        pdf_btn.clicked.connect(lambda: self._export("pdf"))
        bar.addWidget(pdf_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload_all)
        bar.addWidget(refresh_btn)
        return bar

    def _build_legend(self) -> QWidget:
        self.legend = QWidget()
        layout = QHBoxLayout(self.legend)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._legend_layout = layout
        layout.addStretch(1)
        return self.legend

    def _refresh_legend(self) -> None:
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        used_types: list[str] = []
        for layout in self._layouts:
            for device in layout.devices:
                if device.dev_type not in used_types:
                    used_types.append(device.dev_type)

        for dev_type in used_types:
            chip = QLabel(f"■ {dev_type}")
            chip.setStyleSheet(
                f"color: {DEVICE_TYPE_COLORS.get(dev_type, theme.TEXT)}; font-size: 11px;"
            )
            self._legend_layout.addWidget(chip)
        if any(layout.reservations for layout in self._layouts):
            chip = QLabel("▨ 预留")
            chip.setStyleSheet(f"color: {theme.RESERVATION_COLOR}; font-size: 11px;")
            self._legend_layout.addWidget(chip)
        self._legend_layout.addStretch(1)

    def _build_rack_area(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.rack_container = QWidget()
        self.rack_layout = QHBoxLayout(self.rack_container)
        self.rack_layout.setContentsMargins(2, 2, 2, 12)
        self.rack_layout.setSpacing(18)
        self.rack_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.empty_label = muted("还没有机柜，先到「机房机柜」页建一个")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scroll.setWidget(self.rack_container)
        return self.scroll

    def _build_side_panel(self) -> QWidget:
        card = Card("待上架设备")
        self.unracked = UnrackedList()
        self.unracked.refresh_requested.connect(self._reload_unracked)
        self.unracked.edit_requested.connect(self._open_device_dialog)
        self.unracked.auto_rack_requested.connect(self._auto_rack)
        card.add(self.unracked, 1)
        card.setMinimumWidth(300)
        return card

    # ---------- 选择器联动 ----------

    def reload_all(self) -> None:
        """机房机柜结构变了就重建选择器。"""
        self._load_rooms()
        self.reload()
        self._reload_unracked()

    def _load_rooms(self) -> None:
        current = self.room_combo.currentData()
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        rooms = self.backend.list_rooms()
        for room in rooms:
            self.room_combo.addItem(room.name, room.id)
        if current is not None:
            index = self.room_combo.findData(current)
            if index >= 0:
                self.room_combo.setCurrentIndex(index)
        self.room_combo.blockSignals(False)
        self._load_rows()

    def _load_rows(self) -> None:
        room_id = self.room_combo.currentData()
        current = self.row_combo.currentData()
        self.row_combo.blockSignals(True)
        self.row_combo.clear()
        self.row_combo.addItem("全部列", None)
        if room_id is not None:
            for row in self.backend.list_rows(int(room_id)):
                self.row_combo.addItem(row.name, row.id)
        if current is not None:
            index = self.row_combo.findData(current)
            if index >= 0:
                self.row_combo.setCurrentIndex(index)
        self.row_combo.blockSignals(False)
        self._load_cabinets()

    def _load_cabinets(self) -> None:
        room_id = self.room_combo.currentData()
        row_id = self.row_combo.currentData()
        current = self.cabinet_combo.currentData()
        self.cabinet_combo.blockSignals(True)
        self.cabinet_combo.clear()
        cabinets = self.backend.list_cabinets(
            int(room_id) if room_id is not None else None,
            int(row_id) if row_id is not None else None,
        )
        for cab in cabinets:
            self.cabinet_combo.addItem(f"{cab.name}（{cab.u_total}U）", cab.id)
        if current is not None:
            index = self.cabinet_combo.findData(current)
            if index >= 0:
                self.cabinet_combo.setCurrentIndex(index)
        self.cabinet_combo.blockSignals(False)

    def _on_room_changed(self) -> None:
        self._load_rows()
        self.reload()

    def _on_row_changed(self) -> None:
        self._load_cabinets()
        self.reload()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        single = mode == "单柜"
        self.cabinet_combo.setVisible(single)
        self.cabinet_label.setVisible(single)
        self.reload()

    def _on_height_changed(self, value: int) -> None:
        self._u_height = value
        for view in self._views:
            view.set_u_height(value)

    # ---------- 渲染 ----------

    def current_cabinet_id(self) -> int | None:
        data = self.cabinet_combo.currentData()
        return int(data) if data is not None else None

    def focus_cabinet(self, cabinet_id: int) -> None:
        """从别的页面跳过来时定位到指定机柜。"""
        try:
            cabinet = self.backend.get_cabinet(cabinet_id)
        except BackendError:
            return
        index = self.room_combo.findData(cabinet.room_id)
        if index >= 0:
            self.room_combo.setCurrentIndex(index)
        self._set_mode("单柜")
        self.single_btn.setChecked(True)
        index = self.cabinet_combo.findData(cabinet_id)
        if index >= 0:
            self.cabinet_combo.setCurrentIndex(index)
        self.reload()

    def _target_cabinet_ids(self) -> list[int]:
        if self._mode == "单柜":
            current = self.current_cabinet_id()
            return [current] if current else []
        return [
            self.cabinet_combo.itemData(i) for i in range(self.cabinet_combo.count())
        ]

    def reload(self) -> None:
        ids = [int(i) for i in self._target_cabinet_ids() if i is not None]
        try:
            self._layouts = self.backend.cabinet_layouts(ids)
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            self._layouts = []

        # 清空旧的机柜视图。
        #
        # 这里千万别用 setParent(None)：Qt 里控件一脱离父对象就变成顶层
        # 窗口，系统会为它建一个原生窗口再立刻销毁 —— 拖完设备刷新时
        # 就是一道白框闪过。takeAt 本身已经把控件从布局里摘出来了，
        # 不需要再动父子关系。
        #
        # RackView 每次都重建，用完显式删掉：context_requested 的 lambda
        # 用 v=view 捕获了 view 自己，形成引用环，只靠引用计数收不掉，
        # 得等循环 GC。deleteLater 让回收时机确定下来。
        #
        # empty_label 是复用的，不能删，隐藏起来等下面 addWidget 再显示。
        while self.rack_layout.count():
            item = self.rack_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if widget is self.empty_label:
                widget.hide()
            else:
                widget.deleteLater()
        self._views.clear()

        if not self._layouts:
            self.rack_layout.addWidget(self.empty_label)
            self.empty_label.show()
            self._refresh_legend()
            self.unracked.set_target_enabled(False)
            return

        width = 340 if self._mode == "单柜" else 290
        for layout in self._layouts:
            view = RackView(layout, u_height=self._u_height, width=width)
            view.device_clicked.connect(self._on_device_clicked)
            view.device_double_clicked.connect(lambda d: self._open_device_dialog(d.id))
            view.reservation_clicked.connect(self._edit_reservation)
            view.empty_clicked.connect(self._on_empty_clicked)
            view.device_dropped.connect(self._on_device_dropped)
            view.context_requested.connect(
                lambda target, pos, v=view: self._show_context_menu(target, pos, v)
            )
            self.rack_layout.addWidget(view)
            self._views.append(view)

        self._refresh_legend()
        self.unracked.set_target_enabled(self.current_cabinet_id() is not None)

    def _reload_unracked(self) -> None:
        try:
            devices = self.backend.list_unracked(self.unracked.keyword())
        except BackendError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.unracked.set_devices(devices)
        self.unracked.set_target_enabled(self.current_cabinet_id() is not None)

    def _refresh_after_change(self) -> None:
        self.reload()
        self._reload_unracked()
        self.data_changed.emit()

    # ---------- 交互 ----------

    def _on_device_clicked(self, device: Device) -> None:
        for view in self._views:
            view.set_selected_device(device.id)

    def _run_device_dialog(self, dialog: DeviceDialog) -> None:
        """跑设备对话框并按结果刷新。

        类型可能是在框里现加的，那种情况即使点了取消也要通知出去 ——
        类型已经落库，别的页面的下拉和配色得跟上。
        """
        accepted = dialog.exec()
        if dialog.types_changed:
            self.types_changed.emit()
        if accepted:
            self._refresh_after_change()

    def _on_empty_clicked(self, cabinet_id: int, u_start: int) -> None:
        self._run_device_dialog(
            DeviceDialog(
                self.backend,
                preset_cabinet_id=cabinet_id,
                preset_u_start=u_start,
                parent=self,
            )
        )

    def _open_device_dialog(self, device_id: int | None) -> None:
        preset = None if device_id else self.current_cabinet_id()
        self._run_device_dialog(
            DeviceDialog(
                self.backend, device_id=device_id, preset_cabinet_id=preset, parent=self
            )
        )

    def _copy_device(self, device_id: int) -> None:
        """以这台设备为模板新增一台。副本不带 U 位，先进待上架再拖。"""
        try:
            draft = self.backend.copy_of_device(device_id)
        except BackendError as exc:
            QMessageBox.warning(self, "复制失败", str(exc))
            return
        self._run_device_dialog(
            DeviceDialog(self.backend, copy_from=draft, parent=self)
        )

    def _on_device_dropped(self, payload: DragPayload, cabinet_id: int, u_start: int) -> None:
        try:
            self.backend.move_device(payload.device_id, cabinet_id, u_start)
        except BackendError as exc:
            QMessageBox.warning(self, "移动失败", str(exc))
            return
        self._refresh_after_change()

    def _new_reservation(self) -> None:
        cabinet_id = self.current_cabinet_id()
        if cabinet_id is None:
            QMessageBox.information(self, "提示", "先选一个机柜")
            return
        dialog = ReservationDialog(
            self.backend, preset_cabinet_id=cabinet_id, preset_u_start=1, parent=self
        )
        if dialog.exec():
            self._refresh_after_change()

    def _edit_reservation(self, reservation: Reservation) -> None:
        dialog = ReservationDialog(self.backend, reservation=reservation, parent=self)
        if dialog.exec():
            self._refresh_after_change()

    def _auto_rack(self, device_ids: list[int]) -> None:
        cabinet_id = self.current_cabinet_id()
        if cabinet_id is None:
            QMessageBox.information(self, "提示", "先在左边选一个机柜作为目标")
            return
        try:
            placed, failed = self.backend.auto_rack(device_ids, cabinet_id)
        except BackendError as exc:
            QMessageBox.warning(self, "上架失败", str(exc))
            return

        message = f"成功上架 {len(placed)} 台。"
        if failed:
            detail = "\n".join(f"· {name}：{reason}" for name, reason in failed)
            message += f"\n\n{len(failed)} 台没放下：\n{detail}"
        QMessageBox.information(self, "批量上架", message)
        self._refresh_after_change()

    def _show_context_menu(self, target: object, global_pos, view: RackView) -> None:
        # 菜单和动作都挂在 menu 上（不是 self），菜单销毁时一起回收。
        # 挂在 self 上的话每次右键都会留一份，右键几十次就攒几十份。
        menu = QMenu(self)
        if isinstance(target, Device):
            edit = QAction("编辑设备", menu)
            edit.triggered.connect(lambda: self._open_device_dialog(target.id))
            menu.addAction(edit)

            copy = QAction("复制这台设备", menu)
            copy.triggered.connect(lambda: self._copy_device(target.id))
            menu.addAction(copy)

            unrack = QAction("下架到待上架", menu)
            unrack.triggered.connect(lambda: self._unrack_device(target))
            menu.addAction(unrack)

            menu.addSeparator()
            delete = QAction("删除设备", menu)
            delete.triggered.connect(lambda: self._delete_device(target))
            menu.addAction(delete)
        elif isinstance(target, Reservation):
            edit = QAction("编辑预留", menu)
            edit.triggered.connect(lambda: self._edit_reservation(target))
            menu.addAction(edit)

            convert = QAction("在此位置新增设备", menu)
            convert.triggered.connect(
                lambda: self._convert_reservation(target)
            )
            menu.addAction(convert)

            menu.addSeparator()
            cancel = QAction("取消预留", menu)
            cancel.triggered.connect(lambda: self._delete_reservation(target))
            menu.addAction(cancel)
        else:
            u_start = int(target) if isinstance(target, int) and target > 0 else 1
            add_device = QAction(f"在 {u_start}U 新增设备", menu)
            add_device.triggered.connect(
                lambda: self._on_empty_clicked(view.cabinet_id, u_start)
            )
            menu.addAction(add_device)

            add_reservation = QAction(f"在 {u_start}U 新增预留", menu)
            add_reservation.triggered.connect(
                lambda: self._add_reservation_at(view.cabinet_id, u_start)
            )
            menu.addAction(add_reservation)
        # exec 期间槽函数已经跑完，返回后销毁是安全的
        try:
            menu.exec(global_pos)
        finally:
            menu.deleteLater()

    def _add_reservation_at(self, cabinet_id: int, u_start: int) -> None:
        dialog = ReservationDialog(
            self.backend, preset_cabinet_id=cabinet_id, preset_u_start=u_start, parent=self
        )
        if dialog.exec():
            self._refresh_after_change()

    def _convert_reservation(self, reservation: Reservation) -> None:
        """预留位落实成设备：删掉预留，用同一位置开新增对话框。"""
        answer = QMessageBox.question(
            self,
            "落实预留",
            f"将取消预留「{reservation.label}」并在 {reservation.u_start}U 新增设备，继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.delete_reservation(reservation.id)
        except BackendError as exc:
            QMessageBox.warning(self, "操作失败", str(exc))
            return
        dialog = DeviceDialog(
            self.backend,
            preset_cabinet_id=reservation.cabinet_id,
            preset_u_start=reservation.u_start,
            parent=self,
        )
        dialog.u_size_spin.setValue(reservation.u_size)
        if dialog.project_edit is not None and reservation.project:
            dialog.project_edit.setText(reservation.project)
        dialog.exec()
        if dialog.types_changed:
            self.types_changed.emit()
        # 预留已经删了，无论保存与否都要刷
        self._refresh_after_change()

    def _unrack_device(self, device: Device) -> None:
        try:
            self.backend.move_device(device.id, None, None)
        except BackendError as exc:
            QMessageBox.warning(self, "操作失败", str(exc))
            return
        self._refresh_after_change()

    def _delete_device(self, device: Device) -> None:
        answer = QMessageBox.question(
            self, "删除设备", f"确定删除「{device.name}」？删除后无法恢复。"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.delete_devices([device.id])
        except BackendError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._refresh_after_change()

    def _delete_reservation(self, reservation: Reservation) -> None:
        answer = QMessageBox.question(
            self, "取消预留", f"确定取消预留「{reservation.label}」？"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.delete_reservation(reservation.id)
        except BackendError as exc:
            QMessageBox.warning(self, "操作失败", str(exc))
            return
        self._refresh_after_change()

    # ---------- 导出 ----------

    def _export(self, kind: str) -> None:
        if not self._layouts:
            QMessageBox.information(self, "提示", "当前没有可导出的机柜")
            return

        room = self.room_combo.currentText()
        scope = (
            self._layouts[0].cabinet.name
            if self._mode == "单柜"
            else self.row_combo.currentText()
        )
        title = f"{room} {scope} 机柜图"
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        default_name = f"{title}-{stamp}.{kind}"

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出{kind.upper()}",
            str(Path.home() / "Downloads" / default_name),
            f"{kind.upper()} 文件 (*.{kind})",
        )
        if not path:
            return
        try:
            if kind == "png":
                export_png(self._layouts, path, title, self._u_height)
            else:
                export_pdf(self._layouts, path, title, self._u_height)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")
