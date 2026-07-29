"""通用小控件：卡片、统计块、占用条、提示条。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import theme


class Card(QFrame):
    """白底圆角卡片，可带标题和右上角操作区。"""

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
        margins: tuple[int, int, int, int] = (12, 10, 12, 12),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*margins)
        outer.setSpacing(8)

        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        if title:
            outer.addLayout(self.header)
        else:
            self.title_label.hide()

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)
        self.title_label.setVisible(bool(text))

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.body.addLayout(layout, stretch)


class StatCard(Card):
    """总览页的数字卡片，可点击跳转。"""

    clicked = pyqtSignal()

    def __init__(
        self, title: str, value: str = "0", accent: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent=parent, margins=(14, 12, 14, 12))
        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        if accent:
            self.value_label.setStyleSheet(f"color: {accent};")
        self.title_label2 = QLabel(title)
        self.title_label2.setObjectName("statTitle")
        self.add(self.value_label)
        self.add(self.title_label2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: object, accent: str = "") -> None:
        self.value_label.setText(str(value))
        self.value_label.setStyleSheet(f"color: {accent};" if accent else "")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class UsageBar(QWidget):
    """带文字的占用率条，超限变红。表格单元格和卡片里都用它。"""

    def __init__(
        self,
        used: float = 0,
        total: float = 0,
        text: str = "",
        overload: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._used = used
        self._total = total
        self._text = text
        self._overload = overload
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_values(
        self, used: float, total: float, text: str = "", overload: bool = False
    ) -> None:
        self._used, self._total, self._text, self._overload = used, total, text, overload
        self.update()

    @property
    def _ratio(self) -> float:
        if self._total <= 0:
            return 0.0
        return min(self._used / self._total, 1.0)

    def _color(self) -> QColor:
        if self._overload or (self._total > 0 and self._used > self._total):
            return QColor(theme.DANGER)
        pct = self._ratio
        if pct >= 0.9:
            return QColor(theme.WARNING)
        if pct >= 0.7:
            return QColor("#faad14")
        return QColor(theme.PRIMARY)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        text = self._text or (
            f"{self._used:g}/{self._total:g}" if self._total else f"{self._used:g}"
        )
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(text) + 8
        bar_w = max(24, self.width() - text_w)
        bar_h = 8
        top = (self.height() - bar_h) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#eef2f7"))
        painter.drawRoundedRect(0, top, bar_w, bar_h, 4, 4)

        if self._ratio > 0:
            painter.setBrush(self._color())
            painter.drawRoundedRect(0, top, max(3, int(bar_w * self._ratio)), bar_h, 4, 4)

        painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
        painter.drawText(
            bar_w + 6,
            0,
            text_w,
            self.height(),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        painter.end()


class Badge(QLabel):
    """小色块标签，用于类型和状态。"""

    def __init__(self, text: str = "", color: str = theme.PRIMARY, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set_color(color)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(
            f"background: {color}; color: #ffffff; border-radius: 3px;"
            f"padding: 1px 7px; font-size: 11px; font-weight: 600;"
        )


class Hint(QLabel):
    """浅色提示条，用来说明操作或规则。"""

    def __init__(self, text: str = "", kind: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        palette = {
            "info": ("#e6f4ff", "#91caff", theme.TEXT),
            "warn": ("#fffbe6", "#ffe58f", "#874d00"),
            "error": ("#fff1f0", "#ffccc7", "#a8071a"),
            "success": ("#f6ffed", "#b7eb8f", "#237804"),
        }
        bg, border, fg = palette.get(kind, palette["info"])
        self.setStyleSheet(
            f"background: {bg}; border: 1px solid {border}; color: {fg};"
            f"border-radius: 5px; padding: 7px 10px; font-size: 12px;"
        )

    def set_kind(self, kind: str, text: str = "") -> None:
        if text:
            self.setText(text)
        palette = {
            "info": ("#e6f4ff", "#91caff", theme.TEXT),
            "warn": ("#fffbe6", "#ffe58f", "#874d00"),
            "error": ("#fff1f0", "#ffccc7", "#a8071a"),
            "success": ("#f6ffed", "#b7eb8f", "#237804"),
        }
        bg, border, fg = palette.get(kind, palette["info"])
        self.setStyleSheet(
            f"background: {bg}; border: 1px solid {border}; color: {fg};"
            f"border-radius: 5px; padding: 7px 10px; font-size: 12px;"
        )


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("hline")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    return label
