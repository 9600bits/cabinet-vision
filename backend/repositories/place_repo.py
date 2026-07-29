"""机房 / 列 / 机柜的读写。"""

from __future__ import annotations

import sqlite3

from ..database import Database
from ..errors import ConflictError
from ..models import Cabinet, RackRow, Room


def _clean(value: object) -> object:
    """空字符串统一存成 NULL，避免出现 '' 和 NULL 两种空值。"""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class PlaceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------- 行转对象 ----------

    @staticmethod
    def to_room(row: sqlite3.Row) -> Room:
        return Room(
            id=row["id"],
            name=row["name"],
            code=row["code"],
            location=row["location"],
            remark=row["remark"],
            sort_order=row["sort_order"],
        )

    @staticmethod
    def to_row(row: sqlite3.Row) -> RackRow:
        return RackRow(
            id=row["id"],
            room_id=row["room_id"],
            name=row["name"],
            remark=row["remark"],
            sort_order=row["sort_order"],
        )

    @staticmethod
    def to_cabinet(row: sqlite3.Row) -> Cabinet:
        keys = row.keys()
        return Cabinet(
            id=row["id"],
            room_id=row["room_id"],
            row_id=row["row_id"],
            name=row["name"],
            code=row["code"],
            u_total=row["u_total"],
            power_limit_w=row["power_limit_w"],
            weight_limit_kg=row["weight_limit_kg"],
            position_in_row=row["position_in_row"],
            status=row["status"],
            remark=row["remark"],
            room_name=row["room_name"] if "room_name" in keys else None,
            row_name=row["row_name"] if "row_name" in keys else None,
        )

    # ---------- 机房 ----------

    def list_rooms(self) -> list[Room]:
        rows = self.db.query("SELECT * FROM room ORDER BY sort_order, name")
        return [self.to_room(r) for r in rows]

    def get_room(self, room_id: int) -> Room | None:
        row = self.db.query_one("SELECT * FROM room WHERE id = ?", (room_id,))
        return self.to_room(row) if row else None

    def find_room_by_name(self, name: str) -> Room | None:
        row = self.db.query_one("SELECT * FROM room WHERE name = ?", (name.strip(),))
        return self.to_room(row) if row else None

    def insert_room(self, room: Room) -> int:
        try:
            return self.db.insert(
                "INSERT INTO room (name, code, location, remark, sort_order) VALUES (?,?,?,?,?)",
                (
                    room.name.strip(),
                    _clean(room.code),
                    _clean(room.location),
                    _clean(room.remark),
                    room.sort_order,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"机房「{room.name}」已存在") from exc

    def update_room(self, room: Room) -> None:
        try:
            self.db.execute(
                "UPDATE room SET name=?, code=?, location=?, remark=?, sort_order=? WHERE id=?",
                (
                    room.name.strip(),
                    _clean(room.code),
                    _clean(room.location),
                    _clean(room.remark),
                    room.sort_order,
                    room.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"机房「{room.name}」已存在") from exc

    def delete_room(self, room_id: int) -> None:
        self.db.execute("DELETE FROM room WHERE id = ?", (room_id,))

    # ---------- 列 ----------

    def list_rows(self, room_id: int | None = None) -> list[RackRow]:
        if room_id:
            rows = self.db.query(
                "SELECT * FROM rack_row WHERE room_id=? ORDER BY sort_order, name",
                (room_id,),
            )
        else:
            rows = self.db.query("SELECT * FROM rack_row ORDER BY room_id, sort_order, name")
        return [self.to_row(r) for r in rows]

    def get_row(self, row_id: int) -> RackRow | None:
        row = self.db.query_one("SELECT * FROM rack_row WHERE id=?", (row_id,))
        return self.to_row(row) if row else None

    def find_row_by_name(self, room_id: int, name: str) -> RackRow | None:
        row = self.db.query_one(
            "SELECT * FROM rack_row WHERE room_id=? AND name=?", (room_id, name.strip())
        )
        return self.to_row(row) if row else None

    def insert_row(self, item: RackRow) -> int:
        try:
            return self.db.insert(
                "INSERT INTO rack_row (room_id, name, remark, sort_order) VALUES (?,?,?,?)",
                (item.room_id, item.name.strip(), _clean(item.remark), item.sort_order),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"该机房下已有名为「{item.name}」的列") from exc

    def update_row(self, item: RackRow) -> None:
        try:
            self.db.execute(
                "UPDATE rack_row SET room_id=?, name=?, remark=?, sort_order=? WHERE id=?",
                (item.room_id, item.name.strip(), _clean(item.remark), item.sort_order, item.id),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"该机房下已有名为「{item.name}」的列") from exc

    def delete_row(self, row_id: int) -> None:
        self.db.execute("DELETE FROM rack_row WHERE id=?", (row_id,))

    # ---------- 机柜 ----------

    _CAB_SELECT = """
        SELECT c.*, r.name AS room_name, rw.name AS row_name
          FROM cabinet c
          LEFT JOIN room r      ON r.id = c.room_id
          LEFT JOIN rack_row rw ON rw.id = c.row_id
    """

    def list_cabinets(
        self, room_id: int | None = None, row_id: int | None = None
    ) -> list[Cabinet]:
        where: list[str] = []
        params: list[object] = []
        if room_id:
            where.append("c.room_id = ?")
            params.append(room_id)
        if row_id:
            where.append("c.row_id = ?")
            params.append(row_id)
        sql = self._CAB_SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.sort_order, r.name, c.position_in_row, c.name"
        return [self.to_cabinet(r) for r in self.db.query(sql, params)]

    def get_cabinet(self, cabinet_id: int) -> Cabinet | None:
        row = self.db.query_one(self._CAB_SELECT + " WHERE c.id = ?", (cabinet_id,))
        return self.to_cabinet(row) if row else None

    def find_cabinet_by_name(self, room_id: int, name: str) -> Cabinet | None:
        row = self.db.query_one(
            self._CAB_SELECT + " WHERE c.room_id=? AND c.name=?", (room_id, name.strip())
        )
        return self.to_cabinet(row) if row else None

    def insert_cabinet(self, cab: Cabinet) -> int:
        try:
            return self.db.insert(
                """INSERT INTO cabinet
                   (room_id, row_id, name, code, u_total, power_limit_w,
                    weight_limit_kg, position_in_row, status, remark)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    cab.room_id,
                    cab.row_id,
                    cab.name.strip(),
                    _clean(cab.code),
                    cab.u_total,
                    cab.power_limit_w,
                    cab.weight_limit_kg,
                    cab.position_in_row,
                    cab.status,
                    _clean(cab.remark),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"该机房下已有编号为「{cab.name}」的机柜") from exc

    def update_cabinet(self, cab: Cabinet) -> None:
        try:
            self.db.execute(
                """UPDATE cabinet SET room_id=?, row_id=?, name=?, code=?, u_total=?,
                      power_limit_w=?, weight_limit_kg=?, position_in_row=?, status=?, remark=?
                    WHERE id=?""",
                (
                    cab.room_id,
                    cab.row_id,
                    cab.name.strip(),
                    _clean(cab.code),
                    cab.u_total,
                    cab.power_limit_w,
                    cab.weight_limit_kg,
                    cab.position_in_row,
                    cab.status,
                    _clean(cab.remark),
                    cab.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"该机房下已有编号为「{cab.name}」的机柜") from exc

    def delete_cabinet(self, cabinet_id: int) -> None:
        self.db.execute("DELETE FROM cabinet WHERE id=?", (cabinet_id,))

    def max_occupied_u(self, cabinet_id: int) -> int:
        """机柜里被占到的最高 U 位，改小总高时用来校验。"""
        return int(
            self.db.scalar(
                """SELECT MAX(top) FROM (
                       SELECT u_start + u_size - 1 AS top FROM device
                        WHERE cabinet_id=? AND u_start IS NOT NULL AND status <> '已下架'
                       UNION ALL
                       SELECT u_start + u_size - 1 AS top FROM reservation WHERE cabinet_id=?
                   )""",
                (cabinet_id, cabinet_id),
                default=0,
            )
            or 0
        )
