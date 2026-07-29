"""后端门面。

前端只认这一个类，不直接碰 sqlite、仓储或服务实现。
好处是以后要换成 HTTP 服务或者换库，只需要再实现一份同样签名的门面。
"""

from __future__ import annotations

from pathlib import Path

from .database import Database, default_db_path
from .errors import BackendError, NotFoundError
from .models import (
    Cabinet,
    CabinetLayout,
    CapacityRow,
    Device,
    DeviceLink,
    DeviceQuery,
    DeviceType,
    ImportOptions,
    ImportResult,
    IncomingLink,
    PlacementCheck,
    RackRow,
    Reservation,
    Room,
    Slot,
    Stats,
)
from .services import (
    CapacityService,
    DeviceService,
    DeviceTypeService,
    ExcelService,
    OccupancyService,
    PlaceService,
    SeedService,
)


class Backend:
    """打开一个数据库文件，对外提供全部业务能力。"""

    def __init__(self, db_path: str | Path | None = None, seed_demo: bool = True) -> None:
        self._db = Database(db_path or default_db_path())
        self._wire()
        if seed_demo:
            self.seed.seed_if_empty()

    def _wire(self) -> None:
        self.places = PlaceService(self._db)
        self.devices = DeviceService(self._db)
        self.device_types = DeviceTypeService(self._db)
        self.capacity = CapacityService(self._db)
        self.excel = ExcelService(self._db)
        self.occupancy = OccupancyService(self._db)
        self.seed = SeedService(self._db)
        # 设备类型清单是库里的数据，换库就得重新灌进 constants，
        # 否则界面还在用上一个库的类型
        self.device_types.bootstrap()

    # ---------- 生命周期与库维护 ----------

    @property
    def db_path(self) -> Path:
        return self._db.path

    def db_size_kb(self) -> int:
        return self._db.size_kb()

    def switch_database(self, path: str | Path, seed_demo: bool = False) -> Path:
        """切换到另一个 .db 文件，用于恢复备份或多套台账。"""
        target = Path(path)
        old = self._db
        try:
            self._db = Database(target)
        except BackendError:
            self._db = old
            raise
        old.close()
        self._wire()
        if seed_demo:
            self.seed.seed_if_empty()
        return self._db.path

    def backup(self, target: str | Path) -> Path:
        return self._db.backup_to(target)

    def clear_all_data(self) -> None:
        self.seed.clear_all()

    def close(self) -> None:
        self._db.close()

    # ---------- 机房 / 列 / 机柜 ----------

    def list_rooms(self) -> list[Room]:
        return self.places.list_rooms()

    def save_room(self, room: Room) -> Room:
        return self.places.save_room(room)

    def delete_room(self, room_id: int) -> int:
        return self.places.delete_room(room_id)

    def list_rows(self, room_id: int | None = None) -> list[RackRow]:
        return self.places.list_rows(room_id)

    def save_row(self, row: RackRow) -> RackRow:
        return self.places.save_row(row)

    def delete_row(self, row_id: int) -> None:
        self.places.delete_row(row_id)

    def list_cabinets(
        self, room_id: int | None = None, row_id: int | None = None
    ) -> list[Cabinet]:
        return self.places.list_cabinets(room_id, row_id)

    def get_cabinet(self, cabinet_id: int) -> Cabinet:
        cabinet = self.places.get_cabinet(cabinet_id)
        if cabinet is None:
            raise NotFoundError("机柜不存在")
        return cabinet

    def save_cabinet(self, cabinet: Cabinet) -> Cabinet:
        return self.places.save_cabinet(cabinet)

    def delete_cabinet(self, cabinet_id: int) -> int:
        return self.places.delete_cabinet(cabinet_id)

    def batch_create_cabinets(self, **kwargs: object) -> tuple[int, list[str]]:
        return self.places.batch_create_cabinets(**kwargs)  # type: ignore[arg-type]

    def preview_batch_names(
        self, prefix: str, start_no: int, count: int, digits: int
    ) -> list[str]:
        return self.places.preview_batch_names(prefix, start_no, count, digits)

    # ---------- 设备 ----------

    def query_devices(self, query: DeviceQuery) -> list[Device]:
        return self.devices.query(query)

    def count_devices(self, query: DeviceQuery) -> int:
        return self.devices.count(query)

    def get_device(self, device_id: int) -> Device:
        return self.devices.get(device_id)

    def save_device(self, device: Device) -> Device:
        return self.devices.save(device)

    def delete_devices(self, device_ids: list[int]) -> int:
        return self.devices.delete(device_ids)

    def copy_of_device(self, device_id: int) -> Device:
        """按现有设备造一个待保存的副本（未落库，交给对话框预填）。"""
        return self.devices.copy_of(device_id)

    def move_device(
        self, device_id: int, cabinet_id: int | None, u_start: int | None
    ) -> Device:
        return self.devices.move(device_id, cabinet_id, u_start)

    def unrack_devices(self, device_ids: list[int]) -> int:
        return self.devices.unrack(device_ids)

    def auto_rack(
        self, device_ids: list[int], cabinet_id: int
    ) -> tuple[list[tuple[int, int]], list[tuple[str, str]]]:
        return self.devices.auto_rack(device_ids, cabinet_id)

    def bulk_update_devices(self, device_ids: list[int], patch: dict[str, object]) -> int:
        return self.devices.bulk_update(device_ids, patch)

    def list_unracked(self, keyword: str = "") -> list[Device]:
        return self.devices.list_unracked(keyword)

    def field_suggestions(self, column: str) -> list[str]:
        return self.devices.suggestions(column)

    # ---------- 设备类型 ----------

    def list_device_types(self, with_counts: bool = True) -> list[DeviceType]:
        return self.device_types.list_types(with_counts)

    def create_device_type(self, name: str, color: str = "") -> DeviceType:
        return self.device_types.create(name, color)

    def update_device_type(
        self, old_name: str, new_name: str, color: str
    ) -> tuple[DeviceType, int]:
        """改名 / 改色。返回 (新类型, 跟着改名的设备数)。"""
        return self.device_types.update(old_name, new_name, color)

    def delete_device_type(self, name: str) -> int:
        """删类型，用着它的设备归到「其他」。返回受影响的设备数。"""
        return self.device_types.delete(name)

    def restore_default_device_types(self) -> int:
        return self.device_types.restore_defaults()

    # ---------- 连接关系 ----------

    def list_links(self, device_id: int) -> tuple[list[DeviceLink], list[IncomingLink]]:
        return self.devices.list_links(device_id)

    def save_link(self, link: DeviceLink) -> DeviceLink:
        return self.devices.save_link(link)

    def delete_link(self, link_id: int) -> None:
        self.devices.delete_link(link_id)

    # ---------- 布局 / 预留 / 容量 ----------

    def cabinet_layout(self, cabinet_id: int) -> CabinetLayout:
        return self.capacity.cabinet_layout(cabinet_id)

    def cabinet_layouts(self, cabinet_ids: list[int]) -> list[CabinetLayout]:
        return self.capacity.layouts(cabinet_ids)

    def free_slots(self, cabinet_id: int) -> list[Slot]:
        return self.capacity.free_slots(cabinet_id)

    def check_placement(
        self,
        cabinet_id: int,
        u_start: int | None,
        u_size: int,
        exclude_device_id: int = 0,
    ) -> PlacementCheck:
        return self.occupancy.check(
            cabinet_id,
            u_start,
            u_size,
            exclude_kind="device" if exclude_device_id else "",
            exclude_id=exclude_device_id,
        )

    def list_reservations(self, cabinet_id: int | None = None) -> list[Reservation]:
        return self.capacity.list_reservations(cabinet_id)

    def save_reservation(self, reservation: Reservation) -> Reservation:
        return self.capacity.save_reservation(reservation)

    def delete_reservation(self, reservation_id: int) -> None:
        self.capacity.delete_reservation(reservation_id)

    def capacity_report(self, room_id: int | None = None) -> dict[str, list[CapacityRow]]:
        return self.capacity.capacity_report(room_id)

    def tightest_cabinets(self, limit: int = 8) -> list[CapacityRow]:
        return self.capacity.tightest_cabinets(limit)

    def stats(self) -> Stats:
        return self.capacity.stats()

    # ---------- Excel ----------

    def build_import_template(self, target: str | Path) -> Path:
        return self.excel.build_template(target)

    def import_devices(self, file: str | Path, options: ImportOptions) -> ImportResult:
        return self.excel.import_devices(file, options)

    def export_devices(self, target: str | Path, query: DeviceQuery | None = None) -> Path:
        devices = self.devices.query(query or DeviceQuery())
        return self.excel.export_devices(target, devices)

    def export_capacity(self, target: str | Path) -> Path:
        return self.excel.export_capacity(target)
