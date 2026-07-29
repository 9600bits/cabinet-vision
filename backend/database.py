"""SQLite 连接管理与迁移。

设计要点：
- 一个 Database 实例对应一个 .db 文件，前端切换库就是换实例。
- 开启 WAL 和外键约束，写入用事务包起来。
- 迁移按 user_version 递增执行，失败整体回滚。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .errors import BackendError
from .schema import MIGRATIONS, SCHEMA_VERSION

APP_DIR_NAME = "机柜视界"
DB_FILE_NAME = "cabinet_vision.db"


def default_db_path() -> Path:
    """默认库位置：Windows 放 AppData\\Roaming，其他平台放 ~/.local/share。"""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path.home() / ".local" / "share"
    return base / APP_DIR_NAME / DB_FILE_NAME


class Database:
    """薄封装的 sqlite3 连接。仓储层通过它执行 SQL。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._depth = 0
        self.migrate()

    # ---------- 基础执行 ----------

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = self._conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> None:
        self._conn.executemany(sql, [tuple(p) for p in seq])

    def script(self, sql: str) -> None:
        self._conn.executescript(sql)

    # ---------- 事务 ----------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """支持嵌套调用，只有最外层真正提交或回滚。"""
        outermost = self._depth == 0
        if outermost:
            self._conn.execute("BEGIN")
        self._depth += 1
        try:
            yield self._conn
        except BaseException:
            self._depth -= 1
            if outermost:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        else:
            self._depth -= 1
            if outermost:
                self._conn.execute("COMMIT")

    @contextmanager
    def rollback_after(self) -> Iterator[sqlite3.Connection]:
        """跑完一定回滚，用于导入预检：能发现跨行冲突又不落库。"""
        if self._depth:
            raise BackendError("预检不能嵌套在其他事务里执行")
        self._conn.execute("BEGIN")
        self._depth += 1
        try:
            yield self._conn
        finally:
            self._depth -= 1
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    # ---------- 迁移与维护 ----------

    def migrate(self) -> None:
        current = int(self.scalar("PRAGMA user_version", default=0) or 0)
        if current >= SCHEMA_VERSION:
            return
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            # executescript 会先隐式提交，所以事务控制要写在脚本内部
            script = f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"
            try:
                self._conn.executescript(script)
            except sqlite3.Error as exc:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise BackendError(f"数据库迁移到版本 {version} 失败：{exc}") from exc

    def size_kb(self) -> int:
        if not self.path.exists():
            return 0
        return round(self.path.stat().st_size / 1024)

    def backup_to(self, target: str | Path) -> Path:
        """备份成单个文件。先 checkpoint 把 WAL 落盘，保证副本完整。"""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copyfile(self.path, target)
        return target

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")

    def close(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self._conn.close()
