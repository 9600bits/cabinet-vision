"""领域常量。前后端共用这一份，避免两边各写一套枚举。

U 位编号约定：从机柜底部往上数，1U 在最下面，u_total 在最上面。

设备类型是唯一一个可以由用户增删改的「常量」：清单存在库里，
打开数据库时由 DeviceTypeService 灌进 DEVICE_TYPES 和 DEVICE_TYPE_COLORS。
所以这两个是可变容器，而且只能就地改（切片赋值 / clear+update），
不能整体重新绑定 —— 各处都是 `from .constants import DEVICE_TYPES` 按值
导入的，重新绑定只会换掉本模块的名字，导入方还拿着旧对象。
"""

from __future__ import annotations

# 内置类型与配色。用户删光了也能用「恢复默认类型」找回来
DEFAULT_DEVICE_TYPES: tuple[tuple[str, str], ...] = (
    ("交换机", "#1668dc"),
    ("路由器", "#642ab5"),
    ("防火墙", "#d32029"),
    ("负载均衡", "#08979c"),
    ("服务器", "#389e0d"),
    ("存储", "#5b8c00"),
    ("配线架", "#8c6b52"),
    ("PDU", "#d46b08"),
    ("KVM", "#c41d7f"),
    ("光纤盒", "#0958d9"),
    ("其他", "#595959"),
)

# 兜底类型：类型不认识、或者类型被删掉时，设备都归到这里。
# 不允许改名和删除，否则归类逻辑没有落脚点。
FALLBACK_DEVICE_TYPE = "其他"

DEFAULT_TYPE_COLOR = "#595959"

# 当前可用的设备类型，顺序即界面下拉框的顺序。运行时由库里的清单覆盖
DEVICE_TYPES: list[str] = [name for name, _ in DEFAULT_DEVICE_TYPES]

DEVICE_STATUSES: tuple[str, ...] = ("在用", "备用", "故障", "已下架")

CABINET_STATUSES: tuple[str, ...] = ("在用", "空闲", "停用")

LINK_TYPES: tuple[str, ...] = ("上行", "下行", "互联", "堆叠", "管理", "其他")

COMMON_U_TOTALS: tuple[int, ...] = (42, 47, 45, 36, 24, 22, 12, 9, 6)

# 机柜图按设备类型配色，深底白字，打印也清楚
DEVICE_TYPE_COLORS: dict[str, str] = dict(DEFAULT_DEVICE_TYPES)

STATUS_COLORS: dict[str, str] = {
    "在用": "#389e0d",
    "备用": "#1668dc",
    "故障": "#cf1322",
    "已下架": "#8c8c8c",
}

# 已下架的设备不占 U 位
OCCUPYING_STATUSES: tuple[str, ...] = ("在用", "备用", "故障")

RESERVATION_COLOR = "#fa8c16"


def apply_device_types(types: list[tuple[str, str]]) -> None:
    """用库里的清单刷新设备类型注册表。

    就地改容器，不重新绑定名字：DEVICE_TYPES / DEVICE_TYPE_COLORS 被十来处
    按值导入，重新绑定的话那些地方还指向旧对象。切片赋值和 clear+update
    改的是同一个对象，所有导入方立刻看到新值。
    """
    names = [name for name, _ in types]
    if FALLBACK_DEVICE_TYPE not in names:
        # 兜底类型必须在，否则归类无处可去
        names.append(FALLBACK_DEVICE_TYPE)
        types = [*types, (FALLBACK_DEVICE_TYPE, DEFAULT_TYPE_COLOR)]
    DEVICE_TYPES[:] = names
    DEVICE_TYPE_COLORS.clear()
    DEVICE_TYPE_COLORS.update(types)


def type_color(name: str) -> str:
    """取类型配色，认不出的给中性灰。绘图代码统一走这里。"""
    return DEVICE_TYPE_COLORS.get(name, DEFAULT_TYPE_COLOR)
