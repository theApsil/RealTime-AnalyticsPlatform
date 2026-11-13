# -*- coding: utf-8 -*-
"""Веб-интерфейс платформы: статус сервисов, поток данных и просмотр данных ClickHouse.

Отдельный сервис в docker-compose (`ui`). Работает в общей compose-сети,
поэтому видит clickhouse, superset и generator по их служебным именам.
Фронтенд вынесен в отдельные статические файлы `./static` (index.html + CSS + JS).

Endpoints:
- GET /            — статический дашборд (status/static/index.html)
- GET /api/status  — JSON: здоровье ClickHouse/Superset, поток данных генератора
- GET /api/tables  — JSON: список баз и таблиц ClickHouse со счётчиками строк
- GET /api/data    — JSON: превью строк таблицы (columns + rows, по limit)
- GET/POST /api/control — прокси на control-endpoint генератора (скорость)
"""
from __future__ import annotations

import os
import time
from typing import Any

import clickhouse_connect
import requests
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="RealTime Analytics Platform — UI")

CH = {
    "host": os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
    "port": int(os.environ.get("CLICKHOUSE_PORT", "8123")),
    "username": os.environ.get("CLICKHOUSE_USER", "default"),
    "password": os.environ.get("CLICKHOUSE_PASSWORD", "clickhouse"),
    "database": os.environ.get("CLICKHOUSE_DB", "weather"),
}
SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://superset:8088").rstrip("/")
GENERATOR_CONTROL_URL = os.environ.get("GENERATOR_CONTROL_URL", "http://generator:9100").rstrip("/")

POLL_SECONDS = int(os.environ.get("UI_POLL_SECONDS", "3"))

# Каталог статики (index.html, style.css, app.js) рядом с этим файлом.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def index() -> str:
    return os.path.join(_STATIC_DIR, "index.html")


def _client() -> clickhouse_connect.driver.Client:
    """Прямой клиент ClickHouse (без привязки к конкретной БД в URL)."""
    return clickhouse_connect.get_client(**CH)


def _ch_query(sql: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    """Выполнить SQL в ClickHouse и вернуть строки. Кидает исключение при ошибке."""
    with _client() as client:
        result = client.query(sql, parameters=params)
    return result.result_rows


def check_clickhouse() -> dict[str, Any]:
    start = time.perf_counter()
    try:
        with _client() as client:
            pong = client.command("SELECT 1")
        return {"ok": True, "pong": pong == 1, "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001 — любой сбой сети наружу как статус
        return {"ok": False, "error": str(exc)}


def check_superset() -> dict[str, Any]:
    try:
        resp = requests.get(f"{SUPERSET_URL}/health", timeout=3)
        return {"ok": resp.status_code == 200, "http": resp.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def check_generator() -> dict[str, Any]:
    """Поток данных: общий счётчик, строки за последнюю минуту, последний timestamp."""
    db = CH["database"]
    now = time.time()
    try:
        rows_total = int(_ch_query(f"SELECT count() FROM {db}.readings")[0][0])
        rows_last_min = int(
            _ch_query(
                f"SELECT count() FROM {db}.readings WHERE timestamp >= now() - INTERVAL 1 MINUTE"
            )[0][0]
        )
        max_ts = _ch_query(f"SELECT max(timestamp) FROM {db}.readings")[0][0]
        stations = int(_ch_query(f"SELECT uniqExact(station_id) FROM {db}.readings")[0][0])
        return {
            "ok": True,
            "rows_total": rows_total,
            "rows_last_minute": rows_last_min,
            "max_timestamp": str(max_ts) if max_ts else None,
            "stations": stations,
            "flowing": rows_last_min > 0,
            "checked_at": time.strftime("%H:%M:%S", time.localtime(now)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "clickhouse": check_clickhouse(),
        "superset": check_superset(),
        "generator": check_generator(),
        "poll_seconds": POLL_SECONDS,
    }


@app.get("/api/control")
def control_get() -> dict[str, Any]:
    """Текущая скорость генератора (прокси на control-endpoint генератора)."""
    try:
        resp = requests.get(f"{GENERATOR_CONTROL_URL}/rate", timeout=3)
        return resp.json() if resp.ok else {"error": f"generator control: HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@app.post("/api/control")
def control_set(payload: dict[str, Any]) -> dict[str, Any]:
    """Меняет скорость генератора на лету (batch_size / interval_seconds)."""
    try:
        resp = requests.post(
            f"{GENERATOR_CONTROL_URL}/rate", json=payload, timeout=3
        )
        return resp.json() if resp.ok else {"error": f"generator control: HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@app.get("/api/tables")
def tables() -> dict[str, Any]:
    """Список баз и таблиц с количеством строк (безопасный allowlist по каталогу)."""
    db = CH["database"]
    try:
        rows = _ch_query(
            f"""
            SELECT database, name, total_rows
            FROM system.tables
            WHERE database = {{db:LowCardinality(String)}} AND total_rows IS NOT NULL
            ORDER BY name
            """,
            {"db": db},
        )
        out = []
        for database, name, total_rows in rows:
            out.append(
                {
                    "database": database,
                    "table": name,
                    "rows": int(total_rows),
                    "url": f"/api/data?db={database}&table={name}&limit=20",
                }
            )
        return {"tables": out}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tables": []}


@app.get("/api/data")
def data(
    db: str = Query(default="weather"),
    table: str = Query(default="readings"),
    limit: int = Query(default=20, ge=1, le=500),
) -> dict[str, Any]:
    """Превью строк таблицы: колонки + последние `limit` строк по времени, если есть."""
    try:
        # Подтверждаем, что таблица существует и доступна в нашей БД (безопасный allowlist).
        exists = _ch_query(
            "SELECT count() FROM system.tables WHERE database = {db:String} AND name = {t:String}",
            {"db": db, "t": table},
        )[0][0]
        if not exists:
            return {"error": f"Таблица {db}.{table} не найдена"}

        columns = _ch_query(f"DESCRIBE {db}.{table}")

        # Сортируем по первому временному столбцу, если он есть, чтобы показать свежие данные.
        order = ""
        for col in columns:
            if col[0].lower() in ("timestamp", "event_time", "time"):
                order = f" ORDER BY {col[0]} DESC"
                break

        rows = _ch_query(f"SELECT * FROM {db}.{table}{order} LIMIT {int(limit)}")
        return {
            "columns": [c[0] for c in columns],
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}