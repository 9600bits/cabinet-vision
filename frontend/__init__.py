"""机柜视界前端（PyQt6）。

只通过 backend.Backend 门面访问数据，不直接碰 SQL。
"""

from .app import run

__all__ = ["run"]
