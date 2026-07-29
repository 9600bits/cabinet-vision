"""设备类型清单的业务规则。

类型是唯一一份「用户可以自己增删」的领域常量。清单存在库里，
每次变更后都把 constants 里的注册表刷一遍，界面下拉框和机柜图配色
下一次读就是新值。

两条硬规则：
- 兜底类型「其他」不能删、不能改名。设备类型认不出时要有地方可归。
- 改名要连带刷台账里的 dev_type，删除要把设备归到兜底类型。
  device.dev_type 是裸字符串没建外键，这两步不做就会留下悬空的类型名。
"""

from __future__ import annotations

import re

from ..constants import (
    DEFAULT_TYPE_COLOR,
    FALLBACK_DEVICE_TYPE,
    apply_device_types,
)
from ..database import Database
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import DeviceType
from ..repositories import DeviceTypeRepository

_MAX_NAME_LEN = 16
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class DeviceTypeService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = DeviceTypeRepository(db)

    # ---------- 注册表同步 ----------

    def sync_registry(self) -> None:
        """把库里的清单灌进 constants。打开库和每次变更后都要调。"""
        apply_device_types(self.repo.pairs())

    def bootstrap(self) -> None:
        """打开数据库时调一次：空清单补默认值，然后同步注册表。"""
        if self.repo.count() == 0:
            with self.db.transaction():
                self.repo.ensure_defaults()
        self.sync_registry()

    # ---------- 查询 ----------

    def list_types(self, with_counts: bool = True) -> list[DeviceType]:
        return self.repo.list_all(with_counts=with_counts)

    def names(self) -> list[str]:
        return [t.name for t in self.repo.list_all()]

    # ---------- 校验 ----------

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValidationError("类型名称不能为空")
        if len(cleaned) > _MAX_NAME_LEN:
            raise ValidationError(f"类型名称最多 {_MAX_NAME_LEN} 个字符")
        # 类型名会进 Excel 模板的说明文字，用 / 分隔，自己带 / 会读不清
        if "/" in cleaned or "、" in cleaned:
            raise ValidationError("类型名称不能包含「/」或「、」")
        return cleaned

    @staticmethod
    def _clean_color(color: str) -> str:
        cleaned = (color or "").strip() or DEFAULT_TYPE_COLOR
        if not _HEX_COLOR.match(cleaned):
            raise ValidationError("配色要填 #RRGGBB 格式，比如 #1668dc")
        return cleaned.lower()

    # ---------- 增改删 ----------

    def create(self, name: str, color: str = DEFAULT_TYPE_COLOR) -> DeviceType:
        clean_name = self._clean_name(name)
        clean_color = self._clean_color(color)
        if self.repo.exists(clean_name):
            raise ConflictError(f"类型「{clean_name}」已经存在")

        with self.db.transaction():
            self.repo.insert(clean_name, clean_color, self.repo.next_sort_order())
        self.sync_registry()
        created = self.repo.get(clean_name)
        if created is None:  # pragma: no cover - 刚插入必然在
            raise NotFoundError("类型保存后读取失败")
        return created

    def update(self, old_name: str, new_name: str, color: str) -> tuple[DeviceType, int]:
        """改名 / 改色。返回 (新类型, 跟着改名的设备数)。"""
        existing = self.repo.get(old_name)
        if existing is None:
            raise NotFoundError(f"类型「{old_name}」不存在")

        clean_name = self._clean_name(new_name)
        clean_color = self._clean_color(color)
        renaming = clean_name != old_name

        if renaming:
            if old_name == FALLBACK_DEVICE_TYPE:
                raise ValidationError(
                    f"「{FALLBACK_DEVICE_TYPE}」是兜底类型，不能改名。"
                    "识别不出的类型都要归到它下面。改配色可以。"
                )
            if self.repo.exists(clean_name):
                raise ConflictError(f"类型「{clean_name}」已经存在")

        moved = 0
        with self.db.transaction():
            if renaming:
                moved = self.repo.rename(old_name, clean_name, clean_color)
            else:
                self.repo.update_color(old_name, clean_color)
        self.sync_registry()

        updated = self.repo.get(clean_name)
        if updated is None:  # pragma: no cover
            raise NotFoundError("类型保存后读取失败")
        return updated, moved

    def delete(self, name: str) -> int:
        """删类型。用着它的设备归到兜底类型，返回受影响的设备数。"""
        if name == FALLBACK_DEVICE_TYPE:
            raise ValidationError(
                f"「{FALLBACK_DEVICE_TYPE}」是兜底类型，不能删除。"
                "删掉别的类型时，那些设备要归到它下面。"
            )
        if self.repo.get(name) is None:
            raise NotFoundError(f"类型「{name}」不存在")

        with self.db.transaction():
            # 兜底类型可能被手工删过，删之前先确保它在
            self.repo.ensure_name(FALLBACK_DEVICE_TYPE)
            moved = self.repo.delete(name, FALLBACK_DEVICE_TYPE)
        self.sync_registry()
        return moved

    def restore_defaults(self) -> int:
        """补回缺失的内置类型，返回补了几个。自定义类型和改过的配色都不动。"""
        with self.db.transaction():
            added = self.repo.ensure_defaults()
        self.sync_registry()
        return added

    def ensure_name(self, name: str) -> bool:
        """台账里出现清单外的类型时补一条。Excel 导入用。"""
        clean = (name or "").strip()
        if not clean:
            return False
        with self.db.transaction():
            added = self.repo.ensure_name(clean)
        if added:
            self.sync_registry()
        return added
