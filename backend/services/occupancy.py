"""U 位占用计算与冲突校验。

约定：U 位从机柜底部往上编号，1U 在最下面。
一个占 uSize 的设备放在 uStart，占用区间是 [uStart, uStart + uSize - 1]。
已下架的设备不占位。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..database import Database
from ..models import PlacementCheck, Slot


@dataclass(slots=True)
class Occupant:
    """机柜里的一个占位对象，设备和预留统一看待。"""

    kind: str  # 'device' | 'reservation'
    id: int
    name: str
    u_start: int
    u_size: int

    @property
    def u_end(self) -> int:
        return self.u_start + self.u_size - 1

    def describe(self) -> str:
        return f"{self.name}({self.u_start}U-{self.u_end}U)"


class OccupancyService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def occupants(self, cabinet_id: int) -> list[Occupant]:
        devices = self.db.query(
            """SELECT id, name, u_start, u_size FROM device
                WHERE cabinet_id=? AND u_start IS NOT NULL AND status <> '已下架'""",
            (cabinet_id,),
        )
        reservations = self.db.query(
            "SELECT id, label, u_start, u_size FROM reservation WHERE cabinet_id=?",
            (cabinet_id,),
        )
        result = [
            Occupant("device", r["id"], r["name"], r["u_start"], r["u_size"]) for r in devices
        ]
        result += [
            Occupant("reservation", r["id"], r["label"], r["u_start"], r["u_size"])
            for r in reservations
        ]
        return result

    def taken_units(self, cabinet_id: int) -> dict[int, Occupant]:
        """U 位 -> 占用者，界面上判断某格是否可点用得到。"""
        mapping: dict[int, Occupant] = {}
        for occ in self.occupants(cabinet_id):
            for u in range(occ.u_start, occ.u_end + 1):
                mapping[u] = occ
        return mapping

    def check(
        self,
        cabinet_id: int,
        u_start: int | None,
        u_size: int,
        exclude_kind: str = "",
        exclude_id: int = 0,
    ) -> PlacementCheck:
        """校验一段 U 位能不能放。exclude 用于编辑自身时排除自己。"""
        if u_start is None:
            # 没指定 U 位就是未上架，不做占位校验
            return PlacementCheck(ok=True)

        row = self.db.query_one("SELECT u_total, name FROM cabinet WHERE id=?", (cabinet_id,))
        if row is None:
            return PlacementCheck(ok=False, message="机柜不存在")

        if not isinstance(u_start, int) or u_start < 1:
            return PlacementCheck(ok=False, message=f"起始 U 位必须是不小于 1 的整数，当前是 {u_start}")
        if not isinstance(u_size, int) or u_size < 1:
            return PlacementCheck(ok=False, message=f"占用 U 数必须是不小于 1 的整数，当前是 {u_size}")

        u_total = int(row["u_total"])
        u_end = u_start + u_size - 1
        if u_end > u_total:
            return PlacementCheck(
                ok=False,
                message=(
                    f"超出机柜范围：{row['name']} 共 {u_total}U，"
                    f"从 {u_start}U 起放 {u_size}U 会占到 {u_end}U"
                ),
            )

        hits = [
            occ
            for occ in self.occupants(cabinet_id)
            if not (occ.kind == exclude_kind and occ.id == exclude_id)
            and u_start <= occ.u_end
            and occ.u_start <= u_end
        ]
        if hits:
            desc = "、".join(h.describe() for h in hits)
            return PlacementCheck(
                ok=False,
                message=f"U 位冲突：已被 {desc} 占用",
                conflicts=[h.describe() for h in hits],
            )

        return PlacementCheck(ok=True)

    def free_slots(self, cabinet_id: int) -> list[Slot]:
        """机柜里所有连续空闲区间，从下往上排列。"""
        u_total = int(self.db.scalar("SELECT u_total FROM cabinet WHERE id=?", (cabinet_id,), 0) or 0)
        if u_total <= 0:
            return []

        taken = set(self.taken_units(cabinet_id))
        slots: list[Slot] = []
        start: int | None = None
        for u in range(1, u_total + 1):
            if u not in taken:
                if start is None:
                    start = u
            elif start is not None:
                slots.append(Slot(start, u - start))
                start = None
        if start is not None:
            slots.append(Slot(start, u_total - start + 1))
        return slots

    def find_free_slot(self, cabinet_id: int, u_size: int) -> int | None:
        """找一个能放下 u_size 的最低空位，找不到返回 None。"""
        for slot in self.free_slots(cabinet_id):
            if slot.u_size >= u_size:
                return slot.u_start
        return None
