"""设备台账的业务规则：校验、上下架、批量操作、连接关系。"""

from __future__ import annotations

import re

from ..constants import DEVICE_STATUSES, DEVICE_TYPES, LINK_TYPES
from ..database import Database
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import Device, DeviceLink, DeviceQuery, IncomingLink
from ..repositories import DeviceRepository, LinkRepository, PlaceRepository
from .occupancy import OccupancyService


class DeviceService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.devices = DeviceRepository(db)
        self.places = PlaceRepository(db)
        self.links = LinkRepository(db)
        self.occupancy = OccupancyService(db)

    # ---------- 查询 ----------

    def query(self, q: DeviceQuery) -> list[Device]:
        return self.devices.query(q)

    def count(self, q: DeviceQuery) -> int:
        return self.devices.count(q)

    def get(self, device_id: int) -> Device:
        device = self.devices.get(device_id)
        if device is None:
            raise NotFoundError("设备不存在")
        return device

    def list_unracked(self, keyword: str = "") -> list[Device]:
        return self.devices.query(DeviceQuery(keyword=keyword, unracked_only=True))

    def suggestions(self, column: str) -> list[str]:
        return self.devices.distinct_values(column)

    # ---------- 保存 ----------

    def _normalize(self, d: Device) -> Device:
        if not d.name or not d.name.strip():
            raise ValidationError("设备名不能为空")
        d.name = d.name.strip()
        d.u_size = max(1, int(d.u_size or 1))
        if d.dev_type not in DEVICE_TYPES:
            d.dev_type = "其他"
        if d.status not in DEVICE_STATUSES:
            d.status = "在用"
        # 没有机柜就不该有 U 位，避免出现"没柜子却有位置"的脏数据
        if not d.cabinet_id:
            d.cabinet_id = None
            d.u_start = None
        if d.cabinet_id and self.places.get_cabinet(d.cabinet_id) is None:
            raise NotFoundError("指定的机柜不存在")
        return d

    def save(self, d: Device) -> Device:
        d = self._normalize(d)

        if d.cabinet_id and d.u_start is not None and d.status != "已下架":
            check = self.occupancy.check(
                d.cabinet_id,
                d.u_start,
                d.u_size,
                exclude_kind="device" if d.id else "",
                exclude_id=d.id or 0,
            )
            if not check.ok:
                raise ConflictError(check.message)

        with self.db.transaction():
            if d.id:
                self.get(d.id)  # 确认存在
                self.devices.update(d)
                device_id = d.id
            else:
                device_id = self.devices.insert(d)
        return self.get(device_id)

    def delete(self, device_ids: list[int]) -> int:
        with self.db.transaction():
            return self.devices.delete(device_ids)

    # ---------- 复制 ----------

    def next_copy_name(self, name: str) -> str:
        """给复制出来的设备起个不重名的名字。

        末尾是数字就递增，并保持原来的位数（PDU-09 -> PDU-10，不是 -010）；
        没有数字就加「-副本」。都要往后找到第一个没被占用的。
        """
        name = (name or "").strip()
        if not name:
            return "新设备"

        match = re.search(r"^(.*?)(\d+)$", name)
        if match:
            prefix, digits = match.group(1), match.group(2)
            width = len(digits)
            number = int(digits)
            for _ in range(10000):
                number += 1
                # 位数够就补零对齐，超了就自然变长
                candidate = f"{prefix}{number:0{width}d}"
                if self.devices.find_by_name(candidate) is None:
                    return candidate
            return f"{name}-副本"

        # 已经是「xxx-副本」的，别再套一层
        base = re.sub(r"-副本\d*$", "", name)
        for i in range(1, 10000):
            candidate = f"{base}-副本" if i == 1 else f"{base}-副本{i}"
            if self.devices.find_by_name(candidate) is None:
                return candidate
        return f"{base}-副本"

    def copy_of(self, device_id: int) -> Device:
        """按现有设备造一个「待保存」的副本，不落库。

        同型号设备台账里往往一大片，型号厂商功耗这些照抄；
        SN / 资产号 / 管理 IP 是每台唯一的，留空让人填。
        U 位也留空 —— 原位置已经被占了，抄过来必然冲突，
        存下来先进待上架，再拖到想放的地方。
        机柜保留，方便就近放。
        """
        src = self.get(device_id)
        return Device(
            id=0,
            name=self.next_copy_name(src.name),
            cabinet_id=src.cabinet_id,
            u_start=None,
            u_size=src.u_size,
            dev_type=src.dev_type,
            status=src.status,
            model=src.model,
            vendor=src.vendor,
            sn=None,
            asset_no=None,
            mgmt_ip=None,
            power_w=src.power_w,
            weight_kg=src.weight_kg,
            install_date=src.install_date,
            warranty_end=src.warranty_end,
            owner=src.owner,
            project=src.project,
            remark=src.remark,
        )

    # ---------- 位置调整 ----------

    def move(self, device_id: int, cabinet_id: int | None, u_start: int | None) -> Device:
        device = self.get(device_id)
        if cabinet_id and self.places.get_cabinet(cabinet_id) is None:
            raise NotFoundError("目标机柜不存在")

        if cabinet_id and u_start is not None:
            check = self.occupancy.check(
                cabinet_id, u_start, device.u_size, exclude_kind="device", exclude_id=device_id
            )
            if not check.ok:
                raise ConflictError(check.message)

        with self.db.transaction():
            self.devices.move(device_id, cabinet_id, u_start)
        return self.get(device_id)

    def unrack(self, device_ids: list[int]) -> int:
        """批量下架：清掉机柜和 U 位，设备本身留在台账里。"""
        moved = 0
        with self.db.transaction():
            for device_id in device_ids:
                self.devices.move(device_id, None, None)
                moved += 1
        return moved

    def auto_rack(
        self, device_ids: list[int], cabinet_id: int
    ) -> tuple[list[tuple[int, int]], list[tuple[str, str]]]:
        """批量上架，自动从底部往上找连续空位。

        返回 (成功列表[(设备id, 起始U)], 失败列表[(设备名, 原因)])。
        """
        if self.places.get_cabinet(cabinet_id) is None:
            raise NotFoundError("目标机柜不存在")

        placed: list[tuple[int, int]] = []
        failed: list[tuple[str, str]] = []
        with self.db.transaction():
            for device_id in device_ids:
                device = self.devices.get(device_id)
                if device is None:
                    continue
                if device.status == "已下架":
                    failed.append((device.name, "状态为已下架，先改成在用或备用再上架"))
                    continue
                slot = self.occupancy.find_free_slot(cabinet_id, device.u_size)
                if slot is None:
                    failed.append((device.name, f"机柜里找不到 {device.u_size}U 连续空位"))
                    continue
                self.devices.move(device_id, cabinet_id, slot)
                placed.append((device_id, slot))
        return placed, failed

    def bulk_update(self, device_ids: list[int], patch: dict[str, object]) -> int:
        if patch.get("dev_type") and patch["dev_type"] not in DEVICE_TYPES:
            raise ValidationError("设备类型不在可选范围内")
        if patch.get("status") and patch["status"] not in DEVICE_STATUSES:
            raise ValidationError("设备状态不在可选范围内")
        with self.db.transaction():
            return self.devices.bulk_update_fields(device_ids, patch)

    # ---------- 连接关系 ----------

    def list_links(self, device_id: int) -> tuple[list[DeviceLink], list[IncomingLink]]:
        return self.links.list_outgoing(device_id), self.links.list_incoming(device_id)

    def save_link(self, link: DeviceLink) -> DeviceLink:
        if not link.device_id:
            raise ValidationError("连接必须归属一台设备")
        if link.link_type not in LINK_TYPES:
            link.link_type = "上行"
        has_peer = bool(link.peer_device_id) or bool((link.peer_device_name or "").strip())
        if not has_peer:
            raise ValidationError("对端设备不能为空，可以从台账里选，也可以直接填名称")
        if link.peer_device_id and link.peer_device_id == link.device_id:
            raise ValidationError("对端设备不能是自己")
        if link.peer_device_id and self.devices.get(link.peer_device_id) is None:
            raise NotFoundError("对端设备不存在")

        with self.db.transaction():
            if link.id:
                self.links.update(link)
                link_id = link.id
            else:
                link_id = self.links.insert(link)

        for item in self.links.list_outgoing(link.device_id):
            if item.id == link_id:
                return item
        raise NotFoundError("连接保存后读取失败")

    def delete_link(self, link_id: int) -> None:
        with self.db.transaction():
            self.links.delete(link_id)
