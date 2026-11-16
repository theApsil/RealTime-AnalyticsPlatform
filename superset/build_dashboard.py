#!/usr/bin/env python3
"""Сборка дашборда «Погода» в Superset из созданных чартов (идемпотентно)."""
import http.cookiejar
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERSET_BASE", "http://localhost:8088/api/v1")
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
TITLE = "Погода — пайплайн данных"
SLUG = "weather-dashboard"

# id чартов: {name: chart_id}
CHARTS = {
    "Текущая температура": 4,
    "Всего показаний": 5,
    "Аномалий всего": 6,
    "Станций в сети": 7,
    "Температура за 24 часа": 8,
    "Температура по городам (7 дней)": 9,
    "Сезонный ход (месяц)": 10,
    "Суточная кривая (час)": 11,
    "Суточный ритм по городам": 12,
    "Типы погоды": 13,
    "Аномалии по городам": 14,
    "Распределение температуры по городам": 15,
    "Последние показания по станциям": 16,
}

TOK = None
CSRF = None


def req(m, p, d=None, auth=False):
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = "Bearer " + TOK
        if CSRF:
            h["X-CSRFToken"] = CSRF
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None,
                               headers=h, method=m)
    try:
        with OP.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def chart_node(slice_id, width, height):
    return {
        "children": [],
        "id": f"CHART-{slice_id}",
        "type": "CHART",
        "meta": {"width": width, "height": height, "sliceId": slice_id,
                 "sliceName": next((k for k, v in CHARTS.items() if v == slice_id), ""), "chartId": slice_id},
    }


def column_node(cid, children, width):
    return {
        "children": children,
        "id": f"COLUMN-{cid}",
        "type": "COLUMN",
        "meta": {"width": width, "background": "BACKGROUND_TRANSPARENT"},
    }


def build_layout():
    # helper: one chart wrapped in a column
    def col(col_id, slice_id, col_width, chart_height):
        return column_node(col_id, [f"CHART-{slice_id}"], col_width), {
            f"CHART-{slice_id}": chart_node(slice_id, col_width, chart_height)
        }

    pos = {}
    pos.update({"DASHBOARD_VERSION_KEY": "v2"})
    pos.update({"ROOT_ID": {"children": ["GRID_ID"], "id": "ROOT_ID", "type": "ROOT"}})
    pos.update({"HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": TITLE, "background": "BACKGROUND_TRANSPARENT"}}})

    rows = {}  # id -> children
    row_ids = []
    charts = {}

    # --- Строка 1: KPI (gauge + 3 числа) ---
    r1 = "ROW-KPI"
    row_ids.append(r1)
    kpi = [
        ("C-KPI-1", "Текущая температура", 3, 160),
        ("C-KPI-2", "Всего показаний", 3, 160),
        ("C-KPI-3", "Аномалий всего", 3, 160),
        ("C-KPI-4", "Станций в сети", 3, 160),
    ]
    row_kids = []
    for cid, name, w, h in kpi:
        coln, cnodes = col(cid, CHARTS[name], w, h)
        rows[f"COLUMN-{cid}"] = coln
        charts.update(cnodes)
        row_kids.append(f"COLUMN-{cid}")
    rows[r1] = column_node(r1.replace("ROW-", ""), row_kids, 12) if False else {
        "children": row_kids, "id": r1, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    # --- Строка 2: 24 часа (full width) ---
    r2 = "ROW-24H"
    row_ids.append(r2)
    c, cn = col("C-24H", CHARTS["Температура за 24 часа"], 12, 300)
    rows[f"COLUMN-C-24H"] = c
    charts.update(cn)
    rows[r2] = {"children": [f"COLUMN-C-24H"], "id": r2, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    # --- Строка 3: города + сезон ---
    r3 = "ROW-TREND"
    row_ids.append(r3)
    kids = []
    for cid, name, w, h in [
        ("C-CITY", "Температура по городам (7 дней)", 6, 320),
        ("C-SEAS", "Сезонный ход (месяц)", 6, 320),
    ]:
        coln, cnodes = col(cid, CHARTS[name], w, h)
        rows[f"COLUMN-{cid}"] = coln
        charts.update(cnodes)
        kids.append(f"COLUMN-{cid}")
    rows[r3] = {"children": kids, "id": r3, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    # --- Строка 4: heatmap + суточная ---
    r4 = "ROW-DIURNAL"
    row_ids.append(r4)
    kids = []
    for cid, name, w, h in [
        ("C-HEAT", "Суточный ритм по городам", 6, 340),
        ("C-DIUR", "Суточная кривая (час)", 6, 340),
    ]:
        coln, cnodes = col(cid, CHARTS[name], w, h)
        rows[f"COLUMN-{cid}"] = coln
        charts.update(cnodes)
        kids.append(f"COLUMN-{cid}")
    rows[r4] = {"children": kids, "id": r4, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    # --- Строка 5: pie + аномалии + box ---
    r5 = "ROW-DIST"
    row_ids.append(r5)
    kids = []
    for cid, name, w, h in [
        ("C-PIE", "Типы погоды", 4, 300),
        ("C-ANOM", "Аномалии по городам", 4, 300),
        ("C-BOX", "Распределение температуры по городам", 4, 300),
    ]:
        coln, cnodes = col(cid, CHARTS[name], w, h)
        rows[f"COLUMN-{cid}"] = coln
        charts.update(cnodes)
        kids.append(f"COLUMN-{cid}")
    rows[r5] = {"children": kids, "id": r5, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    # --- Строка 6: таблица последних показаний ---
    r6 = "ROW-TABLE"
    row_ids.append(r6)
    c, cn = col("C-TABLE", CHARTS["Последние показания по станциям"], 12, 320)
    rows[f"COLUMN-C-TABLE"] = c
    charts.update(cn)
    rows[r6] = {"children": [f"COLUMN-C-TABLE"], "id": r6, "type": "ROW", "meta": {"background": "BACKGROUND_TRANSPARENT"}}

    pos.update({"GRID_ID": {"children": row_ids, "id": "GRID_ID", "type": "GRID",
                            "meta": {"width": 12, "chartConfiguration": {}}}})
    pos.update(rows)
    pos.update(charts)
    return pos


def main():
    global TOK, CSRF
    code, data = req("POST", "/security/login",
                     {"username": os.environ.get("SUPERSET_ADMIN_USER", "admin"),
                      "password": os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"),
                      "provider": "db", "refresh": True})
    TOK = data["access_token"]
    _, c = req("GET", "/security/csrf_token/", auth=True)
    CSRF = c.get("result")
    print(f"[auth] token={len(TOK)}, csrf={bool(CSRF)}")

    position = build_layout()

    # ищем существующий дашборд по slug
    code, data = req("GET", "/dashboard/?q=(filters:!((col:slug,opr:eq,value:'weather-dashboard')))")
    existing = None
    for d in data.get("result", []):
        existing = d["id"]

    payload = {
        "dashboard_title": TITLE,
        "slug": SLUG,
        "published": True,
        "json_metadata": json.dumps({
            "timed_refresh_immune_slices": [],
            "expanded_slices": {},
            "refresh_frequency": 0,
            "default_filters": "{}",
            "chart_configuration": {},
            "color_scheme": "supersetColors",
            "cross_filters_enabled": True,
            "shared_label_colors": {},
            "label_colors": {},
            "chart_customization_config": [],
        }),
        "position_json": json.dumps(position),
    }

    if existing:
        code, data = req("PUT", f"/dashboard/{existing}", payload, auth=True)
        print(f"[dash] обновлён id={existing} ({code})")
    else:
        code, data = req("POST", "/dashboard/", payload, auth=True)
        if code not in (200, 201):
            print(f"[dash] ОШИБКА создания ({code}): {json.dumps(data, ensure_ascii=False)[:1500]}")
        else:
            print(f"[dash] создан id={data.get('id')} ({code})")
        existing = data.get("id")

    # результат: список чартов в раскладке
    chart_ids = [v for v in CHARTS.values()]
    print(f"[dash] чартов в дашборде: {len(chart_ids)}")
    print(f"[dash] URL: http://localhost:8088/superset/dashboard/{existing}/")


if __name__ == "__main__":
    main()