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
import httpx
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


@app.post("/api/control/stop")
def control_stop() -> dict[str, Any]:
    """Останавливает генератор (graceful shutdown через control-endpoint)."""
    try:
        resp = requests.post(f"{GENERATOR_CONTROL_URL}/stop", timeout=3)
        return resp.json() if resp.ok else {"error": f"generator control: HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# --- Логи контейнеров через Docker API (unix-сокет) -------------------------
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")


def _docker_get(path: str) -> httpx.Response:
    transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
    with httpx.Client(transport=transport, base_url="http://docker", timeout=6) as client:
        return client.get(path)


def _demux_logs(data: bytes) -> str:
    """Разбирает мультиплексированный поток логов Docker (8-байтовые фреймы)."""
    out: list[str] = []
    i = 0
    while i + 8 <= len(data):
        stream_type = data[i]
        size = int.from_bytes(data[i + 4 : i + 8], "big")
        payload = data[i + 8 : i + 8 + size]
        if stream_type in (1, 2):  # stdout / stderr
            out.append(payload.decode("utf-8", "replace"))
        i += 8 + size
    return "".join(out)


@app.get("/api/containers")
def containers() -> dict[str, Any]:
    """Список контейнеров (для вкладки «Логи» и статуса контейнеров).

    Показываем только контейнеры compose-проекта: те, что подключены к
    кастомной (не bridge/host/none) сети. Мусорные exited-контейнеры из
    других проектов так отсекаются.
    """
    default_nets = {"bridge", "host", "none", "default"}
    try:
        data = _docker_get("/containers/json?all=1").json()
        out = []
        for c in data:
            nets = (c.get("NetworkSettings") or {}).get("Networks") or {}
            if not any(n not in default_nets for n in nets):
                continue  # контейнер вне compose-сети — пропускаем
            names = c.get("Names") or []
            name = names[0].lstrip("/") if names else c.get("Id", "")[:12]
            out.append(
                {
                    "name": name,
                    "image": c.get("Image"),
                    "state": c.get("State"),
                    "status": c.get("Status"),
                }
            )
        out.sort(key=lambda x: x["name"])
        return {"containers": out}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "containers": []}


@app.get("/api/logs")
def logs(
    name: str = Query(...),
    tail: int = Query(default=300, ge=10, le=5000),
) -> dict[str, Any]:
    """Последние строки логов контейнера по имени (точному или по префиксу)."""
    try:
        containers_data = _docker_get("/containers/json?all=1").json()
        cid: str | None = None
        for c in containers_data:
            names = [n.lstrip("/") for n in (c.get("Names") or [])]
            if name in names or any(n.startswith(name) for n in names):
                cid = c["Id"]
                break
        if cid is None:
            return {"error": f"контейнер «{name}» не найден", "logs": ""}
        resp = _docker_get(f"/containers/{cid}/logs?stdout=1&stderr=1&tail={tail}&timestamps=1")
        raw = resp.content
        text = _demux_logs(raw) if raw else ""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return {"logs": "\n".join(lines[-tail:])}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "logs": ""}


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


@app.get("/api/filter-options")
def filter_options(
    db: str = Query(default="weather"),
    table: str = Query(default="readings"),
) -> dict[str, Any]:
    """Значения для выпадающих фильтров по выбранной таблице."""
    try:
        out: dict[str, Any] = {}
        if table == "readings":
            out["station_id"] = [int(r[0]) for r in _ch_query(f"SELECT DISTINCT station_id FROM {db}.stations ORDER BY station_id")]
            out["weather_type"] = [r[0] for r in _ch_query(f"SELECT DISTINCT weather_type FROM {db}.readings ORDER BY weather_type")]
        elif table == "stations":
            out["city"] = [r[0] for r in _ch_query(f"SELECT DISTINCT city FROM {db}.stations ORDER BY city")]
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@app.get("/api/data")
def data(
    db: str = Query(default="weather"),
    table: str = Query(default="readings"),
    limit: int = Query(default=20, ge=1, le=500),
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    station_id: int | None = Query(default=None),
    weather_type: str | None = Query(default=None),
    is_anomaly: int | None = Query(default=None),
    search: str | None = Query(default=None),
    agg: str | None = Query(default=None),  # None | minute | hour
) -> dict[str, Any]:
    """Превью строк таблицы с фильтрами и опциональной агрегацией по времени."""
    try:
        exists = _ch_query(
            "SELECT count() FROM system.tables WHERE database = {db:String} AND name = {t:String}",
            {"db": db, "t": table},
        )[0][0]
        if not exists:
            return {"error": f"Таблица {db}.{table} не найдена"}

        columns = [c[0] for c in _ch_query(f"DESCRIBE {db}.{table}")]
        colset = set(columns)

        where: list[str] = []
        params: dict[str, Any] = {}
        if from_ts and "timestamp" in colset:
            where.append("timestamp >= toDateTime64({from_ts:String}, 3)")
            params["from_ts"] = from_ts
        if to_ts and "timestamp" in colset:
            where.append("timestamp <= toDateTime64({to_ts:String}, 3)")
            params["to_ts"] = to_ts
        if station_id is not None and "station_id" in colset:
            where.append("station_id = {station_id:UInt32}")
            params["station_id"] = station_id
        if weather_type and "weather_type" in colset:
            where.append("weather_type = {weather_type:String}")
            params["weather_type"] = weather_type
        if is_anomaly is not None and "is_anomaly" in colset:
            where.append("is_anomaly = {is_anomaly:UInt8}")
            params["is_anomaly"] = is_anomaly
        if search:
            like_cols = [c for c in ("name", "city", "weather_type") if c in colset]
            if like_cols:
                cond = " OR ".join(f"{c} ILIKE {{search:String}}" for c in like_cols)
                where.append(f"({cond})")
                params["search"] = f"%{search}%"
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        if agg in ("minute", "hour"):
            step = "toStartOfMinute(timestamp)" if agg == "minute" else "toStartOfHour(timestamp)"
            sql = (
                f"SELECT {step} AS bucket, count() AS n, "
                f"round(avg(temperature_c), 2) AS avg_temp, "
                f"round(min(temperature_c), 2) AS min_temp, "
                f"round(max(temperature_c), 2) AS max_temp, "
                f"round(avg(humidity_pct), 2) AS avg_humidity "
                f"FROM {db}.{table}{where_sql} "
                f"GROUP BY bucket ORDER BY bucket DESC LIMIT {int(limit)}"
            )
            rows = _ch_query(sql, params)
            return {
                "columns": ["bucket", "n", "avg_temp", "min_temp", "max_temp", "avg_humidity"],
                "rows": rows,
                "row_count": len(rows),
                "agg": agg,
            }

        order = ""
        for col in columns:
            if col.lower() in ("timestamp", "event_time", "time"):
                order = f" ORDER BY {col} DESC"
                break
        rows = _ch_query(f"SELECT * FROM {db}.{table}{where_sql}{order} LIMIT {int(limit)}", params)
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}