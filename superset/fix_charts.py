#!/usr/bin/env python3
"""Точечные правки чартов: структура KPI под известный рабочий шаблон + time_range."""
import http.cookiejar
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERSET_BASE", "http://localhost:8088/api/v1")
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
TOK = CSRF = None


def req(m, p, d=None, auth=False):
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = "Bearer " + TOK
        if CSRF:
            h["X-CSRFToken"] = CSRF
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, headers=h, method=m)
    try:
        with OP.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def temporal_filter(subject):
    return {"clause": "WHERE", "comparator": "No filter", "expressionType": "SIMPLE",
            "operator": "TEMPORAL_RANGE", "subject": subject}


def update(cid, params):
    code, data = req("PUT", f"/chart/{cid}",
                     {"slice_name": params["slice_name"], "viz_type": params["viz_type"],
                      "datasource_id": params["datasource_id"], "datasource_type": "table",
                      "params": json.dumps(params["params"])}, auth=True)
    print(f"[update] id={cid} -> {code}")
    if code not in (200, 201):
        print("   ", json.dumps(data)[:200])


def main():
    global TOK, CSRF
    _, data = req("POST", "/security/login",
                  {"username": os.environ.get("SUPERSET_ADMIN_USER", "admin"),
                   "password": os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"),
                   "provider": "db", "refresh": True})
    TOK = data["access_token"]
    _, c = req("GET", "/security/csrf_token/", auth=True)
    CSRF = c.get("result")

    # big_number на readings (5,6,7): структура как у рабочего чарта 1
    for cid, metric, sub in [(5, {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "COUNT(*)"}, "Всего показаний"),
                             (6, {"expressionType": "SIMPLE", "column": {"column_name": "is_anomaly", "type": "FLOAT"},
                                  "aggregate": "SUM", "label": "SUM(is_anomaly)"}, "Аномалий всего"),
                             (7, {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT station_id)",
                                  "label": "COUNT(DISTINCT station_id)"}, "Станций в сети")]:
        update(cid, {
            "slice_name": sub, "viz_type": "big_number_total", "datasource_id": 1,
            "params": {
                "viz_type": "big_number_total", "datasource": "1__table",
                "metric": metric,
                "adhoc_filters": [temporal_filter("timestamp")],
                "subheader": "", "y_axis_format": "SMART_NUMBER", "time_format": "smart_date",
            }})

    # gauge (4) на current_reading
    update(4, {
        "slice_name": "Текущая температура", "viz_type": "gauge_chart", "datasource_id": 4,
        "params": {
            "viz_type": "gauge_chart", "datasource": "4__table",
            "metric": {"expressionType": "SIMPLE", "column": {"column_name": "current_temp", "type": "FLOAT"},
                       "aggregate": "MAX", "label": "MAX(current_temp)"},
            "adhoc_filters": [temporal_filter("last_ts")],
            "color_scheme": "supersetColors", "row_limit": 10000,
        }})

    # 24ч (8): time_range Last 24 hours -> Last 1 day
    _, ch = req("GET", "/chart/8", auth=True)
    p = json.loads(ch["result"]["params"])
    p["time_range"] = "Last 1 day"
    update(8, {"slice_name": "Температура за 24 часа", "viz_type": "echarts_timeseries_line",
               "datasource_id": 5, "params": p})


if __name__ == "__main__":
    main()