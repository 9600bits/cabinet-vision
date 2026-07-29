"""GUI 冒烟测试：离屏跑起真实窗口，逐页切换并模拟关键交互。

用法：python tests/test_gui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from backend import Backend  # noqa: E402
from backend.constants import (  # noqa: E402
    DEFAULT_TYPE_COLOR,
    DEVICE_TYPE_COLORS,
    DEVICE_TYPES,
    FALLBACK_DEVICE_TYPE,
    type_color,
)
from backend.models import Device, DeviceQuery  # noqa: E402
from frontend import theme  # noqa: E402
from frontend.dialogs import DeviceDialog, DeviceTypeDialog  # noqa: E402
from frontend.main_window import NAV_ITEMS, MainWindow  # noqa: E402
from frontend.widgets.device_table import COLUMNS as DEVICE_COLUMNS  # noqa: E402
from frontend.widgets.rack_export import export_pdf, export_png  # noqa: E402
from frontend.widgets.rack_view import DragPayload, RackView  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
    else:
        FAILED.append((name, detail or "断言失败"))


def _check_no_leak(window: MainWindow, app: QApplication) -> None:
    """反复右键弹菜单，菜单和动作的数量必须持平而不是往上爬。

    曾经的问题：QMenu 和每个 QAction 都挂在页面上又不销毁，
    右键几十次就攒几十个隐藏控件。

    只比首尾差值，不写死绝对数量 —— 页面结构以后会改，
    写死了会变成天天误报的脆测试。
    """
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QMenu

    window.go_to("cabinet")
    app.processEvents()
    page = window.cabinet
    layouts = page._layouts
    if not layouts:
        _check("右键菜单泄漏检查前置条件", False, "没有机柜可右键")
        return
    view = page._views[0]

    def settled() -> tuple[int, int]:
        # deleteLater 投递的是 DeferredDelete 事件，裸 processEvents
        # 不一定处理它，必须显式冲，否则待删对象会被误算成泄漏
        for _ in range(3):
            app.processEvents()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        return len(page.findChildren(QMenu)), len(page.findChildren(QAction))

    # 直接走页面的真实入口。菜单要 exec 才弹，测试里不能阻塞，
    # 所以用定时器在菜单弹出后立刻关掉它
    def one_round(target: object) -> None:
        QTimer.singleShot(0, lambda: [
            m.close() for m in page.findChildren(QMenu) if m.isVisible()
        ])
        page._show_context_menu(target, QPoint(0, 0), view)

    one_round(layouts[0].devices[0] if layouts[0].devices else 1)
    base = settled()
    for _ in range(10):
        one_round(layouts[0].devices[0] if layouts[0].devices else 1)
    after = settled()

    for name, before_n, after_n in zip(("菜单", "菜单动作"), base, after):
        _check(
            f"反复右键不泄漏{name}",
            after_n <= before_n,
            f"10 轮后从 {before_n} 涨到 {after_n}",
        )

    _check_drag_cleanup(page, view, app)
    _check_no_window_flash(page, app)


def _check_copy_device(window: MainWindow, app: QApplication) -> None:
    """复制设备：入口可见性、预填内容、以及不会动到原设备。"""
    from frontend.dialogs import DeviceDialog

    window.go_to("devices")
    page = window.devices
    backend = page.backend
    # 先清筛选并重载，不然表里剩多少行取决于前面用例留下的状态，
    # selectRow(0) 就会时好时坏
    page._reset_filters()
    page.reload()
    app.processEvents()

    rows = page.model.rowCount()
    _check("设备表有数据可供复制测试", rows >= 2, f"只有 {rows} 行")

    # 入口必须常驻工具栏。放进批量操作条会被隐藏，没人找得到
    _check("复制按钮在没选中时也看得见", page.copy_btn.isVisible())
    page.table.clearSelection()
    app.processEvents()
    _check("没选中时复制按钮置灰", not page.copy_btn.isEnabled())

    def select_rows(selector) -> int:
        """选中并等表格真的把选中状态落下来。

        reload 之后表格要走一轮布局，选中命令可能落在模型重置中间被清掉，
        所以这里重试几轮。不重试的话这个用例会时通时不通。
        """
        for _ in range(10):
            selector()
            app.processEvents()
            got = len(page._selected_rows())
            if got:
                return got
        return len(page._selected_rows())

    if rows >= 1:
        got = select_rows(lambda: page.table.selectRow(0))
        _check(
            "选中一台后复制按钮可用",
            got == 1 and page.copy_btn.isEnabled(),
            f"选中 {got} 行，按钮可用={page.copy_btn.isEnabled()}",
        )

    if rows >= 2:
        multi = select_rows(page.table.selectAll)
        _check("多选时复制按钮置灰", multi > 1 and not page.copy_btn.isEnabled(),
               f"选了 {multi} 台，按钮可用={page.copy_btn.isEnabled()}")
        _check("多选时给出原因", "一台" in page.copy_btn.toolTip(),
               page.copy_btn.toolTip())
    page.table.clearSelection()
    app.processEvents()

    # 预填：拿一台有完整信息的设备
    src = backend.save_device(
        Device(
            id=0, name="GUI-CP-01", dev_type="服务器", u_size=2,
            model="R750", vendor="Dell", sn="SN-GUI-1",
            asset_no="ZC-GUI-1", mgmt_ip="10.8.8.8", power_w=400.0,
            owner="李四", project="乙项目",
        )
    )
    draft = backend.copy_of_device(src.id)
    dialog = DeviceDialog(backend, copy_from=draft, parent=page)
    _check("复制对话框标题正确", dialog.windowTitle() == "复制设备",
           dialog.windowTitle())
    _check("复制模式按新增保存", dialog.device_id is None)
    _check("名字已预填为副本名", dialog.name_edit.text() == "GUI-CP-02",
           dialog.name_edit.text())
    _check("型号已预填", dialog.model_edit.text() == "R750", dialog.model_edit.text())
    _check("厂商已预填", dialog.vendor_edit.text() == "Dell")
    _check("类型已预填", dialog.type_combo.currentText() == "服务器")
    _check("U 数已预填", dialog.u_size_spin.value() == 2)
    _check("责任人已预填", dialog.owner_edit.text() == "李四")
    _check("SN 留空待填", dialog.sn_edit.text() == "", dialog.sn_edit.text())
    _check("资产号留空待填", dialog.asset_edit.text() == "")
    _check("管理 IP 留空待填", dialog.ip_edit.text() == "")
    dialog.reject()
    dialog.deleteLater()

    # 新增模式不该被复制模式影响
    plain = DeviceDialog(backend, parent=page)
    _check("新增对话框标题不变", plain.windowTitle() == "新增设备", plain.windowTitle())
    _check("新增时名字为空", plain.name_edit.text() == "", plain.name_edit.text())
    plain.reject()
    plain.deleteLater()
    app.processEvents()


def _check_no_window_flash(page, app: QApplication) -> None:
    """重建机柜视图时不能让控件短暂变成顶层窗口。

    Qt 里控件一脱离父对象就变成顶层窗口，系统会建一个原生窗口再立刻
    销毁，用户看到的就是一道白框闪过。拖完设备会刷新视图，所以这条
    路径上一旦用了 setParent(None)，每移动一次设备都闪一下。

    检查两层：源码里不出现 setParent(None)，以及重建期间实时抓有没有
    控件变成窗口。
    """
    import inspect

    from PyQt6.QtWidgets import QWidget

    # 注释里会提到这个写法（说明为什么不能用），所以先去掉注释再查代码
    src = inspect.getsource(type(page).reload)
    code_only = "\n".join(
        line.split("#", 1)[0] for line in src.splitlines()
    )
    _check(
        "重建视图不用 setParent(None)",
        "setParent(None)" not in code_only,
        "reload 里有 setParent(None)，控件会短暂变顶层窗口，拖完闪一下",
    )

    # 实时抓：重建过程中任何控件变成 isWindow 都记下来
    caught: list[str] = []
    orig_set_parent = QWidget.setParent

    def spy(self, parent):  # noqa: ANN001
        result = orig_set_parent(self, parent)
        try:
            if parent is None and self.isWindow():
                caught.append(type(self).__name__)
        except RuntimeError:
            pass
        return result

    QWidget.setParent = spy
    try:
        for _ in range(3):
            page.reload()
            app.processEvents()
    finally:
        QWidget.setParent = orig_set_parent

    _check(
        "重建期间没有控件变成顶层窗口",
        not caught,
        f"这些变成了窗口: {sorted(set(caught))}",
    )


def _check_drag_cleanup(page, view, app: QApplication) -> None:
    """拖拽用的 QDrag 必须显式销毁。

    QDrag 的构造参数既是拖拽源也是父对象，不显式删就一直挂在控件上。
    拖拽是这个界面最主要的编辑方式，漏一次多一个。

    exec() 需要真实鼠标，测不了整个拖拽；这里退一步：确认两处拖拽代码
    都在 exec 之后调了 deleteLater，并且 QDrag 真的会随之消失。
    """
    import inspect

    from PyQt6.QtGui import QDrag

    from frontend.widgets import rack_view as rv
    from frontend.widgets import unracked_list as ul

    for label, func in (
        ("机柜视图", rv.RackView._start_drag),
        ("待上架列表", ul._DragList.startDrag),
    ):
        src = inspect.getsource(func)
        _check(
            f"{label}建了 QDrag",
            "QDrag(" in src,
            "没找到 QDrag，拖拽实现可能挪了地方，这个检查要跟着更新",
        )
        _check(
            f"{label}拖拽后销毁 QDrag",
            "deleteLater" in src,
            "exec 之后没有 deleteLater，QDrag 会挂在控件上不走",
        )

    # 再验证 deleteLater 对 QDrag 确实有效（父对象存在也能删掉）
    before = len(view.findChildren(QDrag))
    for _ in range(5):
        d = QDrag(view)
        d.deleteLater()
        del d
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    after = len(view.findChildren(QDrag))
    _check(
        "deleteLater 能回收 QDrag",
        after <= before,
        f"5 个 QDrag 走 deleteLater 后仍剩 {after - before} 个",
    )


def _check_device_types(window: MainWindow, app: QApplication) -> None:
    """设置页加类型 -> 台账筛选下拉和机柜图配色都要跟上。

    这条链路容易断：DEVICE_TYPES 是被十来处按值导入的模块级容器，
    只能就地改；哪天改成重新绑定，这里的断言会立刻红。
    """
    window.go_to("settings")
    app.processEvents()
    settings = window.settings
    backend = window.backend

    rows_before = settings.types_table.rowCount()
    _check("设置页：类型表已填充", rows_before >= 11, str(rows_before))
    _check("设置页：类型表显示设备数",
           settings.types_table.item(0, 2) is not None
           and settings.types_table.item(0, 2).text().isdigit(),
           "设备数列为空")
    _check("设置页：类型表标出内置/自定义",
           settings.types_table.item(0, 3).text() in ("内置", "自定义"),
           settings.types_table.item(0, 3).text())

    # 选中兜底类型时删除按钮要禁用
    for row in range(settings.types_table.rowCount()):
        if settings.types_table.item(row, 0).text() == FALLBACK_DEVICE_TYPE:
            settings.types_table.selectRow(row)
            app.processEvents()
            break
    _check("设置页：兜底类型不可删", not settings.delete_type_btn.isEnabled())
    _check("设置页：兜底类型可编辑（改色）", settings.edit_type_btn.isEnabled())

    # 先过一遍对话框自己的校验与保存，不走后端捷径
    dlg = DeviceTypeDialog(backend, None, settings)
    dlg.name_edit.setText("")
    dlg._save()
    # 离屏且未 exec 的对话框子控件 isVisible 恒为假，只能看文案
    _check("类型框：空名被拦", "不能为空" in dlg.hint.text(), dlg.hint.text())
    _check("类型框：空名不算保存", dlg.saved_name == "", dlg.saved_name)
    dlg.name_edit.setText("交换机")
    dlg._save()
    _check("类型框：重名被拦并提示", "已经存在" in dlg.hint.text(), dlg.hint.text())
    dlg.color_edit.setText("#13c2c2")
    _check("类型框：手填配色生效", dlg._color == "#13c2c2", dlg._color)
    dlg.name_edit.setText("动环监控")
    dlg._save()
    _check("类型框：合法输入保存成功", dlg.saved_name == "动环监控", dlg.saved_name)
    _check("类型框：保存后对话框接受", dlg.result() == int(dlg.DialogCode.Accepted))
    dlg.deleteLater()
    app.processEvents()

    settings.types_changed.emit()
    app.processEvents()
    settings.reload_types()
    app.processEvents()
    _check("设置页：新增后类型表增行",
           settings.types_table.rowCount() == rows_before + 1,
           f"{rows_before} -> {settings.types_table.rowCount()}")

    names = [
        settings.types_table.item(r, 0).text()
        for r in range(settings.types_table.rowCount())
    ]
    _check("设置页：新类型出现在表里", "动环监控" in names, str(names))

    # 台账页的类型筛选下拉必须跟着重建
    window.go_to("devices")
    app.processEvents()
    combo_options = [box.text() for box in window.devices.type_combo._checks]
    _check("台账页：筛选下拉含新类型", "动环监控" in combo_options, str(combo_options))
    _check("台账页：筛选下拉不含已删类型",
           all(name in DEVICE_TYPES for name in combo_options), str(combo_options))

    # 新增设备对话框的下拉是每次打开重建的，也要有
    dialog = DeviceDialog(backend, parent=window.devices)
    dialog_types = [dialog.type_combo.itemText(i) for i in range(dialog.type_combo.count())]
    _check("新增设备框：类型下拉含新类型", "动环监控" in dialog_types, str(dialog_types))
    dialog.deleteLater()
    app.processEvents()

    # 配色要进注册表，机柜图才画得出来
    _check("注册表：新类型有配色",
           DEVICE_TYPE_COLORS.get("动环监控") == "#13c2c2",
           str(DEVICE_TYPE_COLORS.get("动环监控")))
    _check("type_color 认新类型", type_color("动环监控") == "#13c2c2", type_color("动环监控"))
    _check("type_color 兜底认不出的类型",
           type_color("根本不存在的类型") == DEFAULT_TYPE_COLOR,
           type_color("根本不存在的类型"))

    # 用新类型上架一台，机柜图能画出来且用的是新配色
    cabinet_id = backend.list_cabinets()[0].id
    slots = backend.free_slots(cabinet_id)
    if slots:
        dev = backend.save_device(
            Device(id=0, name="GUI-ENV-01", dev_type="动环监控",
                   cabinet_id=cabinet_id, u_start=slots[0].u_start, u_size=1)
        )
        window.go_to("cabinet")
        window.cabinet.reload_all()
        app.processEvents()
        drawn = any(
            d.dev_type == "动环监控"
            for layout in window.cabinet._layouts
            for d in layout.devices
        )
        _check("机柜视图：自定义类型设备能上架并绘制", drawn, "布局里找不到该设备")
        legend = [
            child.text()
            for child in window.cabinet.legend.findChildren(QLabel)
        ]
        _check("机柜视图：图例含新类型",
               any("动环监控" in text for text in legend), str(legend))
        backend.delete_devices([dev.id])

    # 删掉类型，下拉要收回去
    backend.delete_device_type("动环监控")
    window.settings.types_changed.emit()
    app.processEvents()
    window.go_to("devices")
    app.processEvents()
    combo_after = [box.text() for box in window.devices.type_combo._checks]
    _check("台账页：删类型后下拉收回", "动环监控" not in combo_after, str(combo_after))
    window.go_to("settings")
    app.processEvents()


def run(tmp: Path, app: QApplication) -> None:
    backend = Backend(tmp / "gui.db")
    window = MainWindow(backend)
    window.show()
    app.processEvents()

    _check("主窗口创建成功", window.isVisible())
    _check("窗口标题正确", "机柜视界" in window.windowTitle(), window.windowTitle())
    _check("导航项数量一致", window.nav.count() == len(NAV_ITEMS), str(window.nav.count()))

    # ---------- 逐页切换 ----------
    for index, (key, title, _) in enumerate(NAV_ITEMS):
        window.nav.setCurrentRow(index)
        app.processEvents()
        _check(
            f"切到「{title}」页正常",
            window.stack.currentWidget() is window._pages[key],
        )
        _check(f"「{title}」页标题正确", window.title_label.text() == title, window.title_label.text())

    # ---------- 总览页 ----------
    window.go_to("dashboard")
    app.processEvents()
    dash = window.dashboard
    _check("总览：设备数卡片有值", dash.stat_cards["devices"].value_label.text() == "18",
           dash.stat_cards["devices"].value_label.text())
    _check("总览：机柜数卡片有值", dash.stat_cards["cabinets"].value_label.text() == "5")
    _check("总览：待上架卡片有值", dash.stat_cards["unracked"].value_label.text() == "2")
    _check("总览：偏紧机柜表有数据", dash.tight_table.rowCount() == 5,
           str(dash.tight_table.rowCount()))
    _check("总览：类型分布已渲染", dash.type_layout.count() > 0)
    _check("总览：待办有内容", dash.todo_layout.count() > 0)
    _check("总览：页脚显示库路径", "gui.db" in dash.footer.text(), dash.footer.text())

    # ---------- 机柜视图 ----------
    window.go_to("cabinet")
    app.processEvents()
    page = window.cabinet
    _check("机柜页：机房下拉有项", page.room_combo.count() == 1, str(page.room_combo.count()))
    _check("机柜页：列下拉含全部列", page.row_combo.count() == 3, str(page.row_combo.count()))
    _check("机柜页：机柜下拉有 5 项", page.cabinet_combo.count() == 5,
           str(page.cabinet_combo.count()))
    _check("机柜页：单柜模式渲染 1 个视图", len(page._views) == 1, str(len(page._views)))

    view = page._views[0]
    _check("机柜视图控件是 RackView", isinstance(view, RackView))
    _check("机柜视图高度按 U 数计算", view.height() > 42 * 20, str(view.height()))

    # U 位坐标换算：顶部应是最大 U，底部应是 1U
    body = view._body_rect()
    top_u = view._u_at(QPoint(body.center().x(), body.top() + 2))
    bottom_u = view._u_at(QPoint(body.center().x(), body.bottom() - 2))
    _check("U 位换算：顶部是 42U", top_u == 42, f"top_u={top_u}")
    _check("U 位换算：底部是 1U", bottom_u == 1, f"bottom_u={bottom_u}")

    # 命中测试：40U 上应该是 SW-CORE-01
    layout = backend.cabinet_layout(page.current_cabinet_id())
    a01_name = layout.cabinet.name
    hit_rect = view._u_rect(40, 1)
    hit = view._hit_test(hit_rect.center())
    _check("命中测试：40U 命中 SW-CORE-01",
           hit is not None and getattr(hit, "name", "") == "SW-CORE-01",
           str(getattr(hit, "name", hit)))
    empty_hit = view._hit_test(view._u_rect(20, 1).center())
    _check("命中测试：空位返回 None", empty_hit is None, str(empty_hit))

    # 拖拽落位判断
    unracked = backend.list_unracked()
    target = next(d for d in unracked if d.u_size == 2)
    payload = DragPayload(target.id, target.u_size, target.name, None)
    _check("拖拽校验：20U 可放 2U 设备", view._can_place(payload, 20))
    _check("拖拽校验：40U 不可放（已占）", not view._can_place(payload, 40))
    _check("拖拽校验：42U 放 2U 越界", not view._can_place(payload, 42))
    _check("拖拽落位：抓取点换算", view._drop_target_u(view._u_rect(21, 1).center(), payload) == 20,
           str(view._drop_target_u(view._u_rect(21, 1).center(), payload)))

    # 真正触发一次拖拽落地
    before = backend.count_devices(DeviceQuery(unracked_only=True))
    page._on_device_dropped(payload, page.current_cabinet_id(), 20)
    app.processEvents()
    after = backend.count_devices(DeviceQuery(unracked_only=True))
    moved = backend.get_device(target.id)
    _check("拖拽上架：设备落到 20U", moved.u_start == 20, str(moved.u_start))
    _check("拖拽上架：待上架数减少", after == before - 1, f"{before}->{after}")
    _check("拖拽上架：视图已刷新",
           any(d.id == target.id for d in page._layouts[0].racked_devices))

    # 待上架列表
    _check("待上架列表有项", page.unracked.list.count() == after, str(page.unracked.list.count()))

    # 切整列模式
    page._set_mode("整列")
    app.processEvents()
    _check("整列模式渲染多个机柜", len(page._views) == 5, str(len(page._views)))
    _check("整列模式隐藏机柜下拉", not page.cabinet_combo.isVisible())
    page._set_mode("单柜")
    app.processEvents()
    _check("切回单柜模式", len(page._views) == 1, str(len(page._views)))

    # 行高调整
    old_height = page._views[0].height()
    page.height_slider.setValue(30)
    app.processEvents()
    _check("调行高后视图变高", page._views[0].height() > old_height,
           f"{old_height}->{page._views[0].height()}")
    page.height_slider.setValue(22)
    app.processEvents()

    # 图例
    _check("图例已渲染类型", page._legend_layout.count() > 1, str(page._legend_layout.count()))

    # ---------- 导出 PNG / PDF ----------
    layouts = backend.cabinet_layouts([c.id for c in backend.list_cabinets()][:3])
    png = export_png(layouts, tmp / "rack.png", "测试机柜图")
    pdf = export_pdf(layouts, tmp / "rack.pdf", "测试机柜图")
    _check("导出 PNG 成功", png.exists() and png.stat().st_size > 5000, str(png.stat().st_size))
    _check("导出 PDF 成功", pdf.exists() and pdf.stat().st_size > 3000, str(pdf.stat().st_size))
    single = export_png(layouts[:1], tmp / "rack_single.png", "单柜图")
    _check("单柜导出 PNG 成功", single.exists() and single.stat().st_size > 3000)

    # ---------- 设备台账 ----------
    window.go_to("devices")
    app.processEvents()
    dev_page = window.devices
    total = backend.count_devices(DeviceQuery())
    _check("台账：表格行数与库一致", dev_page.model.rowCount() == total,
           f"{dev_page.model.rowCount()} vs {total}")
    _check("台账：列数正确", dev_page.model.columnCount() == 19,
           str(dev_page.model.columnCount()))
    _check("台账：状态栏有统计", "台账共" in dev_page.status_label.text(),
           dev_page.status_label.text())

    # 表格显示内容
    first = dev_page.model.device_at(0)
    _check("台账：能取到首行设备", first is not None)
    idx = dev_page.model.index(0, 0)
    _check("台账：首列显示设备名", dev_page.model.data(idx) == first.name,
           str(dev_page.model.data(idx)))

    # 未上架显示
    dev_page.unracked_check.setChecked(True)
    app.processEvents()
    unracked_count = backend.count_devices(DeviceQuery(unracked_only=True))
    _check("台账：仅未上架筛选生效", dev_page.model.rowCount() == unracked_count,
           f"{dev_page.model.rowCount()} vs {unracked_count}")
    u_col = next(i for i, col in enumerate(DEVICE_COLUMNS) if col[1] == "u_position")
    if dev_page.model.rowCount():
        text = dev_page.model.data(dev_page.model.index(0, u_col))
        _check("台账：未上架显示为「未上架」", text == "未上架", str(text))
    dev_page.unracked_check.setChecked(False)
    app.processEvents()

    # 关键字筛选
    dev_page.search.setText("SW-CORE")
    dev_page.reload()
    app.processEvents()
    _check("台账：关键字筛选生效", 0 < dev_page.model.rowCount() < total,
           str(dev_page.model.rowCount()))

    # 排序
    dev_page._sort_field = "name"
    dev_page._sort_desc = False
    dev_page.reload()
    names = [dev_page.model.device_at(i).name for i in range(dev_page.model.rowCount())]
    _check("台账：按名称升序", names == sorted(names), str(names))

    dev_page._reset_filters()
    app.processEvents()
    _check("台账：重置筛选恢复全部", dev_page.model.rowCount() == total,
           str(dev_page.model.rowCount()))

    # 选中与批量栏
    dev_page.table.selectRow(0)
    app.processEvents()
    _check("台账：选中后批量栏出现", dev_page.bulk_bar.isVisible())
    _check("台账：批量栏计数正确", "已选 1 台" in dev_page.bulk_label.text(),
           dev_page.bulk_label.text())
    _check("台账：能取到选中 id", len(dev_page._selected_ids()) == 1)
    dev_page.table.clearSelection()
    app.processEvents()
    _check("台账：取消选择后批量栏隐藏", not dev_page.bulk_bar.isVisible())

    # 导出当前结果
    export_path = tmp / "devices_export.xlsx"
    backend.export_devices(export_path, dev_page.current_query())
    _check("台账：按当前条件导出成功", export_path.exists())

    # ---------- 容量规划 ----------
    window.go_to("capacity")
    app.processEvents()
    cap = window.capacity
    _check("容量：机柜粒度有 5 行", cap.cap_table.rowCount() == 5, str(cap.cap_table.rowCount()))
    _check("容量：合计行有文字", "合计" in cap.summary.text(), cap.summary.text())
    _check("容量：占用条已放入单元格", cap.cap_table.cellWidget(0, 4) is not None)

    cap._set_scope("机房")
    app.processEvents()
    _check("容量：机房粒度 1 行", cap.cap_table.rowCount() == 1, str(cap.cap_table.rowCount()))
    cap._set_scope("列")
    app.processEvents()
    _check("容量：列粒度 2 行", cap.cap_table.rowCount() == 2, str(cap.cap_table.rowCount()))
    cap._set_scope("预留清单")
    app.processEvents()
    _check("容量：预留清单 2 条", cap.rv_table.rowCount() == 2, str(cap.rv_table.rowCount()))
    _check("容量：预留合计文字", "预留" in cap.summary.text(), cap.summary.text())

    cap._set_scope("机柜")
    cap.overload_only.setChecked(True)
    cap.reload()
    app.processEvents()
    _check("容量：只看超限时无超限项", cap.cap_table.rowCount() == 0,
           str(cap.cap_table.rowCount()))
    cap.overload_only.setChecked(False)
    cap.reload()
    app.processEvents()

    # 跳转联动
    cap._rows and cap.cabinet_requested.emit(cap._rows[0].id)
    app.processEvents()
    _check("容量：双击跳转到机柜视图", window.stack.currentWidget() is window.cabinet)

    # ---------- 机房机柜 ----------
    window.go_to("places")
    app.processEvents()
    places = window.places
    _check("机房页：机房列表 1 项", places.room_list.count() == 1, str(places.room_list.count()))
    _check("机房页：列列表含全部列", places.row_list.count() == 3, str(places.row_list.count()))
    _check("机房页：机柜表 5 行", places.cab_table.rowCount() == 5, str(places.cab_table.rowCount()))
    _check("机房页：机柜表首行是 A01", places.cab_table.item(0, 0).text() == "A01",
           places.cab_table.item(0, 0).text())
    _check("机房页：标题带机房名", "示例机房" in places.cabinet_card.title_label.text(),
           places.cabinet_card.title_label.text())

    # 选中列后机柜表跟着过滤
    places.row_list.setCurrentRow(1)
    app.processEvents()
    _check("机房页：按列过滤机柜", places.cab_table.rowCount() == 3,
           str(places.cab_table.rowCount()))
    places.row_list.setCurrentRow(0)
    app.processEvents()

    # ---------- 导入导出页 ----------
    window.go_to("io")
    app.processEvents()
    io_page = window.io
    _check("导入页：初始禁用预检", not io_page.check_btn.isEnabled())
    _check("导入页：初始禁用导入", not io_page.import_btn.isEnabled())

    template = tmp / "tpl.xlsx"
    backend.build_import_template(template)
    io_page._file = template
    io_page.check_btn.setEnabled(True)
    io_page._run_check()
    app.processEvents()
    _check("导入页：预检模板有结果提示", io_page.result_hint.isVisible())
    _check("导入页：模板示例行可导入", io_page.import_btn.isEnabled())

    # 造一份有错的文件看错误表
    from openpyxl import Workbook

    bad = tmp / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["机房", "机柜编号", "设备名", "起始U位"])
    ws.append(["示例机房", "A01", "GUI-CONFLICT", 40])
    ws.append(["示例机房", "A01", "GUI-OUT", 200])
    wb.save(bad)
    io_page._file = bad
    io_page._run_check()
    app.processEvents()
    _check("导入页：错误表列出 2 行问题", io_page.error_table.rowCount() == 2,
           str(io_page.error_table.rowCount()))
    _check("导入页：错误行号可见", io_page.error_table.item(0, 0).text() in ("2", "3"),
           io_page.error_table.item(0, 0).text())

    # ---------- 设置页 ----------
    window.go_to("settings")
    app.processEvents()
    settings = window.settings
    _check("设置页：显示库路径", "gui.db" in settings.path_label.text(),
           settings.path_label.text())
    _check("设置页：显示库大小", "KB" in settings.size_label.text(), settings.size_label.text())
    _check("设置页：显示数据统计", "机柜" in settings.stats_label.text(),
           settings.stats_label.text())

    backup = backend.backup(tmp / "gui_backup.db")
    _check("设置页：备份可用", backup.exists() and backup.stat().st_size > 0)

    # ---------- 设置页：设备类型管理 ----------
    _check_device_types(window, app)

    # ---------- 页面间刷新联动 ----------
    window.go_to("devices")
    app.processEvents()
    count_before = window.devices.model.rowCount()
    backend.delete_devices([window.devices.model.device_at(0).id])
    window._mark_all_stale()
    app.processEvents()
    _check("联动：当前页立即刷新", window.devices.model.rowCount() == count_before - 1,
           f"{count_before} -> {window.devices.model.rowCount()}")
    window.go_to("dashboard")
    app.processEvents()
    _check("联动：切页后总览也更新",
           window.dashboard.stat_cards["devices"].value_label.text()
           == str(backend.count_devices(DeviceQuery())),
           window.dashboard.stat_cards["devices"].value_label.text())

    # ---------- 主题 ----------
    _check("主题样式表非空", len(theme.STYLESHEET) > 1000)
    _check("主题色已定义", theme.PRIMARY.startswith("#"))

    # ---------- 对话框与菜单不泄漏 ----------
    # 曾经的问题：对话框传了 parent 又没销毁，每编辑一次就留一个
    # 隐藏窗口，编辑几十次攒几十个。这里盯住「数量不随次数增长」。
    _check_no_leak(window, app)

    # ---------- 复制设备 ----------
    _check_copy_device(window, app)

    window.close()
    app.processEvents()
    _check("窗口可正常关闭", not window.isVisible())


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(theme.STYLESHEET)

    with tempfile.TemporaryDirectory(
        prefix="cabinet-gui-", ignore_cleanup_errors=True
    ) as folder:
        try:
            run(Path(folder), app)
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            FAILED.append(("测试执行", f"{type(exc).__name__}: {exc}"))

    total = len(PASSED) + len(FAILED)
    print(f"\nGUI 用例 {total} 个，通过 {len(PASSED)}，失败 {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  x {name} —— {detail}")
    if not FAILED:
        print("全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
