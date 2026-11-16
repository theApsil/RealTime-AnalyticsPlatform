#!/usr/bin/env python3
"""Провижининг дашборда погоды в Superset через REST API (идемпотентно).

Запуск: docker cp superset/provision_dashboard.py superset:/app/ && \\
        docker exec superset python3 /app/provision_dashboard.py
"""
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERSET_BASE", "http://localhost:8088/api/v1")
ADMIN_USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")
CH_DB_NAME = "ClickHouse"

TOKEN = None
CSRF = None
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _headers():
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    if CSRF:
        h["X-CSRFToken"] = CSRF
    return h


def _req(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=_headers(), method=method)
    try:
        with _OPENER.open(req, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode() or "{}")
        except Exception:
            err = {"raw": str(exc)}
        return exc.code, err


def login():
    global TOKEN, CSRF
    code, data = _req("POST", "/security/login",
                      {"username": ADMIN_USER, "password": ADMIN_PASSWORD, "provider": "db", "refresh": True})
    if code != 200:
        sys.exit(f"login failed: {code} {data}")
    TOKEN = data["access_token"]
    code, data = _req("GET", "/security/csrf_token/")
    if code == 200 and isinstance(data, dict):
        CSRF = data.get("result")
    print(f"[auth] token={len(TOKEN)}, csrf={bool(CSRF)}")


def db_id():
    code, data = _req("GET", "/database/?q=(page_size:100)")
    for d in data.get("result", []):
        if d["database_name"] == CH_DB_NAME:
            return d["id"]
    sys.exit(f"database {CH_DB_NAME} not found")


def get_dataset_id(table_name):
    code, data = _req("GET", "/dataset/?q=(page_size:200)")
    for d in data.get("result", []):
        if d["table_name"] == table_name:
            return d["id"]
    return None


def upsert_dataset(db, table_name, schema=None, sql=None, is_physical=True):
    existing = get_dataset_id(table_name)
    if existing is not None:
        print(f"[dataset] '{table_name}' уже есть (id={existing})")
        return existing
    payload = {"database": db, "table_name": table_name, "is_managed_externally": False}
    if is_physical:
        payload["schema"] = schema
    else:
        payload["sql"] = sql
        payload["schema"] = schema
    code, data = _req("POST", "/dataset/", payload)
    if code in (200, 201):
        new_id = data.get("id")
        print(f"[dataset] создан '{table_name}' id={new_id}")
        return new_id
    print(f"[dataset] ОШИБКА '{table_name}': {code} {data}")
    return None


def get_chart_id(slice_name):
    code, data = _req("GET", "/chart/?q=(page_size:500)")
    for c in data.get("result", []):
        if c["slice_name"] == slice_name:
            return c["id"]
    return None


def upsert_chart(slice_name, viz_type, ds_id, params):
    existing = get_chart_id(slice_name)
    if existing is not None:
        print(f"[chart] '{slice_name}' уже есть (id={existing})")
        return existing
    payload = {
        "slice_name": slice_name,
        "viz_type": viz_type,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
    }
    code, data = _req("POST", "/chart/", payload)
    if code in (200, 201):
        cid = data.get("id")
        print(f"[chart] создан '{slice_name}' id={cid}")
        return cid
    print(f"[chart] ОШИБКА '{slice_name}': {code} {data}")
    return None


def verify_chart(ds_id, viz_type, params):
    """Проверяет, что чарт-запрос выполняется без SQL-ошибки."""
    form = dict(params)
    form["datasource"] = f"{ds_id}__table"
    form["viz_type"] = viz_type
    form.pop("datasource", None)
    code, data = _req("POST", "/chart/data", {"form_data": form})
    if code == 201 and not data.get("errors") and data.get("result"):
        return True
    if isinstance(data, dict) and data.get("result"):
        return True
    return False


# --- Помощники метрик -------------------------------------------------------
def sql_metric(expr, label=None):
    return {"expressionType": "SQL", "sqlExpression": expr, "label": label or expr}


def simple_metric(col, agg, label=None):
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": col, "type": "FLOAT"},
        "aggregate": agg,
        "label": label or f"{agg}({col})",
    }


def main():
    login()
    db = db_id()
    print(f"DB: {CH_DB_NAME} id={db}")

    # --- Датасеты -------------------------------------------------------------
    readings = get_dataset_id("readings") or upsert_dataset(db, "readings", schema="weather")
    stations = upsert_dataset(db, "stations", schema="weather")
    readings_city = upsert_dataset(
        db, "readings_city", schema="weather", is_physical=False,
        sql=("SELECT r.station_id, r.timestamp, r.temperature_c, r.humidity_pct, "
             "r.pressure_hpa, r.wind_speed_ms, r.wind_direction_deg, r.weather_type, "
             "r.is_anomaly, s.city, s.latitude, s.longitude "
             "FROM weather.readings r LEFT JOIN weather.stations s ON r.station_id = s.station_id"),
    )
    current_reading = upsert_dataset(
        db, "current_reading", schema="weather", is_physical=False,
        sql=("SELECT argMax(temperature_c, timestamp) AS current_temp, "
             "argMax(humidity_pct, timestamp) AS current_humidity, "
             "argMax(pressure_hpa, timestamp) AS current_pressure, "
             "max(timestamp) AS last_ts FROM weather.readings"),
    )
    readings_hourly = upsert_dataset(
        db, "readings_hourly", schema="weather", is_physical=False,
        sql=("SELECT r.station_id, s.city, toStartOfHour(r.timestamp) AS ts, "
             "toHour(r.timestamp) AS hour, toMonth(r.timestamp) AS month, "
             "round(avg(r.temperature_c),2) AS avg_temp, "
             "sum(r.is_anomaly) AS anomalies, count() AS n "
             "FROM weather.readings r LEFT JOIN weather.stations s "
             "ON r.station_id = s.station_id "
             "GROUP BY r.station_id, s.city, ts, hour, month"),
    )
    latest_readings = upsert_dataset(
        db, "latest_readings", schema="weather", is_physical=False,
        sql=("SELECT s.city, r.station_id, "
             "argMax(r.temperature_c, r.timestamp) AS temp, "
             "argMax(r.humidity_pct, r.timestamp) AS humidity, "
             "argMax(r.weather_type, r.timestamp) AS weather, "
             "max(r.timestamp) AS ts "
             "FROM weather.readings r LEFT JOIN weather.stations s "
             "ON r.station_id = s.station_id GROUP BY s.city, r.station_id"),
    )
    print(f"datasets: readings={readings}, stations={stations}, city={readings_city}, "
          f"current={current_reading}, hourly={readings_hourly}, latest={latest_readings}")

    charts = []

    def add(name, viz, ds, params):
        cid = upsert_chart(name, viz, ds, params)
        ok = verify_chart(ds, viz, params) if cid else False
        print(f"   [verify] '{name}' -> {'OK' if ok else 'FAIL'}")
        charts.append((name, cid, ok))

    # --- KPI / Gauge ----------------------------------------------------------
    add("Текущая температура", "gauge_chart", current_reading, {
        "datasource": f"{current_reading}__table", "viz_type": "gauge_chart",
        "time_range": "No filter", "granularity_sqla": "last_ts",
        "metric": simple_metric("current_temp", "MAX"), "adhoc_filters": [],
        "color_scheme": "supersetColors", "row_limit": 10000,
    })
    add("Всего показаний", "big_number_total", readings, {
        "datasource": f"{readings}__table", "viz_type": "big_number_total",
        "time_range": "No filter", "granularity_sqla": "timestamp",
        "metric": sql_metric("COUNT(*)"), "adhoc_filters": [],
        "subheader": "", "color_picker": {"r": 0, "g": 191, "b": 179},
        "y_axis_format": "SMART_NUMBER", "time_format": "smart_date",
    })
    add("Аномалий всего", "big_number_total", readings, {
        "datasource": f"{readings}__table", "viz_type": "big_number_total",
        "time_range": "No filter", "granularity_sqla": "timestamp",
        "metric": simple_metric("is_anomaly", "SUM"), "adhoc_filters": [],
        "subheader": "", "color_picker": {"r": 224, "g": 67, "b": 54},
        "y_axis_format": "SMART_NUMBER", "time_format": "smart_date",
    })
    add("Станций в сети", "big_number_total", readings, {
        "datasource": f"{readings}__table", "viz_type": "big_number_total",
        "time_range": "No filter", "granularity_sqla": "timestamp",
        "metric": sql_metric("COUNT(DISTINCT station_id)"), "adhoc_filters": [],
        "subheader": "", "color_picker": {"r": 255, "g": 159, "b": 67},
        "y_axis_format": "SMART_NUMBER", "time_format": "smart_date",
    })

    # --- Временные ряды -------------------------------------------------------
    add("Температура за 24 часа", "echarts_timeseries_line", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "echarts_timeseries_line",
        "time_range": "Last 24 hours", "granularity_sqla": "ts", "time_grain_sqla": "PT1H",
        "x_axis": "ts", "metrics": [simple_metric("avg_temp", "AVG")], "groupby": [],
        "adhoc_filters": [], "series_type": "line", "smooth": True,
        "color_scheme": "supersetColors", "show_legend": False, "row_limit": 10000,
    })
    add("Температура по городам (7 дней)", "echarts_timeseries_line", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "echarts_timeseries_line",
        "time_range": "Last 7 days", "granularity_sqla": "ts", "time_grain_sqla": "PT1H",
        "x_axis": "ts", "metrics": [simple_metric("avg_temp", "AVG")], "groupby": ["city"],
        "adhoc_filters": [], "series_type": "line", "smooth": True,
        "color_scheme": "supersetColors", "show_legend": True, "row_limit": 10000,
    })
    add("Сезонный ход (месяц)", "echarts_timeseries_line", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "echarts_timeseries_line",
        "time_range": "No filter", "granularity_sqla": "ts", "time_grain_sqla": "P1M",
        "x_axis": "ts", "metrics": [simple_metric("avg_temp", "AVG")], "groupby": [],
        "adhoc_filters": [], "series_type": "line", "smooth": True,
        "color_scheme": "supersetColors", "show_legend": False, "row_limit": 10000,
    })

    # --- Паттерны -------------------------------------------------------------
    add("Суточная кривая (час)", "dist_bar", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "dist_bar",
        "time_range": "No filter", "granularity_sqla": "ts",
        "metrics": [simple_metric("avg_temp", "AVG")], "groupby": ["hour"],
        "columns": [], "adhoc_filters": [], "color_scheme": "supersetColors",
        "show_legend": False, "order_by_cols": [], "row_limit": 10000,
    })
    add("Суточный ритм по городам", "heatmap", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "heatmap",
        "time_range": "No filter", "granularity_sqla": "ts",
        "x_axis": "hour", "y_axis": "city",
        "metric": simple_metric("avg_temp", "AVG"), "adhoc_filters": [],
        "normalize_across": "heatmap", "show_legend": True, "row_limit": 10000,
    })
    add("Типы погоды", "pie", readings, {
        "datasource": f"{readings}__table", "viz_type": "pie",
        "time_range": "No filter", "granularity_sqla": "timestamp",
        "groupby": ["weather_type"], "metric": sql_metric("COUNT(*)"),
        "adhoc_filters": [], "show_legend": True, "label_type": "value",
        "color_scheme": "supersetColors", "row_limit": 10000, "outerRadius": 70,
    })
    add("Аномалии по городам", "dist_bar", readings_hourly, {
        "datasource": f"{readings_hourly}__table", "viz_type": "dist_bar",
        "time_range": "No filter", "granularity_sqla": "ts",
        "metrics": [simple_metric("anomalies", "SUM")], "groupby": ["city"],
        "columns": [], "adhoc_filters": [], "color_scheme": "supersetColors",
        "show_legend": False, "order_by_cols": [], "row_limit": 10000,
    })
    add("Распределение температуры по городам", "box_plot", readings_city, {
        "datasource": f"{readings_city}__table", "viz_type": "box_plot",
        "time_range": "No filter", "granularity_sqla": "timestamp",
        "metrics": [simple_metric("temperature_c", "AVG")], "adhoc_filters": [],
        "groupby": ["city"], "color_scheme": "supersetColors",
        "whisker_options": "Min/max (no whiskers)", "row_limit": 100000,
    })

    # --- Realtime / таблица ---------------------------------------------------
    add("Последние показания по станциям", "table", latest_readings, {
        "datasource": f"{latest_readings}__table", "viz_type": "table",
        "time_range": "No filter", "granularity_sqla": "ts",
        "columns": ["city", "temp", "humidity", "weather", "ts"],
        "all_columns": ["city", "temp", "humidity", "weather", "ts"],
        "metrics": [], "adhoc_filters": [], "row_limit": 10,
        "order_by_cols": [], "table_timestamp_format": "smart_date",
        "column_format": {}, "align_pn": False, "color_pn": False, "table_filter": False,
    })

    ok = [c for c in charts if c[2]]
    print(f"\n=== Итог: {len(ok)}/{len(charts)} чартов OK ===")
    for name, cid, good in charts:
        print(f"  {'OK ' if good else 'FAIL'} id={cid} {name}")


if __name__ == "__main__":
    main()