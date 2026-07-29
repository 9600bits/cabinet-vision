"""机柜正视图控件。

自绘而不是拼控件，好处是同一套绘制代码能直接输出到 QPixmap（PNG）
和 QPdfWriter（PDF），导出的图和屏幕上看到的完全一致。

U 位从底部往上编号：1U 在最下面，u_total 在最上面。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from PyQt6.QtCore import QMimeData, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from backend.constants import type_color
from backend.models import CabinetLayout, Device, Reservation

from .. import theme

DRAG_MIME = "application/x-cabinet-device"

HEADER_H = 44
FOOTER_H = 22
PAD = 8
LABEL_W = 26


@dataclass(slots=True)
class DragPayload:
    """拖拽时在控件间传递的设备信息。"""

    device_id: int
    u_size: int
    name: str
    from_cabinet_id: int | None = None

    def to_mime(self) -> QMimeData:
        data = QMimeData()
        raw = json.dumps(
            {
                "device_id": self.device_id,
                "u_size": self.u_size,
                "name": self.name,
                "from_cabinet_id": self.from_cabinet_id,
            }
        ).encode("utf-8")
        data.setData(DRAG_MIME, raw)
        data.setText(self.name)
        return data

    @staticmethod
    def from_mime(mime: QMimeData) -> "DragPayload | None":
        if not mime.hasFormat(DRAG_MIME):
            return None
        try:
            obj = json.loads(bytes(mime.data(DRAG_MIME)).decode("utf-8"))
            return DragPayload(
                device_id=int(obj["device_id"]),
                u_size=int(obj["u_size"]),
                name=str(obj["name"]),
                from_cabinet_id=obj.get("from_cabinet_id"),
            )
        except (ValueError, KeyError, TypeError):
            return None


def _status_alpha(status: str) -> int:
    return {"在用": 255, "备用": 200, "故障": 235, "已下架": 90}.get(status, 255)


class RackView(QWidget):
    """一个机柜的正视图。支持点击、拖拽换位、右键菜单。"""

    device_clicked = pyqtSignal(object)  # Device
    device_double_clicked = pyqtSignal(object)
    reservation_clicked = pyqtSignal(object)  # Reservation
    empty_clicked = pyqtSignal(int, int)  # cabinet_id, u_start
    device_dropped = pyqtSignal(object, int, int)  # DragPayload, cabinet_id, u_start
    context_requested = pyqtSignal(object, QPoint)  # 命中对象(Device/Reservation/int) , 全局坐标

    def __init__(
        self,
        layout: CabinetLayout,
        u_height: int = 22,
        width: int = 300,
        read_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout = layout
        self._u_height = u_height
        self._read_only = read_only
        self._selected_device_id: int | None = None
        self._hover_u: int | None = None
        self._drop_u: int | None = None
        self._drop_size: int = 0
        self._drop_valid = False
        self._press_pos: QPoint | None = None
        self._press_device: Device | None = None

        self.setMouseTracking(True)
        self.setAcceptDrops(not read_only)
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._recalc_height()

    # ---------- 数据与尺寸 ----------

    @property
    def cabinet_id(self) -> int:
        return self._layout.cabinet.id

    def set_layout_data(self, layout: CabinetLayout) -> None:
        self._layout = layout
        self._recalc_height()
        self.update()

    def set_u_height(self, value: int) -> None:
        self._u_height = max(12, min(40, value))
        self._recalc_height()
        self.update()

    def set_selected_device(self, device_id: int | None) -> None:
        self._selected_device_id = device_id
        self.update()

    def _recalc_height(self) -> None:
        body = self._layout.cabinet.u_total * self._u_height
        self.setFixedHeight(HEADER_H + body + FOOTER_H + PAD * 2)

    def content_size(self) -> tuple[int, int]:
        """导出时用的画布尺寸。"""
        return self.width(), self.height()

    # ---------- 坐标换算 ----------

    def _body_rect(self) -> QRect:
        return QRect(
            PAD,
            HEADER_H,
            self.width() - PAD * 2,
            self._layout.cabinet.u_total * self._u_height,
        )

    def _u_rect(self, u_start: int, u_size: int) -> QRect:
        """某段 U 位对应的矩形。U 越大越靠上。"""
        body = self._body_rect()
        u_total = self._layout.cabinet.u_total
        top = body.top() + (u_total - (u_start + u_size - 1)) * self._u_height
        return QRect(
            body.left() + LABEL_W,
            top + 1,
            body.width() - LABEL_W - 2,
            u_size * self._u_height - 2,
        )

    def _u_at(self, pos: QPoint) -> int | None:
        body = self._body_rect()
        if not body.contains(pos.x(), pos.y()):
            return None
        offset_from_top = (pos.y() - body.top()) // self._u_height
        u = self._layout.cabinet.u_total - int(offset_from_top)
        return u if 1 <= u <= self._layout.cabinet.u_total else None

    def _taken_map(self) -> dict[int, object]:
        mapping: dict[int, object] = {}
        for d in self._layout.racked_devices:
            assert d.u_start is not None
            for u in range(d.u_start, d.u_start + d.u_size):
                mapping[u] = d
        for r in self._layout.reservations:
            for u in range(r.u_start, r.u_end + 1):
                mapping[u] = r
        return mapping

    def _hit_test(self, pos: QPoint) -> object | None:
        u = self._u_at(pos)
        if u is None:
            return None
        return self._taken_map().get(u)

    def _can_place(self, payload: DragPayload, u_start: int) -> bool:
        if u_start < 1 or u_start + payload.u_size - 1 > self._layout.cabinet.u_total:
            return False
        taken = self._taken_map()
        for u in range(u_start, u_start + payload.u_size):
            hit = taken.get(u)
            if hit is None:
                continue
            if isinstance(hit, Device) and hit.id == payload.device_id:
                continue
            return False
        return True

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.render_to(painter)
        painter.end()

    def render_to(self, painter: QPainter, for_export: bool = False) -> None:
        """把机柜画到任意 painter 上，导出复用这里。"""
        cab = self._layout.cabinet
        width = self.width()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.CARD_BG))
        painter.drawRoundedRect(0, 0, width, self.height(), 8, 8)
        painter.setPen(QPen(QColor(theme.BORDER)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, width - 1, self.height() - 1, 8, 8)

        # 标题区
        title_font = QFont(painter.font())
        title_font.setPointSizeF(10.5)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QPen(QColor(theme.TEXT)))
        painter.drawText(QRect(PAD + 2, 6, width - PAD * 2, 20),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         cab.name)

        sub_font = QFont(painter.font())
        sub_font.setPointSizeF(7.8)
        sub_font.setBold(False)
        painter.setFont(sub_font)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
        place = " / ".join(filter(None, (cab.room_name, cab.row_name)))
        summary = (
            f"{place + ' · ' if place else ''}{cab.u_total}U · "
            f"用{self._layout.used_u} 留{self._layout.reserved_u} 空{self._layout.free_u}"
        )
        painter.drawText(QRect(PAD + 2, 24, width - PAD * 2 - 4, 16),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         summary)

        # 机柜框体
        body = self._body_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.RACK_BODY_BG))
        painter.drawRect(body)

        # U 位刻度
        scale_font = QFont(painter.font())
        scale_font.setPointSizeF(6.8)
        painter.setFont(scale_font)
        taken = self._taken_map()
        for index in range(cab.u_total):
            u = cab.u_total - index
            y = body.top() + index * self._u_height
            if not for_export and self._hover_u == u and u not in taken and not self._read_only:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#e6f4ff"))
                painter.drawRect(body.left(), y, body.width(), self._u_height)
            painter.setPen(QPen(QColor(theme.RACK_GRID)))
            painter.drawLine(body.left(), y + self._u_height, body.right(), y + self._u_height)
            painter.setPen(QPen(QColor(theme.TEXT_FAINT)))
            painter.drawText(
                QRect(body.left(), y, LABEL_W - 4, self._u_height),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                str(u),
            )

        painter.setPen(QPen(QColor(theme.RACK_FRAME)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(body)

        self._draw_reservations(painter)
        self._draw_devices(painter)

        if not for_export and self._drop_u is not None:
            self._draw_drop_ghost(painter)

        # 底部功率承重
        painter.setFont(sub_font)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
        power = f"{self._layout.power_used_w:g}W"
        if cab.power_limit_w:
            power += f" / {cab.power_limit_w:g}W"
        weight = f"{self._layout.weight_used_kg:g}kg"
        if cab.weight_limit_kg:
            weight += f" / {cab.weight_limit_kg:g}kg"
        painter.drawText(
            QRect(PAD + 2, body.bottom() + 3, width - PAD * 2, FOOTER_H),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"功率 {power} · 承重 {weight}",
        )

    def _draw_reservations(self, painter: QPainter) -> None:
        font = QFont(painter.font())
        font.setPointSizeF(7.6)
        painter.setFont(font)
        for r in self._layout.reservations:
            rect = self._u_rect(r.u_start, r.u_size)
            painter.setBrush(QBrush(QColor("#fff7e6")))
            pen = QPen(QColor(theme.RESERVATION_COLOR))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QPen(QColor("#ad6800")))
            text = f"{r.label}（{r.u_size}U）"
            painter.drawText(
                rect.adjusted(6, 0, -4, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(font).elidedText(
                    text, Qt.TextElideMode.ElideRight, rect.width() - 10
                ),
            )

    def _draw_devices(self, painter: QPainter) -> None:
        for d in self._layout.racked_devices:
            assert d.u_start is not None
            rect = self._u_rect(d.u_start, d.u_size)
            color = QColor(type_color(d.dev_type))
            color.setAlpha(_status_alpha(d.status))
            painter.setBrush(QBrush(color))
            if d.status == "故障":
                pen = QPen(QColor("#ffffff"))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(1)
                painter.setPen(pen)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 3, 3)

            if self._selected_device_id == d.id:
                pen = QPen(QColor(theme.SELECTION))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

            self._draw_device_text(painter, d, rect)

    def _draw_device_text(self, painter: QPainter, d: Device, rect: QRect) -> None:
        name_font = QFont(painter.font())
        name_font.setPointSizeF(7.8)
        name_font.setBold(True)
        two_lines = rect.height() >= 30

        painter.setFont(name_font)
        painter.setPen(QPen(QColor("#ffffff")))
        name_rect = (
            QRect(rect.left() + 6, rect.top() + 2, rect.width() - 10, 14)
            if two_lines
            else rect.adjusted(6, 0, -4, 0)
        )
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(name_font).elidedText(
                d.name, Qt.TextElideMode.ElideRight, name_rect.width()
            ),
        )

        if not two_lines:
            return
        meta_font = QFont(painter.font())
        meta_font.setPointSizeF(7.0)
        meta_font.setBold(False)
        painter.setFont(meta_font)
        pen = QPen(QColor(255, 255, 255, 205))
        painter.setPen(pen)
        meta = " · ".join(filter(None, (d.model, d.mgmt_ip, f"{d.u_size}U")))
        meta_rect = QRect(rect.left() + 6, rect.top() + 15, rect.width() - 10, 13)
        painter.drawText(
            meta_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(meta_font).elidedText(
                meta, Qt.TextElideMode.ElideRight, meta_rect.width()
            ),
        )

    def _draw_drop_ghost(self, painter: QPainter) -> None:
        assert self._drop_u is not None
        rect = self._u_rect(self._drop_u, max(1, self._drop_size))
        color = QColor(theme.DROP_OK if self._drop_valid else theme.DROP_BAD)
        fill = QColor(color)
        fill.setAlpha(60)
        pen = QPen(color)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, 3, 3)

        font = QFont(painter.font())
        font.setPointSizeF(7.8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(color.darker(130)))
        if self._drop_valid:
            end = self._drop_u + self._drop_size - 1
            text = f"{self._drop_u}U" if self._drop_size == 1 else f"{self._drop_u}U-{end}U"
        else:
            text = "放不下"
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    # ---------- 交互 ----------

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        u = self._u_at(pos)
        if u != self._hover_u:
            self._hover_u = u
            self.update()
        self._update_tooltip(pos)

        # 按住并移动一定距离才启动拖拽，避免误触
        if (
            not self._read_only
            and self._press_device is not None
            and self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (pos - self._press_pos).manhattanLength() > 8
        ):
            self._start_drag(self._press_device)
        super().mouseMoveEvent(event)

    def _update_tooltip(self, pos: QPoint) -> None:
        hit = self._hit_test(pos)
        if isinstance(hit, Device):
            lines = [
                f"<b>{hit.name}</b>",
                f"{hit.u_start}U-{hit.u_end}U（{hit.u_size}U）· {hit.dev_type} · {hit.status}",
            ]
            for label, value in (
                ("型号", hit.model),
                ("IP", hit.mgmt_ip),
                ("序列号", hit.sn),
                ("责任人", hit.owner),
                ("项目", hit.project),
            ):
                if value:
                    lines.append(f"{label}：{value}")
            self.setToolTip("<br>".join(lines))
        elif isinstance(hit, Reservation):
            lines = [
                f"<b>预留：{hit.label}</b>",
                f"{hit.u_start}U-{hit.u_end}U（{hit.u_size}U）",
            ]
            if hit.project:
                lines.append(f"项目：{hit.project}")
            if hit.owner:
                lines.append(f"责任人：{hit.owner}")
            if hit.planned_date:
                lines.append(f"计划上架：{hit.planned_date}")
            self.setToolTip("<br>".join(lines))
        else:
            u = self._u_at(pos)
            self.setToolTip(f"{u}U 空闲，点击可在此新增设备" if u else "")

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_u = None
        self._press_device = None
        self._press_pos = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_test(pos)
            self._press_pos = pos
            self._press_device = hit if isinstance(hit, Device) else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_test(pos)
            if isinstance(hit, Device):
                self._selected_device_id = hit.id
                self.update()
                self.device_clicked.emit(hit)
            elif isinstance(hit, Reservation):
                self.reservation_clicked.emit(hit)
            else:
                u = self._u_at(pos)
                if u is not None and not self._read_only:
                    self.empty_clicked.emit(self.cabinet_id, u)
        self._press_device = None
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        hit = self._hit_test(event.position().toPoint())
        if isinstance(hit, Device):
            self.device_double_clicked.emit(hit)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        pos = event.pos()
        hit = self._hit_test(pos)
        target: object = hit if hit is not None else (self._u_at(pos) or 0)
        self.context_requested.emit(target, event.globalPos())

    # ---------- 拖拽 ----------

    def _start_drag(self, device: Device) -> None:
        payload = DragPayload(
            device_id=device.id,
            u_size=device.u_size,
            name=device.name,
            from_cabinet_id=device.cabinet_id,
        )
        drag = QDrag(self)
        drag.setMimeData(payload.to_mime())

        rect = self._u_rect(device.u_start or 1, device.u_size)
        pixmap = QPixmap(rect.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(type_color(device.dev_type))
        color.setAlpha(215)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRect(0, 0, rect.width(), rect.height()), 3, 3)
        painter.setPen(QPen(QColor("#ffffff")))
        font = QFont(painter.font())
        font.setPointSizeF(7.8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRect(6, 0, rect.width() - 10, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            device.name,
        )
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(20, rect.height() // 2))

        self._press_device = None
        self._press_pos = None
        # 用完显式删掉：QDrag 的构造参数既是拖拽源也是父对象，不会自动回收。
        # 拖拽是这个界面最常用的操作，漏一次就多一个，还带着 Qt 画拖拽方块
        # 用的那个无标题原生窗口。
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            drag.deleteLater()

    def _drop_target_u(self, pos: QPoint, payload: DragPayload) -> int:
        """按抓取点算落位：鼠标所在 U 作为设备顶部，往下铺 u_size。"""
        u = self._u_at(pos)
        if u is None:
            body = self._body_rect()
            u = 1 if pos.y() > body.bottom() else self._layout.cabinet.u_total
        return max(1, u - (payload.u_size - 1))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        payload = DragPayload.from_mime(event.mimeData())
        if payload is None or self._read_only:
            event.ignore()
            return
        event.acceptProposedAction()
        self._apply_drag_preview(event.position().toPoint(), payload)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        payload = DragPayload.from_mime(event.mimeData())
        if payload is None:
            event.ignore()
            return
        self._apply_drag_preview(event.position().toPoint(), payload)
        event.acceptProposedAction()

    def _apply_drag_preview(self, pos: QPoint, payload: DragPayload) -> None:
        target = self._drop_target_u(pos, payload)
        valid = self._can_place(payload, target)
        if (target, valid, payload.u_size) != (self._drop_u, self._drop_valid, self._drop_size):
            self._drop_u, self._drop_valid, self._drop_size = target, valid, payload.u_size
            self.update()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._clear_drop_state()
        super().dragLeaveEvent(event)

    def _clear_drop_state(self) -> None:
        self._drop_u = None
        self._drop_size = 0
        self._drop_valid = False
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        payload = DragPayload.from_mime(event.mimeData())
        self._clear_drop_state()
        if payload is None or self._read_only:
            event.ignore()
            return
        target = self._drop_target_u(event.position().toPoint(), payload)
        if not self._can_place(payload, target):
            event.ignore()
            return
        event.acceptProposedAction()
        self.device_dropped.emit(payload, self.cabinet_id, target)
