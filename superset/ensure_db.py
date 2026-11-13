#!/usr/bin/env python3
"""Гарантирует наличие подключения к ClickHouse в метаданных Superset (таблица dbs).

Вызывается из entrypoint до старта сервера. Идемпотентно: если подключение
с именем SUPERSET_CLICKHOUSE_DB_NAME уже есть — ничего не делает.
Использует диалект clickhouse-connect по URI clickhousedb:// (рабочая связка).
"""
import datetime
import os
import sqlite3
import uuid

DB_PATH = "/app/superset_home/superset.db"
NAME = os.environ.get("SUPERSET_CLICKHOUSE_DB_NAME", "ClickHouse")
URI = os.environ.get(
    "SUPERSET_CLICKHOUSE_URI",
    "clickhousedb://default:clickhouse@clickhouse:8123/weather",
)

conn = sqlite3.connect(DB_PATH)
exists = conn.execute(
    "SELECT count(*) FROM dbs WHERE database_name = ?", (NAME,)
).fetchone()[0]
if exists:
    print(f"[ensure_db] подключение '{NAME}' уже есть — пропускаем")
    raise SystemExit(0)

now = datetime.datetime.utcnow()
conn.execute(
    """INSERT INTO dbs
        (created_on, changed_on, database_name, sqlalchemy_uri, allow_ctas,
         expose_in_sqllab, allow_run_async, configuration_method, uuid, is_managed_externally)
     VALUES (?,?,?,?,?,?,?,?,?,?)""",
    (
        now,
        now,
        NAME,
        URI,
        1,
        1,
        1,
        "dynamic_form",
        uuid.uuid4().bytes,  # Superset хранит uuid как 16 байт (BLOB)
        0,
    ),
)
conn.commit()
print(f"[ensure_db] создано подключение '{NAME}': {URI}")