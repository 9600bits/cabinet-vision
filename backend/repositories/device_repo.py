"""设备读写与筛选查询。"""

from __future__ import annotations

import sqlite3

from ..database import Database
from ..models import Device, DeviceQuery

# 前端列名 -> SQL 列，白名单避免拼接注入
SORTABLE: dict[str, str] = {
    "name": "d.name",
    "dev_type": "d.dev_type",
    "status": "d.status",
    "model": "d.model",
    "vendor": "d.vendor",
    "sn": "d.sn",
    "asset_no": "d.asset_no",
    "mgmt_ip": "d.mgmt_ip",
    "u_start": "d.u_start",
    "u_size": "d.u_size",
    "power_w": "d.power_w",
    "weight_kg": "d.weight_kg",
    "install_date": "d.install_date",
    "warranty_end": "d.warranty_end",
    "owner": "d.owner",
    "project": "d.project",
    "room_name": "r.name",
    "row_name": "rw.name",
    "cabinet_name": "c.name",
    "updated_at": "d.updated_at",
}

_FROM = """
  FROM device d
  LEFT JOIN cabinet c   ON c.id = d.cabinet_id
  LEFT JOIN room r      ON r.id = c.room_id
  LEFT JOIN rack_row rw ON rw.id = c.row_id
"""

_COLUMNS = (
    "cabinet_id",
    "name",
    "u_start",
    "u_size",
    "dev_type",
    "status",
    "model",
    "vendor",
    "sn",
    "asset_no",
    "mgmt_ip",
    "power_w",
    "weight_kg",
    "install_date",
    "warranty_end",
    "owner",
    "project",
    "remark",
)


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def to_device(row: sqlite3.Row) -> Device:
        keys = row.keys()
        return Device(
            id=row["id"],
            cabinet_id=row["cabinet_id"],
            name=row["name"],
            u_start=row["u_start"],
            u_size=row["u_size"],
            dev_type=row["dev_type"],
            status=row["status"],
            model=row["model"],
            vendor=row["vendor"],
            sn=row["sn"],
            asset_no=row["asset_no"],
            mgmt_ip=row["mgmt_ip"],
            power_w=row["power_w"],
            weight_kg=row["weight_kg"],
            install_date=row["install_date"],
            warranty_end=row["warranty_end"],
            owner=row["owner"],
            project=row["project"],
            remark=row["remark"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            room_name=row["room_name"] if "room_name" in keys else None,
            row_name=row["row_name"] if "row_name" in keys else None,
            cabinet_name=row["cabinet_name"] if "cabinet_name" in keys else None,
        )

    # ---------- 查询 ----------

    def _build_where(self, q: DeviceQuery) -> tuple[str, list[object]]:
        where: list[str] = []
        params: list[object] = []

        kw = q.keyword.strip()
        if kw:
            like = f"%{kw}%"
            fields = (
                "d.name",
                "d.model",
                "d.sn",
                "d.asset_no",
                "d.mgmt_ip",
                "d.vendor",
                "d.owner",
                "d.project",
                "d.remark",
                "c.name",
            )
            where.append("(" + " OR ".join(f"{f} LIKE ?" for f in fields) + ")")
            params.extend([like] * len(fields))

        # 有机柜但没 U 位的设备也算待上架，避免卡在中间态看不见
        if q.unracked_only:
            where.append("(d.cabinet_id IS NULL OR d.u_start IS NULL)")
        if q.cabinet_id:
            where.append("d.cabinet_id = ?")
            params.append(q.cabinet_id)
        if q.row_id:
            where.append("c.row_id = ?")
            params.append(q.row_id)
        if q.room_id:
            where.append("c.room_id = ?")
            params.append(q.room_id)
        if q.dev_types:
            where.append(f"d.dev_type IN ({','.join('?' * len(q.dev_types))})")
            params.extend(q.dev_types)
        if q.statuses:
            where.append(f"d.status IN ({','.join('?' * len(q.statuses))})")
            params.extend(q.statuses)
        for value, column in ((q.owner, "d.owner"), (q.project, "d.project"), (q.vendor, "d.vendor")):
            if value.strip():
                where.append(f"{column} LIKE ?")
                params.append(f"%{value.strip()}%")

        return (" WHERE " + " AND ".join(where) if where else ""), params

    def count(self, q: DeviceQuery) -> int:
        where_sql, params = self._build_where(q)
        return int(self.db.scalar(f"SELECT COUNT(*) {_FROM} {where_sql}", params, 0) or 0)

    def query(self, q: DeviceQuery) -> list[Device]:
        where_sql, params = self._build_where(q)

        if q.sort_by and q.sort_by in SORTABLE:
            direction = "DESC" if q.sort_desc else "ASC"
            order = f"ORDER BY {SORTABLE[q.sort_by]} {direction}, d.id ASC"
        else:
            order = (
                "ORDER BY r.sort_order, r.name, c.position_in_row, c.name, "
                "d.u_start DESC, d.id ASC"
            )

        sql = f"""SELECT d.*, c.name AS cabinet_name, r.name AS room_name, rw.name AS row_name
                  {_FROM} {where_sql} {order}"""
        if q.limit:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, q.limit, q.offset]
        return [self.to_device(r) for r in self.db.query(sql, params)]

    def get(self, device_id: int) -> Device | None:
        row = self.db.query_one(
            f"""SELECT d.*, c.name AS cabinet_name, r.name AS room_name, rw.name AS row_name
                {_FROM} WHERE d.id = ?""",
            (device_id,),
        )
        return self.to_device(row) if row else None

    def list_by_cabinet(self, cabinet_id: int) -> list[Device]:
        rows = self.db.query(
            "SELECT * FROM device WHERE cabinet_id=? ORDER BY u_start DESC, name",
            (cabinet_id,),
        )
        return [self.to_device(r) for r in rows]

    def list_by_cabinets(self, cabinet_ids: list[int]) -> list[Device]:
        """一次取一批机柜里的设备，整列视图用。ORDER BY 保证每柜内顺序不变。"""
        if not cabinet_ids:
            return []
        marks = ",".join("?" * len(cabinet_ids))
        rows = self.db.query(
            f"SELECT * FROM device WHERE cabinet_id IN ({marks}) ORDER BY u_start DESC, name",
            cabinet_ids,
        )
        return [self.to_device(r) for r in rows]

    def find_by_sn(self, sn: str) -> Device | None:
        row = self.db.query_one("SELECT * FROM device WHERE sn = ?", (sn.strip(),))
        return self.to_device(row) if row else None

    def find_by_asset_no(self, asset_no: str) -> Device | None:
        row = self.db.query_one("SELECT * FROM device WHERE asset_no = ?", (asset_no.strip(),))
        return self.to_device(row) if row else None

    def find_by_cabinet_and_name(self, cabinet_id: int, name: str) -> Device | None:
        row = self.db.query_one(
            "SELECT * FROM device WHERE cabinet_id=? AND name=?", (cabinet_id, name.strip())
        )
        return self.to_device(row) if row else None

    def find_by_name(self, name: str) -> Device | None:
        row = self.db.query_one("SELECT * FROM device WHERE name = ?", (name.strip(),))
        return self.to_device(row) if row else None

    def distinct_values(self, column: str) -> list[str]:
        """取某列的已有取值，给筛选下拉用。"""
        if column not in {"vendor", "owner", "project", "model"}:
            return []
        rows = self.db.query(
            f"SELECT DISTINCT {column} AS v FROM device "
            f"WHERE {column} IS NOT NULL AND {column} <> '' ORDER BY {column}"
        )
        return [r["v"] for r in rows]

    # ---------- 写入 ----------

    def _values(self, d: Device) -> list[object]:
        return [
            d.cabinet_id,
            d.name.strip(),
            d.u_start,
            max(1, int(d.u_size or 1)),
            d.dev_type,
            d.status,
            _clean(d.model),
            _clean(d.vendor),
            _clean(d.sn),
            _clean(d.asset_no),
            _clean(d.mgmt_ip),
            d.power_w,
            d.weight_kg,
            _clean(d.install_date),
            _clean(d.warranty_end),
            _clean(d.owner),
            _clean(d.project),
            _clean(d.remark),
        ]

    def insert(self, d: Device) -> int:
        placeholders = ",".join("?" * len(_COLUMNS))
        return self.db.insert(
            f"INSERT INTO device ({','.join(_COLUMNS)}) VALUES ({placeholders})",
            self._values(d),
        )

    def update(self, d: Device) -> None:
        sets = ", ".join(f"{c}=?" for c in _COLUMNS)
        self.db.execute(
            f"UPDATE device SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
            [*self._values(d), d.id],
        )

    def move(self, device_id: int, cabinet_id: int | None, u_start: int | None) -> None:
        self.db.execute(
            """UPDATE device SET cabinet_id=?, u_start=?,
                 updated_at=datetime('now','localtime') WHERE id=?""",
            (cabinet_id, u_start if cabinet_id else None, device_id),
        )

    def delete(self, device_ids: list[int]) -> int:
        if not device_ids:
            return 0
        marks = ",".join("?" * len(device_ids))
        cur = self.db.execute(f"DELETE FROM device WHERE id IN ({marks})", device_ids)
        return cur.rowcount

    def bulk_update_fields(self, device_ids: list[int], patch: dict[str, object]) -> int:
        allowed = {"dev_type", "status", "vendor", "model", "owner", "project", "remark"}
        fields = {k: v for k, v in patch.items() if k in allowed}
        if not fields or not device_ids:
            return 0
        sets = ", ".join(f"{k}=?" for k in fields)
        marks = ",".join("?" * len(device_ids))
        cur = self.db.execute(
            f"""UPDATE device SET {sets}, updated_at=datetime('now','localtime')
                WHERE id IN ({marks})""",
            [*(_clean(v) for v in fields.values()), *device_ids],
        )
        return cur.rowcount

    def unrack_by_cabinet(self, cabinet_id: int) -> int:
        cur = self.db.execute(
            """UPDATE device SET cabinet_id=NULL, u_start=NULL,
                 updated_at=datetime('now','localtime') WHERE cabinet_id=?""",
            (cabinet_id,),
        )
        return cur.rowcount

    def unrack_by_room(self, room_id: int) -> int:
        cur = self.db.execute(
            """UPDATE device SET cabinet_id=NULL, u_start=NULL,
                 updated_at=datetime('now','localtime')
                WHERE cabinet_id IN (SELECT id FROM cabinet WHERE room_id=?)""",
            (room_id,),
        )
        return cur.rowcount
