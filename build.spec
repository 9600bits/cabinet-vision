# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 机柜视界。

用法：
    pyinstaller build.spec --noconfirm

产物：dist/机柜视界.exe，单文件、免安装、双击即用。

数据库不在包里：运行时落在 %APPDATA%\\机柜视界\\cabinet_vision.db，
所以升级 exe 不会丢台账，直接覆盖旧文件即可。
"""

ONEFILE = True  # 改 False 出目录版（启动快，但是一堆文件）

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # 图标也打进包：exe 自身的图标由下面 icon= 决定，
    # 这份是给 setWindowIcon 用的（标题栏、Alt+Tab、任务栏）
    datas=[("assets/app.ico", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 用不到的大件全部剔掉，包体从 ~120MB 压到 ~45MB
    excludes=[
        # Qt 只用 QtCore / QtGui / QtWidgets，PDF 走 QtGui 的 QPdfWriter
        "PyQt6.QtNetwork",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuick3D",
        "PyQt6.QtQuickWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebSockets",
        "PyQt6.QtBluetooth",
        "PyQt6.QtNfc",
        "PyQt6.QtPositioning",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSql",
        "PyQt6.QtTest",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
        "PyQt6.Qt3DCore",
        "PyQt6.QtCharts",
        "PyQt6.QtDataVisualization",
        # 其他生态
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "scipy",
        "pytest",
        "setuptools",
        "pip",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="机柜视界",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # 桌面程序，不弹黑框
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon="assets/app.ico",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="机柜视界",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon="assets/app.ico",
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="机柜视界",
    )
