"""机柜布局、U 位预留与容量汇总。"""

from __future__ import annotations

from ..database import Database
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import CabinetLayout, CapacityRow, Device, Reservation, Slot, Stats
from ..repositories import DeviceRepository, PlaceRepository, ReservationRepository
from .occupancy import OccupancyService

# 每个机柜的用量明细，是三级汇总的基础
_USAGE_SQL = """
SELECT
  c.id, c.name, c.room_id, c.row_id, c.u_total,
  COALESCE(c.power_limit_w, 0)    AS power_limit_w,
  COALESCE(c.weight_limit_kg, 0)  AS weight_limit_kg,
  r.name  AS room_name,
  rw.name AS row_name,
  COALESCE(d.dev_count, 0)   AS dev_count,
  COALESCE(d.u_used, 0)      AS u_used,
  COALESCE(d.power_used, 0)  AS power_used,
  COALESCE(d.weight_used, 0) AS weight_used,
  COALESCE(rv.u_reserved, 0) AS u_reserved
FROM cabinet c
LEFT JOIN room r      ON r.id = c.room_id
LEFT JOIN rack_row rw ON rw.id = c.row_id
LEFT JOIN (
    SELECT cabinet_id,
           COUNT(*) AS dev_count,
           SUM(u_size) AS u_used,
           SUM(COALESCE(power_w, 0)) AS power_used,
           SUM(COALESCE(weight_kg, 0)) AS weight_used
      FROM device
     WHERE cabinet_id IS NOT NULL AND u_start IS NOT NULL AND status <> '已下架'
     GROUP BY cabinet_id
) d ON d.cabinet_id = c.id
LEFT JOIN (
    SELECT cabinet_id, SUM(u_size) AS u_reserved FROM reservation GROUP BY cabinet_id
) rv ON rv.cabinet_id = c.id
"""


class CapacityService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.places = PlaceRepository(db)
        self.devices = DeviceRepository(db)
        self.reservations = ReservationRepository(db)
        self.occupancy = OccupancyService(db)

    # ---------- 机柜布局 ----------

    def cabinet_layout(self, cabinet_id: int) -> CabinetLayout:
        cabinet = self.places.get_cabinet(cabinet_id)
        if cabinet is None:
            raise NotFoundError("机柜不存在")
        return CabinetLayout(
            cabinet=cabinet,
            devices=self.devices.list_by_cabinet(cabinet_id),
            reservations=self.reservations.list_by_cabinet(cabinet_id),
        )

    def layouts(self, cabinet_ids: list[int]) -> list[CabinetLayout]:
        """整列并排用的批量布局。

        原来是逐柜各发 3 条查询（机柜 / 设备 / 预留），一排 20 个柜就是
        60 条。现在一次 IN 批量取回三样，内存里按 cabinet_id 分组。
        """
        if not cabinet_ids:
            return []
        cabinets = {c.id: c for c in self.places.get_cabinets(cabinet_ids)}
        devices_by_cab: dict[int, list[Device]] = {}
        for d in self.devices.list_by_cabinets(cabinet_ids):
            devices_by_cab.setdefault(d.cabinet_id, []).append(d)
        reservations_by_cab: dict[int, list[Reservation]] = {}
        for r in self.reservations.list_by_cabinets(cabinet_ids):
            reservations_by_cab.setdefault(r.cabinet_id, []).append(r)

        result: list[CabinetLayout] = []
        for cid in cabinet_ids:
            cabinet = cabinets.get(cid)
            if cabinet is None:
                continue  # 列表到布局之间机柜被删了，跳过而不是报错
            result.append(
                CabinetLayout(
                    cabinet=cabinet,
                    devices=devices_by_cab.get(cid, []),
                    reservations=reservations_by_cab.get(cid, []),
                )
            )
        return result

    def free_slots(self, cabinet_id: int) -> list[Slot]:
        return self.occupancy.free_slots(cabinet_id)

    # ---------- 预留 ----------

    def list_reservations(self, cabinet_id: int | None = None) -> list[Reservation]:
        return self.reservations.list_all(cabinet_id)

    def save_reservation(self, item: Reservation) -> Reservation:
        if not item.cabinet_id:
            raise ValidationError("预留必须指定机柜")
        if not (item.label or "").strip():
            item.label = "预留"
        item.u_size = max(1, int(item.u_size or 1))

        check = self.occupancy.check(
            item.cabinet_id,
            item.u_start,
            item.u_size,
            exclude_kind="reservation" if item.id else "",
            exclude_id=item.id or 0,
        )
        if not check.ok:
            raise ConflictError(check.message)

        with self.db.transaction():
            if item.id:
                self.reservations.update(item)
                reservation_id = item.id
            else:
                reservation_id = self.reservations.insert(item)
        saved = self.reservations.get(reservation_id)
        if saved is None:
            raise NotFoundError("预留保存后读取失败")
        return saved

    def delete_reservation(self, reservation_id: int) -> None:
        with self.db.transaction():
            self.reservations.delete(reservation_id)

    def convert_reservation(self, reservation_id: int) -> Reservation:
        """把预留原样返回，供界面拿它的位置去新建设备。"""
        item = self.reservations.get(reservation_id)
        if item is None:
            raise NotFoundError("预留不存在")
        return item

    # ---------- 容量汇总 ----------

    def _usage_rows(self, room_id: int | None = None) -> list[dict[str, object]]:
        sql = _USAGE_SQL
        params: list[object] = []
        if room_id:
            sql += " WHERE c.room_id = ?"
            params.append(room_id)
        return [dict(r) for r in self.db.query(sql, params)]

    def capacity_report(
        self, room_id: int | None = None
    ) -> dict[str, list[CapacityRow]]:
        """返回机房 / 列 / 机柜三种粒度的汇总。"""
        usage = self._usage_rows(room_id)

        cabinets = [
            CapacityRow(
                scope="cabinet",
                id=int(u["id"]),
                name=str(u["name"]),
                parent_name=(u["row_name"] or u["room_name"] or None),
                cabinet_count=1,
                device_count=int(u["dev_count"]),
                u_total=int(u["u_total"]),
                u_used=int(u["u_used"]),
                u_reserved=int(u["u_reserved"]),
                power_limit_w=float(u["power_limit_w"]),
                power_used_w=round(float(u["power_used"]), 1),
                weight_limit_kg=float(u["weight_limit_kg"]),
                weight_used_kg=round(float(u["weight_used"]), 1),
            )
            for u in usage
        ]

        def group(scope: str, key: str, name_key: str, parent_key: str | None) -> list[CapacityRow]:
            acc: dict[object, CapacityRow] = {}
            for u in usage:
                gid = u[key]
                if gid is None:
                    # 未分列的机柜单独归一组，不能丢
                    gid = 0
                    label = "未分列"
                else:
                    label = str(u[name_key] or f"#{gid}")
                item = acc.get(gid)
                if item is None:
                    item = CapacityRow(
                        scope=scope,
                        id=int(gid),
                        name=label,
                        parent_name=str(u[parent_key]) if parent_key and u[parent_key] else None,
                    )
                    acc[gid] = item
                item.cabinet_count += 1
                item.device_count += int(u["dev_count"])
                item.u_total += int(u["u_total"])
                item.u_used += int(u["u_used"])
                item.u_reserved += int(u["u_reserved"])
                item.power_limit_w += float(u["power_limit_w"])
                item.power_used_w += float(u["power_used"])
                item.weight_limit_kg += float(u["weight_limit_kg"])
                item.weight_used_kg += float(u["weight_used"])
            rows = list(acc.values())
            for row in rows:
                row.power_used_w = round(row.power_used_w, 1)
                row.weight_used_kg = round(row.weight_used_kg, 1)
            return sorted(rows, key=lambda r: r.name)

        return {
            "rooms": group("room", "room_id", "room_name", None),
            "rows": group("row", "row_id", "row_name", "room_name"),
            "cabinets": cabinets,
        }

    def tightest_cabinets(self, limit: int = 8) -> list[CapacityRow]:
        """容量最紧的几个机柜，超限的排最前，给总览页用。"""
        cabinets = self.capacity_report()["cabinets"]
        return sorted(cabinets, key=lambda c: (not c.overload, -c.u_usage_pct))[:limit]

    # ---------- 统计 ----------

    def stats(self) -> Stats:
        one = lambda sql: int(self.db.scalar(sql, default=0) or 0)  # noqa: E731
        by_type = [
            (r["dev_type"], int(r["n"]))
            for r in self.db.query(
                "SELECT dev_type, COUNT(*) AS n FROM device GROUP BY dev_type ORDER BY n DESC"
            )
        ]
        return Stats(
            rooms=one("SELECT COUNT(*) FROM room"),
            rows=one("SELECT COUNT(*) FROM rack_row"),
            cabinets=one("SELECT COUNT(*) FROM cabinet"),
            devices=one("SELECT COUNT(*) FROM device"),
            unracked=one(
                "SELECT COUNT(*) FROM device WHERE cabinet_id IS NULL OR u_start IS NULL"
            ),
            faulty=one("SELECT COUNT(*) FROM device WHERE status = '故障'"),
            reservations=one("SELECT COUNT(*) FROM reservation"),
            warranty_soon=one(
                # 只看「今天到 90 天后之间」的；已经过保的不算「即将脱保」，
                # 不然台账里的过保老设备会一直挂在这个提醒里
                """SELECT COUNT(*) FROM device
                    WHERE warranty_end IS NOT NULL AND warranty_end <> ''
                      AND date(warranty_end) >= date('now')
                      AND date(warranty_end) <= date('now', '+90 day')"""
            ),
            by_type=by_type,
            db_path=str(self.db.path),
            db_size_kb=self.db.size_kb(),
        )
