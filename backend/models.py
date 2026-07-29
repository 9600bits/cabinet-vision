"""数据传输对象。

后端只对外暴露这些 dataclass，不把 sqlite3.Row 泄漏到前端，
这样以后换存储或加网络层都不用改界面代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


class Dto:
    """提供统一的 to_dict，方便调试与导出。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass(slots=True)
class Room(Dto):
    id: int
    name: str
    code: str | None = None
    location: str | None = None
    remark: str | None = None
    sort_order: int = 0


@dataclass(slots=True)
class RackRow(Dto):
    id: int
    room_id: int
    name: str
    remark: str | None = None
    sort_order: int = 0


@dataclass(slots=True)
class Cabinet(Dto):
    id: int
    room_id: int
    name: str
    row_id: int | None = None
    code: str | None = None
    u_total: int = 42
    power_limit_w: float | None = None
    weight_limit_kg: float | None = None
    position_in_row: int = 0
    status: str = "在用"
    remark: str | None = None
    # 便于界面直接显示，查询时带出来
    room_name: str | None = None
    row_name: str | None = None


@dataclass(slots=True)
class Device(Dto):
    id: int
    name: str
    cabinet_id: int | None = None
    u_start: int | None = None
    u_size: int = 1
    dev_type: str = "其他"
    status: str = "在用"
    model: str | None = None
    vendor: str | None = None
    sn: str | None = None
    asset_no: str | None = None
    mgmt_ip: str | None = None
    power_w: float | None = None
    weight_kg: float | None = None
    install_date: str | None = None
    warranty_end: str | None = None
    owner: str | None = None
    project: str | None = None
    remark: str | None = None
    created_at: str = ""
    updated_at: str = ""
    room_name: str | None = None
    row_name: str | None = None
    cabinet_name: str | None = None

    @property
    def u_end(self) -> int | None:
        """占用区间的顶部 U 位。"""
        if self.u_start is None:
            return None
        return self.u_start + self.u_size - 1

    @property
    def is_racked(self) -> bool:
        """是否已经真正上架（既有机柜又有 U 位）。"""
        return self.cabinet_id is not None and self.u_start is not None


@dataclass(slots=True)
class Reservation(Dto):
    id: int
    cabinet_id: int
    u_start: int
    u_size: int = 1
    label: str = "预留"
    project: str | None = None
    owner: str | None = None
    planned_date: str | None = None
    remark: str | None = None
    created_at: str = ""
    cabinet_name: str | None = None
    room_name: str | None = None

    @property
    def u_end(self) -> int:
        return self.u_start + self.u_size - 1


@dataclass(slots=True)
class DeviceLink(Dto):
    id: int
    device_id: int
    local_port: str | None = None
    peer_device_id: int | None = None
    peer_device_name: str | None = None
    peer_port: str | None = None
    link_type: str = "上行"
    speed: str | None = None
    medium: str | None = None
    remark: str | None = None
    # 对端在台账里时解析出的名字
    peer_resolved_name: str | None = None


@dataclass(slots=True)
class IncomingLink(Dto):
    """别的设备连到本设备的记录，只用于展示。"""

    id: int
    device_id: int
    device_name: str
    local_port: str | None
    peer_port: str | None
    link_type: str


@dataclass(slots=True)
class DeviceQuery:
    """设备列表查询条件。"""

    keyword: str = ""
    room_id: int | None = None
    row_id: int | None = None
    cabinet_id: int | None = None
    dev_types: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    owner: str = ""
    project: str = ""
    vendor: str = ""
    unracked_only: bool = False
    sort_by: str | None = None
    sort_desc: bool = False
    limit: int | None = None
    offset: int = 0


@dataclass(slots=True)
class Slot:
    """机柜里的一段连续空位。"""

    u_start: int
    u_size: int

    @property
    def u_end(self) -> int:
        return self.u_start + self.u_size - 1


@dataclass(slots=True)
class CabinetLayout(Dto):
    """画一个机柜正视图所需的全部数据。"""

    cabinet: Cabinet
    devices: list[Device] = field(default_factory=list)
    reservations: list[Reservation] = field(default_factory=list)

    @property
    def racked_devices(self) -> list[Device]:
        from .constants import OCCUPYING_STATUSES

        return [
            d
            for d in self.devices
            if d.u_start is not None and d.status in OCCUPYING_STATUSES
        ]

    @property
    def used_u(self) -> int:
        return sum(d.u_size for d in self.racked_devices)

    @property
    def reserved_u(self) -> int:
        return sum(r.u_size for r in self.reservations)

    @property
    def free_u(self) -> int:
        return max(0, self.cabinet.u_total - self.used_u - self.reserved_u)

    @property
    def power_used_w(self) -> float:
        return sum(d.power_w or 0.0 for d in self.racked_devices)

    @property
    def weight_used_kg(self) -> float:
        return sum(d.weight_kg or 0.0 for d in self.racked_devices)


@dataclass(slots=True)
class CapacityRow(Dto):
    """容量汇总的一行，机房 / 列 / 机柜三种粒度共用。"""

    scope: str
    id: int
    name: str
    parent_name: str | None = None
    cabinet_count: int = 0
    device_count: int = 0
    u_total: int = 0
    u_used: int = 0
    u_reserved: int = 0
    power_limit_w: float = 0.0
    power_used_w: float = 0.0
    weight_limit_kg: float = 0.0
    weight_used_kg: float = 0.0

    @property
    def u_free(self) -> int:
        return max(0, self.u_total - self.u_used - self.u_reserved)

    @property
    def u_usage_pct(self) -> float:
        if self.u_total <= 0:
            return 0.0
        return round((self.u_used + self.u_reserved) / self.u_total * 100, 1)

    @property
    def power_usage_pct(self) -> float:
        if self.power_limit_w <= 0:
            return 0.0
        return round(self.power_used_w / self.power_limit_w * 100, 1)

    @property
    def weight_usage_pct(self) -> float:
        if self.weight_limit_kg <= 0:
            return 0.0
        return round(self.weight_used_kg / self.weight_limit_kg * 100, 1)

    @property
    def overload(self) -> bool:
        if self.u_used + self.u_reserved > self.u_total:
            return True
        if self.power_limit_w > 0 and self.power_used_w > self.power_limit_w:
            return True
        if self.weight_limit_kg > 0 and self.weight_used_kg > self.weight_limit_kg:
            return True
        return False


@dataclass(slots=True)
class PlacementCheck(Dto):
    """U 位可用性校验结果。"""

    ok: bool
    message: str = ""
    conflicts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportError_(Dto):
    """导入时某一行的问题。"""

    row: int
    message: str
    field_name: str = ""


@dataclass(slots=True)
class ImportResult(Dto):
    total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[ImportError_] = field(default_factory=list)

    @property
    def writable(self) -> int:
        return self.inserted + self.updated


@dataclass(slots=True)
class ImportOptions:
    dry_run: bool = True
    create_missing_places: bool = True
    update_existing: bool = True
    default_u_total: int = 42


@dataclass(slots=True)
class Stats(Dto):
    rooms: int = 0
    rows: int = 0
    cabinets: int = 0
    devices: int = 0
    unracked: int = 0
    faulty: int = 0
    reservations: int = 0
    warranty_soon: int = 0
    by_type: list[tuple[str, int]] = field(default_factory=list)
    db_path: str = ""
    db_size_kb: int = 0
