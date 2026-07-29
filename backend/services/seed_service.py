"""首次启动的示例数据，让各视图打开就有内容。设置页可以一键清空。"""

from __future__ import annotations

from ..database import Database

DEMO_FLAG = "demo_seeded"

# (机柜, 设备名, 起始U, 占U, 类型, 状态, 型号, 厂商, IP, 功耗W, 重量kg)
_DEMO_DEVICES: tuple[tuple, ...] = (
    ("A01", "SW-CORE-01", 40, 2, "交换机", "在用", "S12700E-4", "华为", "10.0.0.11", 900, 45),
    ("A01", "SW-CORE-02", 37, 2, "交换机", "在用", "S12700E-4", "华为", "10.0.0.12", 900, 45),
    ("A01", "FW-01", 34, 2, "防火墙", "在用", "USG6650E", "华为", "10.0.0.21", 350, 12),
    ("A01", "PDU-A01", 1, 1, "PDU", "在用", "PDU-32A", "APC", None, 0, 5),
    ("A02", "SW-ACC-A02-1", 42, 1, "交换机", "在用", "S5735-48T", "华为", "10.0.1.11", 150, 8),
    ("A02", "SW-ACC-A02-2", 41, 1, "交换机", "在用", "S5735-48T", "华为", "10.0.1.12", 150, 8),
    ("A02", "PP-A02-1", 40, 1, "配线架", "在用", "24口铜缆", "康普", None, 0, 3),
    ("A02", "SRV-APP-01", 20, 2, "服务器", "在用", "R740", "戴尔", "10.0.2.31", 750, 30),
    ("A02", "SRV-APP-02", 18, 2, "服务器", "备用", "R740", "戴尔", "10.0.2.32", 750, 30),
    ("A03", "RT-WAN-01", 42, 1, "路由器", "在用", "AR6300", "华为", "10.0.0.31", 260, 10),
    ("A03", "LB-01", 39, 2, "负载均衡", "在用", "BIG-IP i4800", "F5", "10.0.0.41", 400, 15),
    ("A03", "SW-OLD-01", 30, 1, "交换机", "故障", "S5720-28X", "华为", "10.0.1.90", 120, 7),
    ("B01", "SRV-DB-01", 36, 4, "服务器", "在用", "R750", "戴尔", "10.0.3.11", 1100, 38),
    ("B01", "STO-01", 28, 4, "存储", "在用", "OceanStor 5310", "华为", "10.0.3.51", 1400, 60),
    ("B02", "KVM-01", 42, 1, "KVM", "在用", "KVM-1116", "ATEN", "10.0.9.11", 40, 4),
    ("B02", "SW-ACC-B02-1", 40, 1, "交换机", "在用", "S5735-48T", "华为", "10.0.1.21", 150, 8),
)

# (本端设备, 本端口, 对端设备, 对端口, 类型, 速率, 介质)
_DEMO_LINKS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("SW-ACC-A02-1", "GE0/0/49", "SW-CORE-01", "XGE1/0/1", "上行", "10G", "光纤"),
    ("SW-ACC-A02-1", "GE0/0/50", "SW-CORE-02", "XGE1/0/1", "上行", "10G", "光纤"),
    ("SW-ACC-B02-1", "GE0/0/49", "SW-CORE-01", "XGE1/0/2", "上行", "10G", "光纤"),
    ("FW-01", "GE0/0/1", "SW-CORE-01", "XGE1/0/24", "互联", "10G", "光纤"),
    ("SRV-APP-01", "NIC1", "SW-ACC-A02-1", "GE0/0/1", "管理", "1G", "网线"),
)


class SeedService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def is_empty(self) -> bool:
        return int(self.db.scalar("SELECT COUNT(*) FROM room", default=0) or 0) == 0

    def seed_if_empty(self) -> bool:
        """空库时铺一份示例数据。返回是否真的写入了。"""
        if not self.is_empty():
            return False

        with self.db.transaction():
            room_id = self.db.insert(
                "INSERT INTO room (name, code, location, sort_order) VALUES (?,?,?,?)",
                ("示例机房", "IDC-A", "园区 3 号楼 2 层", 0),
            )
            row_ids = {
                name: self.db.insert(
                    "INSERT INTO rack_row (room_id, name, sort_order) VALUES (?,?,?)",
                    (room_id, name, order),
                )
                for order, name in enumerate(("A列", "B列"))
            }

            cabinet_ids: dict[str, int] = {}
            for row_name, cab_name, pos in (
                ("A列", "A01", 0), ("A列", "A02", 1), ("A列", "A03", 2),
                ("B列", "B01", 0), ("B列", "B02", 1),
            ):
                cabinet_ids[cab_name] = self.db.insert(
                    """INSERT INTO cabinet
                       (room_id, row_id, name, u_total, power_limit_w, weight_limit_kg, position_in_row)
                       VALUES (?,?,?,?,?,?,?)""",
                    (room_id, row_ids[row_name], cab_name, 42, 6000, 800, pos),
                )

            for cab, name, u_start, u_size, dev_type, status, model, vendor, ip, power, weight in _DEMO_DEVICES:
                self.db.insert(
                    """INSERT INTO device
                       (cabinet_id, name, u_start, u_size, dev_type, status, model, vendor,
                        mgmt_ip, power_w, weight_kg, install_date, warranty_end, owner, project)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cabinet_ids[cab], name, u_start, u_size, dev_type, status, model, vendor,
                        ip, power, weight, "2024-06-01", "2027-05-31", "张工", "园区网络",
                    ),
                )

            # 未上架设备，演示待上架列表
            for name, u_size, dev_type, model, vendor, power, weight in (
                ("SW-NEW-01", 1, "交换机", "S5735-48T", "华为", 150, 8),
                ("SRV-NEW-01", 2, "服务器", "R760", "戴尔", 800, 32),
            ):
                self.db.insert(
                    """INSERT INTO device
                       (name, u_size, dev_type, status, model, vendor, power_w, weight_kg, project)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (name, u_size, dev_type, "备用", model, vendor, power, weight, "二期扩容"),
                )

            for cab, u_start, u_size, label, project, owner, planned in (
                ("A02", 30, 4, "二期扩容预留", "二期扩容", "张工", "2026-09-01"),
                ("B02", 20, 8, "存储扩容预留", "存储扩容", "李工", "2026-12-01"),
            ):
                self.db.insert(
                    """INSERT INTO reservation
                       (cabinet_id, u_start, u_size, label, project, owner, planned_date)
                       VALUES (?,?,?,?,?,?,?)""",
                    (cabinet_ids[cab], u_start, u_size, label, project, owner, planned),
                )

            def device_id(name: str) -> int:
                return int(self.db.scalar("SELECT id FROM device WHERE name=?", (name,), 0) or 0)

            for local, local_port, peer, peer_port, link_type, speed, medium in _DEMO_LINKS:
                self.db.insert(
                    """INSERT INTO device_link
                       (device_id, local_port, peer_device_id, peer_port, link_type, speed, medium)
                       VALUES (?,?,?,?,?,?,?)""",
                    (device_id(local), local_port, device_id(peer), peer_port, link_type, speed, medium),
                )

            self.db.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?,?)", (DEMO_FLAG, "1")
            )
        return True

    def clear_all(self) -> None:
        """清空业务数据，保留表结构。

        device_type 不在清空范围内：那是配置而不是台账，自己加的类型
        不该因为清空数据就没了。要恢复内置清单用设置页的「恢复默认类型」。
        """
        with self.db.transaction():
            for table in (
                "device_link", "reservation", "device", "cabinet", "rack_row", "room"
            ):
                self.db.execute(f"DELETE FROM {table}")
            self.db.execute("DELETE FROM app_meta WHERE key=?", (DEMO_FLAG,))
        self.db.vacuum()
