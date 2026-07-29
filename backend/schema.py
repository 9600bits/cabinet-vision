"""数据库表结构与迁移。

每次改结构就在 MIGRATIONS 末尾追加一个新版本，不要修改已有版本的 SQL，
否则老库升级会对不上。
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE room (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    code        TEXT,
    location    TEXT,
    remark      TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE rack_row (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    remark      TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (room_id, name)
);

CREATE TABLE cabinet (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id          INTEGER NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    row_id           INTEGER REFERENCES rack_row(id) ON DELETE SET NULL,
    name             TEXT    NOT NULL,
    code             TEXT,
    u_total          INTEGER NOT NULL DEFAULT 42 CHECK (u_total > 0 AND u_total <= 100),
    power_limit_w    REAL,
    weight_limit_kg  REAL,
    position_in_row  INTEGER NOT NULL DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT '在用',
    remark           TEXT,
    UNIQUE (room_id, name)
);

CREATE INDEX idx_cabinet_room ON cabinet(room_id);
CREATE INDEX idx_cabinet_row  ON cabinet(row_id);

CREATE TABLE device (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id    INTEGER REFERENCES cabinet(id) ON DELETE SET NULL,
    name          TEXT    NOT NULL,
    u_start       INTEGER,
    u_size        INTEGER NOT NULL DEFAULT 1 CHECK (u_size >= 1),
    dev_type      TEXT    NOT NULL DEFAULT '其他',
    status        TEXT    NOT NULL DEFAULT '在用',
    model         TEXT,
    vendor        TEXT,
    sn            TEXT,
    asset_no      TEXT,
    mgmt_ip       TEXT,
    power_w       REAL,
    weight_kg     REAL,
    install_date  TEXT,
    warranty_end  TEXT,
    owner         TEXT,
    project       TEXT,
    remark        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_device_cabinet ON device(cabinet_id);
CREATE INDEX idx_device_name    ON device(name);
CREATE INDEX idx_device_sn      ON device(sn);
CREATE INDEX idx_device_asset   ON device(asset_no);
CREATE INDEX idx_device_ip      ON device(mgmt_ip);
CREATE INDEX idx_device_type    ON device(dev_type);
CREATE INDEX idx_device_status  ON device(status);

CREATE TABLE reservation (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id    INTEGER NOT NULL REFERENCES cabinet(id) ON DELETE CASCADE,
    u_start       INTEGER NOT NULL,
    u_size        INTEGER NOT NULL DEFAULT 1 CHECK (u_size >= 1),
    label         TEXT    NOT NULL DEFAULT '预留',
    project       TEXT,
    owner         TEXT,
    planned_date  TEXT,
    remark        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_reservation_cabinet ON reservation(cabinet_id);

CREATE TABLE device_link (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id         INTEGER NOT NULL REFERENCES device(id) ON DELETE CASCADE,
    local_port        TEXT,
    peer_device_id    INTEGER REFERENCES device(id) ON DELETE SET NULL,
    peer_device_name  TEXT,
    peer_port         TEXT,
    link_type         TEXT NOT NULL DEFAULT '上行',
    speed             TEXT,
    medium            TEXT,
    remark            TEXT
);

CREATE INDEX idx_link_device ON device_link(device_id);
CREATE INDEX idx_link_peer   ON device_link(peer_device_id);

CREATE TABLE app_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
""",
    ),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]
