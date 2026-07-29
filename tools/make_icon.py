"""生成应用图标 assets/app.ico。

画的是机柜正视图 —— 和主界面「机柜视图」页同一个意象：
柜体轮廓 + 两侧安装立柱 + 柜内彩色设备条，配色直接取自
backend.constants.DEVICE_TYPE_COLORS，图标和界面是一套视觉。

小尺寸（<= 24px）自动切简化版：少画几条、条更厚，
不然缩到 16x16 全糊成一团灰。

ICO 用 PNG 内嵌手工封装（Qt 的 ico 插件只读不能写），零额外依赖。

用法：
    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath  # noqa: E402

# Windows 图标标准尺寸档位
SIZES = [16, 20, 24, 32, 48, 64, 128, 256]

BG_DARK = "#0d2340"      # 深藏蓝底，浅色和深色任务栏上都压得住
BG_DARK_2 = "#123a63"    # 底色渐变的亮端
RACK_BODY = "#eef2f8"    # 柜体面板
RAIL = "#9aa9bd"         # 安装立柱
VENT = "#cfd8e3"         # 顶部散热格栅

# 柜内设备条：(相对高度权重, 颜色)。顺序 = 从上往下，按真实机柜的
# 常见排布：网络设备在上、服务器在中、存储在下、PDU 收尾。
# 颜色刻意错开色系，相邻两条不同色，缩图时才有层次
BANDS_FULL = [
    (0.9, "#1668dc"),   # 交换机
    (0.9, "#642ab5"),   # 路由器
    (0.8, "#d32029"),   # 防火墙
    (1.5, "#389e0d"),   # 服务器
    (0.9, "#08979c"),   # 负载均衡
    (1.3, "#5b8c00"),   # 存储
    (0.7, "#d46b08"),   # PDU
]

# 简化版：3 条粗的，保留品牌蓝 + 绿 + 橙的辨识度
BANDS_SMALL = [
    (1.0, "#1668dc"),
    (1.0, "#389e0d"),
    (1.0, "#d46b08"),
]


def render(size: int) -> QImage:
    """画一张 size x size 的 RGBA 图标。"""
    # 统一放大 4 倍画再缩，边缘更干净
    ss = 4 if size <= 64 else 2
    px = size * ss

    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 32px 是任务栏 / 资源管理器最常用档位，也走简化版：
    # 7 条设备条在 32px 下条间空隙不足 1px，降采样后会糊成一坨灰
    small = size <= 32

    # ---- 圆角底板 ----
    pad = px * 0.04
    radius = px * (0.20 if not small else 0.16)
    plate = QRectF(pad, pad, px - 2 * pad, px - 2 * pad)
    path = QPainterPath()
    path.addRoundedRect(plate, radius, radius)

    from PyQt6.QtGui import QLinearGradient

    grad = QLinearGradient(plate.topLeft(), plate.bottomRight())
    grad.setColorAt(0.0, QColor(BG_DARK_2))
    grad.setColorAt(1.0, QColor(BG_DARK))
    p.fillPath(path, grad)

    # ---- 柜体 ----
    # 主体要撑满画面，四周只留一圈深色底衬出轮廓。
    # 真机柜是瘦高的（600 x 2000mm），但图标是正方形，
    # 太瘦会两侧空一大片，所以这里压扁成接近 3:4。
    inset_x = plate.width() * (0.17 if not small else 0.15)
    inset_y = plate.height() * (0.10 if not small else 0.09)
    body = QRectF(
        plate.left() + inset_x,
        plate.top() + inset_y,
        plate.width() - 2 * inset_x,
        plate.height() - 2 * inset_y,
    )
    body_radius = px * (0.025 if not small else 0.015)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(RACK_BODY))
    p.drawRoundedRect(body, body_radius, body_radius)

    # ---- 顶部散热格栅（大尺寸才画，小尺寸省掉）----
    content_top = body.top() + body.height() * 0.02
    if not small:
        vent_h = body.height() * 0.055
        vent = QRectF(
            body.left() + body.width() * 0.12,
            body.top() + body.height() * 0.035,
            body.width() * 0.76,
            vent_h,
        )
        p.setBrush(QColor(VENT))
        p.drawRect(vent)
        content_top = vent.bottom() + body.height() * 0.045

    # ---- 两侧安装立柱 ----
    # 立柱外侧留一圈白色柜体边框，不然整个内区被立柱和设备条填满，
    # 「白柜子」的形状就没了，缩小后只剩一团彩条
    margin = body.width() * 0.075
    rail_w = body.width() * 0.065
    content_bottom = body.bottom() - body.height() * 0.055
    p.setBrush(QColor(RAIL))
    for rx in (body.left() + margin, body.right() - margin - rail_w):
        p.drawRect(QRectF(rx, content_top, rail_w, content_bottom - content_top))

    # ---- 柜内设备条 ----
    bands = BANDS_SMALL if small else BANDS_FULL
    inner_gap = body.width() * (0.035 if not small else 0.02)
    slot_left = body.left() + margin + rail_w + inner_gap
    slot_right = body.right() - margin - rail_w - inner_gap
    slot_w = slot_right - slot_left

    total_weight = sum(w for w, _ in bands)
    gap_ratio = 0.22 if not small else 0.26
    n_gap = len(bands) - 1
    avail = (content_bottom - content_top)
    unit = avail / (total_weight + n_gap * gap_ratio)

    y = content_top
    for i, (weight, color) in enumerate(bands):
        h = unit * weight
        r = QRectF(slot_left, y, slot_w, h)
        p.setBrush(QColor(color))
        p.drawRect(r)

        # 大尺寸给设备条加个状态指示灯，细节质感
        if size >= 48:
            led = min(h * 0.30, slot_w * 0.055)
            if led >= 1.2:
                p.setBrush(QColor(255, 255, 255, 200))
                p.drawEllipse(
                    QRectF(r.right() - led * 2.2, r.center().y() - led / 2, led, led)
                )
        y += h + unit * gap_ratio

    p.end()

    return img.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def png_bytes(img: QImage) -> bytes:
    # ba 必须留在局部变量里：QBuffer 只持有引用，
    # 写成 QBuffer(QByteArray()) 临时对象会被 GC 掉，直接段错误
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_ico(images: list[tuple[int, bytes]], target: Path) -> None:
    """手工封装 ICO：ICONDIR + N * ICONDIRENTRY + PNG 数据块。"""
    n = len(images)
    header = struct.pack("<HHH", 0, 1, n)          # reserved, type=1(icon), count
    offset = 6 + 16 * n                            # 数据区起点
    entries, blobs = b"", b""
    for size, data in images:
        # 256 在 ICONDIRENTRY 里写 0
        dim = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset
        )
        blobs += data
        offset += len(data)
    target.write_bytes(header + entries + blobs)


def main() -> int:
    import os

    from PyQt6.QtGui import QGuiApplication

    # QImage 画图也需要 QGuiApplication；离屏跑，不弹窗
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])

    out_dir = ROOT / "assets"
    out_dir.mkdir(exist_ok=True)

    images: list[tuple[int, bytes]] = []
    for size in SIZES:
        img = render(size)
        images.append((size, png_bytes(img)))
        # 顺手存一份 PNG，方便预览和别处复用
        if size in (256, 48):
            img.save(str(out_dir / f"app_{size}.png"), "PNG")

    ico = out_dir / "app.ico"
    build_ico(images, ico)
    print(f"OK  {ico}  {ico.stat().st_size:,} bytes  sizes={SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
