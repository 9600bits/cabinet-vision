"""界面配色与全局样式表。集中放一处，改风格不用翻各个页面。"""

from __future__ import annotations

# 基础色板
PRIMARY = "#1668dc"
PRIMARY_DARK = "#0d4fa8"
BG = "#f5f7fa"
CARD_BG = "#ffffff"
BORDER = "#d9e1ec"
BORDER_LIGHT = "#e8ecf1"
TEXT = "#1f2d3d"
TEXT_MUTED = "#8894a5"
TEXT_FAINT = "#a9b4c2"

SUCCESS = "#389e0d"
WARNING = "#d46b08"
DANGER = "#cf1322"

# 机柜图专用
RACK_BODY_BG = "#f0f3f7"
RACK_GRID = "#e3e9f0"
RACK_FRAME = "#cfd8e3"
DROP_OK = "#52c41a"
DROP_BAD = "#ff4d4f"
SELECTION = "#faad14"
# 预留位的描边色，和 backend.constants.RESERVATION_COLOR 保持一致
RESERVATION_COLOR = "#fa8c16"

FONT_FAMILY = "Microsoft YaHei UI, Microsoft YaHei, PingFang SC, sans-serif"

STYLESHEET = f"""
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QDialog {{
    background: {BG};
}}

/* 左侧导航 */
QListWidget#navList {{
    background: {CARD_BG};
    border: none;
    border-right: 1px solid {BORDER_LIGHT};
    outline: none;
    padding-top: 6px;
}}
QListWidget#navList::item {{
    height: 38px;
    padding-left: 14px;
    color: {TEXT};
    border-left: 3px solid transparent;
}}
QListWidget#navList::item:hover {{
    background: #f0f7ff;
}}
QListWidget#navList::item:selected {{
    background: #e6f4ff;
    color: {PRIMARY};
    border-left: 3px solid {PRIMARY};
    font-weight: 600;
}}

QLabel#brand {{
    font-size: 17px;
    font-weight: 700;
    color: {PRIMARY};
    padding: 14px 14px 12px 14px;
    border-bottom: 1px solid {BORDER_LIGHT};
}}
QLabel#pageTitle {{
    font-size: 16px;
    font-weight: 600;
}}
QLabel#muted {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#statValue {{
    font-size: 24px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#statTitle {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel#sectionTitle {{
    font-size: 13px;
    font-weight: 600;
    padding-bottom: 4px;
}}

/* 卡片 */
QFrame#card {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#hline {{
    background: {BORDER_LIGHT};
    max-height: 1px;
    border: none;
}}

/* 按钮 */
QPushButton {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 12px;
    min-height: 22px;
}}
QPushButton:hover {{
    border-color: {PRIMARY};
    color: {PRIMARY};
}}
QPushButton:pressed {{
    background: #f0f7ff;
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background: #f7f9fc;
    border-color: {BORDER_LIGHT};
}}
QPushButton#primary {{
    background: {PRIMARY};
    border-color: {PRIMARY};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {PRIMARY_DARK};
    border-color: {PRIMARY_DARK};
    color: #ffffff;
}}
QPushButton#danger {{
    color: {DANGER};
    border-color: #ffccc7;
}}
QPushButton#danger:hover {{
    background: #fff1f0;
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#linkBtn {{
    border: none;
    background: transparent;
    color: {PRIMARY};
    padding: 2px 6px;
    text-align: left;
}}
QPushButton#linkBtn:hover {{
    text-decoration: underline;
}}

/* 输入控件 */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 22px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus {{
    border-color: {PRIMARY};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: #f7f9fc;
    color: {TEXT_FAINT};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    selection-background-color: #e6f4ff;
    selection-color: {TEXT};
    outline: none;
}}

/* 表格 */
QTableView {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER_LIGHT};
    selection-background-color: #e6f4ff;
    selection-color: {TEXT};
    alternate-background-color: #fafcff;
}}
QTableView::item {{
    padding: 3px 6px;
}}
QHeaderView::section {{
    background: #fafcff;
    color: {TEXT};
    border: none;
    border-right: 1px solid {BORDER_LIGHT};
    border-bottom: 1px solid {BORDER};
    padding: 6px 6px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: #fafcff;
    border: none;
    border-bottom: 1px solid {BORDER};
}}

/* 滚动条 */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #c9d3e0;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #aebbcc;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: #c9d3e0;
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* 进度条 */
QProgressBar {{
    background: #eef2f7;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 4px;
}}

/* 其他 */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {CARD_BG};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 6px 16px;
    border: 1px solid transparent;
    border-bottom: none;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{
    background: {CARD_BG};
    border-color: {BORDER};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {PRIMARY};
    font-weight: 600;
}}
QCheckBox, QRadioButton {{
    spacing: 6px;
}}
QToolTip {{
    background: #2b3648;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}}
QSplitter::handle {{
    background: {BORDER_LIGHT};
    width: 1px;
}}
QMenu {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #e6f4ff;
    color: {PRIMARY};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_LIGHT};
    margin: 4px 6px;
}}
"""
