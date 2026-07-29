"""机房 / 列 / 机柜的业务规则。"""

from __future__ import annotations

from ..constants import CABINET_STATUSES
from ..database import Database
from ..errors import NotFoundError, ValidationError
from ..models import Cabinet, RackRow, Room
from ..repositories import DeviceRepository, PlaceRepository


class PlaceService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.places = PlaceRepository(db)
        self.devices = DeviceRepository(db)

    # ---------- 机房 ----------

    def list_rooms(self) -> list[Room]:
        return self.places.list_rooms()

    def save_room(self, room: Room) -> Room:
        if not room.name.strip():
            raise ValidationError("机房名称不能为空")
        with self.db.transaction():
            if room.id:
                self.places.update_room(room)
                room_id = room.id
            else:
                room_id = self.places.insert_room(room)
        saved = self.places.get_room(room_id)
        if saved is None:
            raise NotFoundError("机房保存后读取失败")
        return saved

    def delete_room(self, room_id: int) -> int:
        """删除机房。柜内设备转为未上架而不是删掉，避免误删台账。"""
        if self.places.get_room(room_id) is None:
            raise NotFoundError("机房不存在")
        with self.db.transaction():
            moved = self.devices.unrack_by_room(room_id)
            self.places.delete_room(room_id)
        return moved

    # ---------- 列 ----------

    def list_rows(self, room_id: int | None = None) -> list[RackRow]:
        return self.places.list_rows(room_id)

    def save_row(self, item: RackRow) -> RackRow:
        if not item.name.strip():
            raise ValidationError("列名称不能为空")
        if not item.room_id:
            raise ValidationError("必须指定所属机房")
        with self.db.transaction():
            if item.id:
                self.places.update_row(item)
                row_id = item.id
            else:
                row_id = self.places.insert_row(item)
        saved = self.places.get_row(row_id)
        if saved is None:
            raise NotFoundError("列保存后读取失败")
        return saved

    def delete_row(self, row_id: int) -> None:
        """删列不动机柜，只是把机柜的列归属清空。"""
        if self.places.get_row(row_id) is None:
            raise NotFoundError("列不存在")
        self.places.delete_row(row_id)

    # ---------- 机柜 ----------

    def list_cabinets(
        self, room_id: int | None = None, row_id: int | None = None
    ) -> list[Cabinet]:
        return self.places.list_cabinets(room_id, row_id)

    def get_cabinet(self, cabinet_id: int) -> Cabinet | None:
        return self.places.get_cabinet(cabinet_id)

    def save_cabinet(self, cab: Cabinet) -> Cabinet:
        if not cab.name.strip():
            raise ValidationError("机柜编号不能为空")
        if not cab.room_id:
            raise ValidationError("必须指定所属机房")
        if not 1 <= int(cab.u_total) <= 100:
            raise ValidationError("机柜总 U 数必须在 1 到 100 之间")
        if cab.status not in CABINET_STATUSES:
            cab.status = "在用"

        # 改小总高时不能把已有的设备或预留切掉
        if cab.id:
            highest = self.places.max_occupied_u(cab.id)
            if highest and cab.u_total < highest:
                raise ValidationError(
                    f"机柜内已有内容占到 {highest}U，无法把总高改成 {cab.u_total}U"
                )

        with self.db.transaction():
            if cab.id:
                self.places.update_cabinet(cab)
                cabinet_id = cab.id
            else:
                cabinet_id = self.places.insert_cabinet(cab)
        saved = self.places.get_cabinet(cabinet_id)
        if saved is None:
            raise NotFoundError("机柜保存后读取失败")
        return saved

    def delete_cabinet(self, cabinet_id: int) -> int:
        if self.places.get_cabinet(cabinet_id) is None:
            raise NotFoundError("机柜不存在")
        with self.db.transaction():
            moved = self.devices.unrack_by_cabinet(cabinet_id)
            self.places.delete_cabinet(cabinet_id)
        return moved

    def batch_create_cabinets(
        self,
        room_id: int,
        row_id: int | None,
        prefix: str,
        start_no: int,
        count: int,
        digits: int,
        u_total: int,
        power_limit_w: float | None = None,
        weight_limit_kg: float | None = None,
    ) -> tuple[int, list[str]]:
        """按编号规则铺一整列机柜。已存在的编号跳过并返回，方便补建。"""
        if count < 1 or count > 200:
            raise ValidationError("单次批量创建的数量需要在 1 到 200 之间")
        if not 1 <= u_total <= 100:
            raise ValidationError("机柜总 U 数必须在 1 到 100 之间")
        if self.places.get_room(room_id) is None:
            raise NotFoundError("机房不存在")

        created = 0
        skipped: list[str] = []
        with self.db.transaction():
            for index in range(count):
                name = f"{prefix}{str(start_no + index).zfill(max(1, digits))}"
                if self.places.find_cabinet_by_name(room_id, name):
                    skipped.append(name)
                    continue
                self.places.insert_cabinet(
                    Cabinet(
                        id=0,
                        room_id=room_id,
                        row_id=row_id,
                        name=name,
                        u_total=u_total,
                        power_limit_w=power_limit_w,
                        weight_limit_kg=weight_limit_kg,
                        position_in_row=index,
                    )
                )
                created += 1
        return created, skipped

    def preview_batch_names(
        self, prefix: str, start_no: int, count: int, digits: int, limit: int = 4
    ) -> list[str]:
        """给界面显示"将创建 A01、A02 …"用。"""
        return [
            f"{prefix}{str(start_no + i).zfill(max(1, digits))}"
            for i in range(min(max(count, 0), limit))
        ]
