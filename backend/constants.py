"""领域常量。前后端共用这一份，避免两边各写一套枚举。

U 位编号约定：从机柜底部往上数，1U 在最下面，u_total 在最上面。
"""

from __future__ import annotations

DEVICE_TYPES: tuple[str, ...] = (
    "交换机",
    "路由器",
    "防火墙",
    "负载均衡",
    "服务器",
    "存储",
    "配线架",
    "PDU",
    "KVM",
    "光纤盒",
    "其他",
)

DEVICE_STATUSES: tuple[str, ...] = ("在用", "备用", "故障", "已下架")

CABINET_STATUSES: tuple[str, ...] = ("在用", "空闲", "停用")

LINK_TYPES: tuple[str, ...] = ("上行", "下行", "互联", "堆叠", "管理", "其他")

COMMON_U_TOTALS: tuple[int, ...] = (42, 47, 45, 36, 24, 22, 12, 9, 6)

# 机柜图按设备类型配色，深底白字，打印也清楚
DEVICE_TYPE_COLORS: dict[str, str] = {
    "交换机": "#1668dc",
    "路由器": "#642ab5",
    "防火墙": "#d32029",
    "负载均衡": "#08979c",
    "服务器": "#389e0d",
    "存储": "#5b8c00",
    "配线架": "#8c6b52",
    "PDU": "#d46b08",
    "KVM": "#c41d7f",
    "光纤盒": "#0958d9",
    "其他": "#595959",
}

STATUS_COLORS: dict[str, str] = {
    "在用": "#389e0d",
    "备用": "#1668dc",
    "故障": "#cf1322",
    "已下架": "#8c8c8c",
}

# 已下架的设备不占 U 位
OCCUPYING_STATUSES: tuple[str, ...] = ("在用", "备用", "故障")

RESERVATION_COLOR = "#fa8c16"
