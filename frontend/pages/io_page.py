"""导入导出页：模板下载、预检、正式导入、清单与报表导出。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend import Backend, BackendError
from backend.models import ImportOptions, ImportResult

from ..widgets.common import Card, Hint, muted


class IoPage(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, backend: Backend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._file: Path | None = None
        self._preview: ImportResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_import_side())
        splitter.addWidget(self._build_export_side())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420])
        root.addWidget(splitter)

    # ---------- 导入侧 ----------

    def _build_import_side(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)

        card = Card("Excel 批量导入")
        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        template_btn = QPushButton("① 下载导入模板")
        template_btn.clicked.connect(self._download_template)
        pick_btn = QPushButton("② 选择 Excel 文件")
        pick_btn.setObjectName("primary")
        pick_btn.clicked.connect(self._pick_file)
        step_row.addWidget(template_btn)
        step_row.addWidget(pick_btn)
        step_row.addStretch(1)
        card.add_layout(step_row)

        self.file_label = muted("还没有选择文件")
        card.add(self.file_label)

        options = QVBoxLayout()
        options.setSpacing(6)
        self.create_places = QCheckBox("自动创建缺失的机房 / 列 / 机柜")
        self.create_places.setChecked(True)
        self.create_places.setToolTip("关掉的话，机房或机柜不存在的行会被列为错误")
        options.addWidget(self.create_places)

        u_row = QHBoxLayout()
        u_row.setSpacing(6)
        u_row.addWidget(QLabel("自动创建机柜的默认总U数"))
        self.default_u = QSpinBox()
        self.default_u.setRange(1, 100)
        self.default_u.setValue(42)
        self.default_u.setFixedWidth(80)
        u_row.addWidget(self.default_u)
        u_row.addStretch(1)
        options.addLayout(u_row)

        self.update_existing = QCheckBox("已存在的设备用表里的数据覆盖")
        self.update_existing.setChecked(True)
        self.update_existing.setToolTip("按 序列号 → 资产编号 → 机柜+设备名 依次匹配")
        options.addWidget(self.update_existing)
        card.add_layout(options)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.check_btn = QPushButton("③ 预检（不写入）")
        self.check_btn.setEnabled(False)
        self.check_btn.clicked.connect(self._run_check)
        self.import_btn = QPushButton("④ 正式导入")
        self.import_btn.setObjectName("primary")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._run_import)
        action_row.addWidget(self.check_btn)
        action_row.addWidget(self.import_btn)
        action_row.addStretch(1)
        card.add_layout(action_row)

        self.result_hint = Hint("", "info")
        self.result_hint.hide()
        card.add(self.result_hint)
        layout.addWidget(card)

        error_card = Card("问题明细")
        self.error_table = QTableWidget(0, 3)
        self.error_table.setHorizontalHeaderLabels(["Excel 行号", "字段", "问题"])
        self.error_table.verticalHeader().setVisible(False)
        self.error_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.error_table.setAlternatingRowColors(True)
        self.error_table.setColumnWidth(0, 90)
        self.error_table.setColumnWidth(1, 90)
        self.error_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        error_card.add(self.error_table, 1)
        error_card.add(
            muted("有问题的行不会被导入，其余正常行不受影响。改完 Excel 重新选择文件即可。")
        )
        layout.addWidget(error_card, 1)
        return panel

    # ---------- 导出侧 ----------

    def _build_export_side(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(12)

        export_card = Card("导出")
        devices_btn = QPushButton("导出全部设备台账")
        devices_btn.clicked.connect(self._export_devices)
        capacity_btn = QPushButton("导出容量报表")
        capacity_btn.clicked.connect(self._export_capacity)
        export_card.add(devices_btn)
        export_card.add(capacity_btn)
        export_card.add(
            muted(
                "导出的设备清单和导入模板列结构一致，改完可以直接导回来。\n"
                "机柜正视图的 PNG / PDF 在「机柜视图」页导出。\n"
                "想只导一部分，在「设备台账」页筛选后点「导出当前结果」。"
            )
        )
        layout.addWidget(export_card)

        rules_card = Card("导入规则")
        rules_card.add(
            muted(
                "必填列：机房、机柜编号、设备名。列名支持常见别名，"
                "比如「设备名称」「主机名」都能识别成设备名。"
            )
        )
        rules_card.add(
            muted("U 位从机柜底部往上数，1 是最底层。留空表示暂不上架，会进「待上架」列表。")
        )
        rules_card.add(
            muted(
                "预检会在事务里真跑一遍再回滚，所以同一批数据内部的 U 位重叠"
                "也能提前发现，不会出现导一半污染台账的情况。"
            )
        )
        rules_card.add(muted("去重：优先按序列号匹配，其次资产编号，最后按 机柜 + 设备名。"))
        rules_card.add(muted("状态填「已下架」的设备不占用 U 位，可以和其他设备位置重叠。"))
        layout.addWidget(rules_card)
        layout.addStretch(1)
        return panel

    # ---------- 导入流程 ----------

    def reload(self) -> None:
        """从别的页面切回来时不清状态，保留上次的预检结果。"""

    def _options(self, dry_run: bool) -> ImportOptions:
        return ImportOptions(
            dry_run=dry_run,
            create_missing_places=self.create_places.isChecked(),
            update_existing=self.update_existing.isChecked(),
            default_u_total=self.default_u.value(),
        )

    def _download_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存导入模板",
            str(Path.home() / "Downloads" / "机柜视界-导入模板.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            self.backend.build_import_template(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "生成失败", str(exc))
            return
        QMessageBox.information(self, "模板已保存", f"已保存到：\n{path}")

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的 Excel", str(Path.home()), "Excel 文件 (*.xlsx *.xlsm)"
        )
        if not path:
            return
        self._file = Path(path)
        self._preview = None
        self.file_label.setText(f"已选择：{self._file.name}")
        self.check_btn.setEnabled(True)
        self.import_btn.setEnabled(False)
        self.result_hint.hide()
        self.error_table.setRowCount(0)

    def _run_check(self) -> None:
        if self._file is None:
            return
        try:
            result = self.backend.import_devices(self._file, self._options(True))
        except BackendError as exc:
            QMessageBox.warning(self, "预检失败", str(exc))
            return
        self._preview = result
        self._show_result(result, dry_run=True)
        self.import_btn.setEnabled(result.writable > 0)

    def _run_import(self) -> None:
        if self._file is None:
            return
        try:
            result = self.backend.import_devices(self._file, self._options(False))
        except BackendError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self._show_result(result, dry_run=False)
        self.import_btn.setEnabled(False)
        self.data_changed.emit()

    def _show_result(self, result: ImportResult, dry_run: bool) -> None:
        prefix = "预检结果" if dry_run else "导入完成"
        summary = (
            f"{prefix}：共 {result.total} 行，"
            f"可新增 {result.inserted}，可更新 {result.updated}，"
            f"跳过 {result.skipped}，问题 {len(result.errors)} 行"
        )
        if not dry_run:
            summary = (
                f"{prefix}：新增 {result.inserted}，更新 {result.updated}，"
                f"跳过 {result.skipped}，问题 {len(result.errors)} 行"
            )
        kind = "success" if not result.errors else "warn"
        if dry_run and not result.errors:
            summary += "。全部校验通过，可以正式导入。"
        self.result_hint.set_kind(kind, summary)
        self.result_hint.show()

        self.error_table.setRowCount(len(result.errors))
        for index, error in enumerate(result.errors):
            for col, text in enumerate((str(error.row), error.field_name, error.message)):
                self.error_table.setItem(index, col, QTableWidgetItem(text))

    # ---------- 导出 ----------

    def _export_devices(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出设备台账",
            str(Path.home() / "Downloads" / f"设备台账-{stamp}.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            self.backend.export_devices(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")

    def _export_capacity(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出容量报表",
            str(Path.home() / "Downloads" / f"容量报表-{stamp}.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            self.backend.export_capacity(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")
