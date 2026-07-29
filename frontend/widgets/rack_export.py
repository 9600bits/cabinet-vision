"""把机柜正视图导出成 PNG / PDF。

复用 RackView.render_to，所以导出结果和屏幕上完全一致。
PDF 走 QPdfWriter，矢量输出，中文不会乱码。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPixmap

from backend.models import CabinetLayout

from .. import theme
from .rack_view import RackView

GAP = 24
MARGIN = 24
TITLE_H = 34
SCALE = 2  # PNG 用 2 倍分辨率，打印清楚


def _build_views(layouts: list[CabinetLayout], u_height: int, width: int) -> list[RackView]:
    return [RackView(item, u_height=u_height, width=width, read_only=True) for item in layouts]


def _canvas_size(views: list[RackView]) -> tuple[int, int]:
    total_w = MARGIN * 2 + sum(v.width() for v in views) + GAP * (len(views) - 1)
    total_h = MARGIN * 2 + TITLE_H + max(v.height() for v in views)
    return total_w, total_h


def _paint_sheet(painter: QPainter, views: list[RackView], title: str, width: int) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRect(0, 0, width, painter.device().height())

    title_font = QFont(theme.FONT_FAMILY.split(",")[0])
    title_font.setPointSizeF(13)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor(theme.TEXT))
    painter.drawText(
        QRect(MARGIN, MARGIN - 8, width - MARGIN * 2, 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        title,
    )

    stamp_font = QFont(theme.FONT_FAMILY.split(",")[0])
    stamp_font.setPointSizeF(8)
    painter.setFont(stamp_font)
    painter.setPen(QColor(theme.TEXT_MUTED))
    painter.drawText(
        QRect(MARGIN, MARGIN - 8, width - MARGIN * 2, 24),
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        f"导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )

    x = MARGIN
    top = MARGIN + TITLE_H
    for view in views:
        painter.save()
        painter.translate(x, top)
        view.render_to(painter, for_export=True)
        painter.restore()
        x += view.width() + GAP


def export_png(
    layouts: list[CabinetLayout], target: str | Path, title: str, u_height: int = 22
) -> Path:
    views = _build_views(layouts, u_height, 300)
    width, height = _canvas_size(views)

    pixmap = QPixmap(width * SCALE, height * SCALE)
    pixmap.setDevicePixelRatio(SCALE)
    pixmap.fill(QColor("#ffffff"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(SCALE, SCALE)
    _paint_sheet(painter, views, title, width)
    painter.end()

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(target), "PNG")
    return target


def export_pdf(
    layouts: list[CabinetLayout], target: str | Path, title: str, u_height: int = 22
) -> Path:
    views = _build_views(layouts, u_height, 300)
    width, height = _canvas_size(views)

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    # 宽图横向，高图纵向
    writer.setPageOrientation(
        QPageLayout.Orientation.Landscape
        if width >= height
        else QPageLayout.Orientation.Portrait
    )
    writer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
    writer.setResolution(300)
    writer.setTitle(title)
    writer.setCreator("机柜视界")

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    page = painter.viewport()
    ratio = min(page.width() / width, page.height() / height)
    painter.scale(ratio, ratio)
    _paint_sheet(painter, views, title, width)
    painter.end()
    return target
