"""设备连接关系（简化版：本端口 -> 对端设备端口）。"""

from __future__ import annotations

import sqlite3

from ..database import Database
from ..models import DeviceLink, IncomingLink


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class LinkRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def to_link(row: sqlite3.Row) -> DeviceLink:
        keys = row.keys()
        resolved = row["peer_name"] if "peer_name" in keys else None
        return DeviceLink(
            id=row["id"],
            device_id=row["device_id"],
            local_port=row["local_port"],
            peer_device_id=row["peer_device_id"],
            peer_device_name=row["peer_device_name"],
            peer_port=row["peer_port"],
            link_type=row["link_type"],
            speed=row["speed"],
            medium=row["medium"],
            remark=row["remark"],
            peer_resolved_name=resolved or row["peer_device_name"],
        )

    def list_outgoing(self, device_id: int) -> list[DeviceLink]:
        rows = self.db.query(
            """SELECT l.*, p.name AS peer_name FROM device_link l
                 LEFT JOIN device p ON p.id = l.peer_device_id
                WHERE l.device_id=? ORDER BY l.link_type, l.local_port""",
            (device_id,),
        )
        return [self.to_link(r) for r in rows]

    def list_incoming(self, device_id: int) -> list[IncomingLink]:
        rows = self.db.query(
            """SELECT l.id, l.device_id, d.name AS device_name, l.local_port,
                      l.peer_port, l.link_type
                 FROM device_link l JOIN device d ON d.id = l.device_id
                WHERE l.peer_device_id=? ORDER BY d.name""",
            (device_id,),
        )
        return [
            IncomingLink(
                id=r["id"],
                device_id=r["device_id"],
                device_name=r["device_name"],
                local_port=r["local_port"],
                peer_port=r["peer_port"],
                link_type=r["link_type"],
            )
            for r in rows
        ]

    def insert(self, link: DeviceLink) -> int:
        return self.db.insert(
            """INSERT INTO device_link
               (device_id, local_port, peer_device_id, peer_device_name,
                peer_port, link_type, speed, medium, remark)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            self._values(link),
        )

    def update(self, link: DeviceLink) -> None:
        self.db.execute(
            """UPDATE device_link SET device_id=?, local_port=?, peer_device_id=?,
                 peer_device_name=?, peer_port=?, link_type=?, speed=?, medium=?, remark=?
                WHERE id=?""",
            [*self._values(link), link.id],
        )

    @staticmethod
    def _values(link: DeviceLink) -> list[object]:
        # 对端选了台账里的设备时不再存文本名，避免两份数据不一致
        peer_name = None if link.peer_device_id else _clean(link.peer_device_name)
        return [
            link.device_id,
            _clean(link.local_port),
            link.peer_device_id,
            peer_name,
            _clean(link.peer_port),
            link.link_type,
            _clean(link.speed),
            _clean(link.medium),
            _clean(link.remark),
        ]

    def delete(self, link_id: int) -> None:
        self.db.execute("DELETE FROM device_link WHERE id=?", (link_id,))

    def count_for_device(self, device_id: int) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM device_link WHERE device_id=? OR peer_device_id=?",
                (device_id, device_id),
                default=0,
            )
            or 0
        )
