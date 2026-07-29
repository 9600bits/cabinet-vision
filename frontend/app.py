"""应用启动：创建 QApplication、装主题、开后端、显示主窗口。"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend import Backend, BackendError

from . import theme
from .main_window import MainWindow

APP_ID = "CabinetVision.App"


def resource_path(rel: str) -> Path:
    """定位随包资源。

    PyInstaller 打包后资源解到 sys._MEIPASS 临时目录，
    源码运行时则在项目根目录，两种情况都要能找到。
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root / rel


def app_icon() -> QIcon:
    """应用图标；文件缺失时返回空图标，不影响启动。"""
    path = resource_path("assets/app.ico")
    return QIcon(str(path)) if path.exists() else QIcon()


def run(db_path: str | Path | None = None) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    # 让 Windows 任务栏用本程序自己的图标分组，
    # 否则源码运行时会归到 python.exe 下、显示 Python 的图标
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001 - 纯装饰性，失败不该影响启动
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("机柜视界")
    app.setOrganizationName("机柜视界")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(theme.STYLESHEET)

    try:
        backend = Backend(db_path)
    except BackendError as exc:
        QMessageBox.critical(None, "启动失败", f"打不开数据库：\n{exc}")
        return 1

    window = MainWindow(backend)
    window.show()
    return app.exec()
