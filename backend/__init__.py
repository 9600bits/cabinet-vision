"""机柜视界后端。

分层：database（连接与迁移）→ repositories（SQL）→ services（业务规则）→ api.Backend（门面）。
前端只依赖 api.Backend 和 models 里的 dataclass，不碰下面几层。
"""

from .api import Backend
from .database import Database, default_db_path
from .errors import BackendError, ConflictError, NotFoundError, ValidationError
from .models import DeviceType

__all__ = [
    "Backend",
    "DeviceType",
    "Database",
    "default_db_path",
    "BackendError",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
]
