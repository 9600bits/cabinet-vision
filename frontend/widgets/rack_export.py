"""把机柜正视图导出成 PNG / PDF。

复用 RackView.render_to，所以导出结果和屏幕上完全一致。
PDF 走 QPdfWriter，矢量输出，中文不会乱码。

两个坑，都跟「单位」有关，改这个文件前先看一眼：

1. 画布宽度必须把页眉算进去。以前只按机柜宽度求和，机房名一长
   标题就被裁，右对齐的导出时间还会压在标题上。

2. 字号一律用像素（setPixelSize），不能用磅（setPointSizeF）。
   这里所有几何都是像素写死的（PAD、LABEL_W、u_height），而磅是
   物理单位，要乘设备 DPI 才变成画布单位。PDF 是 300 DPI，屏幕是
   96 DPI，同一个磅值在 PDF 里就大 3.1 倍 —— 字比 U 位行还高，
   于是层层叠在一起。像素跟着几何走，两边就一致了。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QRect, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPixmap,
)

from backend.models import CabinetLayout

from .. import theme
from .rack_view import RackView

GAP = 24
MARGIN = 24
TITLE_H = 34
SCALE = 2  # PNG 用 2 倍分辨率，打印清楚

# 和屏幕上「单柜」模式一致。以前写 300，比屏幕窄，副标题
# （机房 · 42U · 用x 留y 空z）放不下会被裁掉尾巴
CARD_WIDTH = 340

TITLE_PX = 17  # 原来是 13pt，×96/72 得到等效像素
STAMP_PX = 11  # 原来是 8pt
TITLE_STAMP_GAP = 16  # 标题和右侧时间戳之间至少留这么多


def _title_font() -> QFont:
    font = QFont(theme.FONT_FAMILY.split(",")[0])
    font.setPixelSize(TITLE_PX)
    font.setBold(True)
    return font


def _stamp_font() -> QFont:
    font = QFont(theme.FONT_FAMILY.split(",")[0])
    font.setPixelSize(STAMP_PX)
    return font


def _stamp_text() -> str:
    return f"导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def _build_views(
    layouts: list[CabinetLayout], u_height: int, width: int = CARD_WIDTH
) -> list[RackView]:
    return [RackView(item, u_height=u_height, width=width, read_only=True) for item in layouts]


def _header_width(title: str) -> int:
    """页眉这一行需要多宽：标题 + 间隔 + 导出时间，都得放得下。"""
    title_w = QFontMetrics(_title_font()).horizontalAdvance(title)
    stamp_w = QFontMetrics(_stamp_font()).horizontalAdvance(_stamp_text())
    return title_w + TITLE_STAMP_GAP + stamp_w


def _canvas_size(views: list[RackView], title: str = "") -> tuple[int, int]:
    racks_w = sum(v.width() for v in views) + GAP * (len(views) - 1)
    # 页眉可能比机柜还宽（机房名长的时候），取两者较大值
    content_w = max(racks_w, _header_width(title))
    total_w = MARGIN * 2 + content_w
    total_h = MARGIN * 2 + TITLE_H + max(v.height() for v in views)
    return total_w, total_h


def _paint_sheet(painter: QPainter, views: list[RackView], title: str, width: int) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRect(0, 0, width, painter.device().height())

    stamp = _stamp_text()
    stamp_w = QFontMetrics(_stamp_font()).horizontalAdvance(stamp)
    header = QRect(MARGIN, MARGIN - 8, width - MARGIN * 2, 24)

    painter.setFont(_title_font())
    painter.setPen(QColor(theme.TEXT))
    # 标题的可用宽度要把时间戳让出来，否则长标题会压到它上面
    painter.drawText(
        QRect(header.left(), header.top(),
              max(40, header.width() - stamp_w - TITLE_STAMP_GAP), header.height()),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        title,
    )

    painter.setFont(_stamp_font())
    painter.setPen(QColor(theme.TEXT_MUTED))
    painter.drawText(
        header,
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        stamp,
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
    views = _build_views(layouts, u_height)
    width, height = _canvas_size(views, title)

    # 不设 devicePixelRatio：painter.scale 已经把内容放大到 SCALE 倍，
    # 再设一次等于叠两层缩放
    pixmap = QPixmap(width * SCALE, height * SCALE)
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
    views = _build_views(layouts, u_height)
    width, height = _canvas_size(views, title)

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
    # 300 DPI 只决定坐标精度，输出仍是矢量。字号用像素，所以
    # 这个值多大都不会影响文字与几何的比例
    writer.setResolution(300)
    writer.setTitle(title)
    writer.setCreator("机柜视界")

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    page = painter.viewport()
    ratio = min(page.width() / width, page.height() / height)
    # 高图会被页高卡住，横向就富余一大片。居中放，别贴在左边
    offset_x = (page.width() - width * ratio) / 2
    offset_y = (page.height() - height * ratio) / 2
    painter.translate(offset_x, offset_y)
    painter.scale(ratio, ratio)
    _paint_sheet(painter, views, title, width)
    painter.end()
    return target
