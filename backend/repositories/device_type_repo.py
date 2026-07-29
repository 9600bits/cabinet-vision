"""设备类型清单的读写。

name 是主键，台账 device.dev_type 存的就是这个名字（没建外键：
类型改名要连带刷设备，删类型要把设备归到兜底类型，都得走服务层的
显式逻辑，外键的 CASCADE / SET NULL 给不了这种语义）。
"""

from __future__ import annotations

import sqlite3

from ..constants import DEFAULT_DEVICE_TYPES, DEFAULT_TYPE_COLOR
from ..database import Database
from ..models import DeviceType

_BUILTIN_NAMES = frozenset(name for name, _ in DEFAULT_DEVICE_TYPES)


class DeviceTypeRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def to_type(row: sqlite3.Row) -> DeviceType:
        keys = row.keys()
        return DeviceType(
            name=row["name"],
            color=row["color"],
            sort_order=row["sort_order"],
            device_count=row["device_count"] if "device_count" in keys else 0,
            builtin=row["name"] in _BUILTIN_NAMES,
        )

    # ---------- 读 ----------

    def list_all(self, with_counts: bool = False) -> list[DeviceType]:
        if with_counts:
            sql = """
                SELECT t.name, t.color, t.sort_order,
                       (SELECT COUNT(*) FROM device d WHERE d.dev_type = t.name)
                           AS device_count
                  FROM device_type t
                 ORDER BY t.sort_order, t.name
            """
        else:
            sql = "SELECT name, color, sort_order FROM device_type ORDER BY sort_order, name"
        return [self.to_type(row) for row in self.db.query(sql)]

    def pairs(self) -> list[tuple[str, str]]:
        """(名称, 配色) 列表，用来刷 constants 里的注册表。"""
        return [
            (row["name"], row["color"])
            for row in self.db.query(
                "SELECT name, color FROM device_type ORDER BY sort_order, name"
            )
        ]

    def get(self, name: str) -> DeviceType | None:
        row = self.db.query_one(
            "SELECT name, color, sort_order FROM device_type WHERE name = ?", (name,)
        )
        return self.to_type(row) if row else None

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM device_type", default=0) or 0)

    def device_count(self, name: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM device WHERE dev_type = ?", (name,), 0
            )
            or 0
        )

    def next_sort_order(self) -> int:
        """新类型排在末尾，但要在「其他」前面 —— 兜底项固定 999。"""
        current = int(
            self.db.scalar(
                "SELECT MAX(sort_order) FROM device_type WHERE sort_order < 999",
                default=0,
            )
            or 0
        )
        return min(current + 10, 990)

    # ---------- 写 ----------

    def insert(self, name: str, color: str, sort_order: int) -> None:
        self.db.execute(
            "INSERT INTO device_type (name, color, sort_order) VALUES (?,?,?)",
            (name, color, sort_order),
        )

    def update_color(self, name: str, color: str) -> None:
        self.db.execute("UPDATE device_type SET color = ? WHERE name = ?", (color, name))

    def rename(self, old_name: str, new_name: str, color: str) -> int:
        """改名并同步台账里的 dev_type，返回跟着改的设备数。

        没有外键，所以这一步必须自己做；漏了的话那些设备的类型会变成
        清单里不存在的值，下次保存就被归到兜底类型，等于静默丢数据。
        """
        self.db.execute(
            "UPDATE device_type SET name = ?, color = ? WHERE name = ?",
            (new_name, color, old_name),
        )
        cur = self.db.execute(
            "UPDATE device SET dev_type = ? WHERE dev_type = ?", (new_name, old_name)
        )
        return cur.rowcount or 0

    def delete(self, name: str, fallback: str) -> int:
        """删类型，柜里已有的设备归到兜底类型。返回改动的设备数。"""
        cur = self.db.execute(
            "UPDATE device SET dev_type = ? WHERE dev_type = ?", (fallback, name)
        )
        self.db.execute("DELETE FROM device_type WHERE name = ?", (name,))
        return cur.rowcount or 0

    def ensure_defaults(self) -> int:
        """补齐缺失的内置类型，已有的不动（保留用户改过的配色）。"""
        added = 0
        for order, (name, color) in enumerate(DEFAULT_DEVICE_TYPES):
            sort_order = 999 if order == len(DEFAULT_DEVICE_TYPES) - 1 else order * 10
            if not self.exists(name):
                self.insert(name, color, sort_order)
                added += 1
        return added

    def ensure_name(self, name: str) -> bool:
        """台账里出现了清单外的类型时补一条，用于导入和迁移兜底。"""
        if self.exists(name):
            return False
        self.insert(name, DEFAULT_TYPE_COLOR, self.next_sort_order())
        return True
