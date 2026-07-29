"""U 位预留的读写。预留只占位，不是真实设备。"""

from __future__ import annotations

import sqlite3

from ..database import Database
from ..models import Reservation


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class ReservationRepository:
    _SELECT = """
        SELECT rv.*, c.name AS cabinet_name, r.name AS room_name
          FROM reservation rv
          LEFT JOIN cabinet c ON c.id = rv.cabinet_id
          LEFT JOIN room r    ON r.id = c.room_id
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def to_reservation(row: sqlite3.Row) -> Reservation:
        keys = row.keys()
        return Reservation(
            id=row["id"],
            cabinet_id=row["cabinet_id"],
            u_start=row["u_start"],
            u_size=row["u_size"],
            label=row["label"],
            project=row["project"],
            owner=row["owner"],
            planned_date=row["planned_date"],
            remark=row["remark"],
            created_at=row["created_at"],
            cabinet_name=row["cabinet_name"] if "cabinet_name" in keys else None,
            room_name=row["room_name"] if "room_name" in keys else None,
        )

    def list_all(self, cabinet_id: int | None = None) -> list[Reservation]:
        if cabinet_id:
            rows = self.db.query(
                self._SELECT + " WHERE rv.cabinet_id=? ORDER BY rv.u_start DESC", (cabinet_id,)
            )
        else:
            rows = self.db.query(
                self._SELECT + " ORDER BY r.name, c.position_in_row, c.name, rv.u_start DESC"
            )
        return [self.to_reservation(r) for r in rows]

    def list_by_cabinet(self, cabinet_id: int) -> list[Reservation]:
        rows = self.db.query(
            "SELECT * FROM reservation WHERE cabinet_id=? ORDER BY u_start DESC", (cabinet_id,)
        )
        return [self.to_reservation(r) for r in rows]

    def get(self, reservation_id: int) -> Reservation | None:
        row = self.db.query_one(self._SELECT + " WHERE rv.id=?", (reservation_id,))
        return self.to_reservation(row) if row else None

    def insert(self, item: Reservation) -> int:
        return self.db.insert(
            """INSERT INTO reservation
               (cabinet_id, u_start, u_size, label, project, owner, planned_date, remark)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                item.cabinet_id,
                item.u_start,
                max(1, int(item.u_size or 1)),
                (item.label or "预留").strip(),
                _clean(item.project),
                _clean(item.owner),
                _clean(item.planned_date),
                _clean(item.remark),
            ),
        )

    def update(self, item: Reservation) -> None:
        self.db.execute(
            """UPDATE reservation SET cabinet_id=?, u_start=?, u_size=?, label=?,
                 project=?, owner=?, planned_date=?, remark=? WHERE id=?""",
            (
                item.cabinet_id,
                item.u_start,
                max(1, int(item.u_size or 1)),
                (item.label or "预留").strip(),
                _clean(item.project),
                _clean(item.owner),
                _clean(item.planned_date),
                _clean(item.remark),
                item.id,
            ),
        )

    def delete(self, reservation_id: int) -> None:
        self.db.execute("DELETE FROM reservation WHERE id=?", (reservation_id,))

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM reservation", default=0) or 0)
