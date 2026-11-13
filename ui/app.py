# -*- coding: utf-8 -*-
"""Веб-интерфейс платформы: статус сервисов, поток данных и просмотр данных ClickHouse.

Отдельный сервис в docker-compose (`ui`). Работает в общей compose-сети,
поэтому видит clickhouse и superset по их служебным именам.

Endpoints:
- GET /            — SPA-дашборд (статус + поток + данные)
- GET /api/status  — JSON: здоровье ClickHouse/Superset, поток данных генератора
- GET /api/tables  — JSON: список баз и таблиц ClickHouse со счётчиками строк
- GET /api/data    — JSON: превью строк таблицы (columns + rows, по limit)
"""
from __future__ import annotations

import os
import time
from typing import Any

import clickhouse_connect
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="RealTime Analytics Platform — UI")

CH = {
    "host": os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
    "port": int(os.environ.get("CLICKHOUSE_PORT", "8123")),
    "username": os.environ.get("CLICKHOUSE_USER", "default"),
    "password": os.environ.get("CLICKHOUSE_PASSWORD", "clickhouse"),
    "database": os.environ.get("CLICKHOUSE_DB", "weather"),
}
SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://superset:8088").rstrip("/")

POLL_SECONDS = int(os.environ.get("UI_POLL_SECONDS", "3"))


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


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # HTML — обычная (не f-)строка, поэтому плейсхолдер интерполируем через replace,
    # а не через {…} в шаблонной строке (иначе сломаются фигурные скобки CSS/JS).
    return HTML.replace("__POLL_SECONDS__", str(POLL_SECONDS))


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "clickhouse": check_clickhouse(),
        "superset": check_superset(),
        "generator": check_generator(),
        "poll_seconds": POLL_SECONDS,
    }


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


# --- SPA: одна HTML-страница, обновление по /api/status и /api/tables ---
HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RealTime Analytics Platform — UI</title>
<style>
:root{
  --bg:#0f1420; --card:#1a2133; --line:#2a3550; --txt:#e6e9f0; --mut:#8b94a8;
  --ok:#3ddc84; --bad:#ff5c5c; --warn:#ffb020; --acc:#5b8cff;
}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
header{padding:18px 24px;background:var(--card);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px}
header h1{font-size:18px;margin:0;font-weight:600}
header .sub{color:var(--mut);font-size:13px}
#clock{margin-left:auto;color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;padding:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 10px}
.card .big{font-size:28px;font-weight:700;margin:2px 0}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}
.pill.ok{background:rgba(61,220,132,.15);color:var(--ok)}
.pill.bad{background:rgba(255,92,92,.15);color:var(--bad)}
.pill.warn{background:rgba(255,176,32,.15);color:var(--warn)}
.mut{color:var(--mut);font-size:12px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.wide{grid-column:1/-1}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);text-transform:uppercase;font-size:11px;letter-spacing:.04em}
td.num{text-align:right;font-family:ui-monospace,Menlo,monospace}
.err{color:var(--bad)}
.tabs{display:flex;gap:8px;margin-bottom:14px}
.tab{padding:8px 16px;border-radius:8px;background:var(--card);border:1px solid var(--line);cursor:pointer;color:var(--txt);font-size:14px}
.tab.active{background:var(--acc);border-color:var(--acc);color:#fff}
select,button{background:#0f1420;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:14px}
button{cursor:pointer}
#dataView{display:none}
</style>
</head>
<body>
<header>
  <h1>🌤 RealTime Analytics Platform</h1>
  <span class="sub">статус · поток данных · ClickHouse</span>
  <span id="clock"></span>
</header>
<main>
  <div class="card">
    <h2>ClickHouse</h2>
    <div id="chPill" class="pill warn">…</div>
    <div id="chLatency" class="mut"></div>
  </div>
  <div class="card">
    <h2>Superset</h2>
    <div id="ssPill" class="pill warn">…</div>
    <div id="ssHttp" class="mut"></div>
  </div>
  <div class="card">
    <h2>Генератор</h2>
    <div id="genPill" class="pill warn">…</div>
    <div id="genStats" class="mut"></div>
  </div>
  <div class="card">
    <h2>Всего строк</h2>
    <div id="rowsTotal" class="big">—</div>
    <div id="rowsMinute" class="mut"></div>
  </div>
  <div class="card wide">
    <div class="tabs">
      <button class="tab active" id="tabStatus" onclick="showTab('status')">Статус</button>
      <button class="tab" id="tabData" onclick="showTab('data')">Данные в ClickHouse</button>
    </div>
    <div id="statusView">
      <h2>Поток данных за последнюю минуту</h2>
      <div id="flowDetail" class="mut"></div>
      <h2 style="margin-top:14px">Службы</h2>
      <div id="services"></div>
    </div>
    <div id="dataView">
      <h2>Просмотр таблиц</h2>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
        <select id="tableSel"></select>
        <label class="mut">limit
          <select id="limitSel">
            <option>10</option><option selected>20</option><option>50</option><option>100</option>
          </select>
        </label>
        <button onclick="loadData()">Обновить</button>
        <span id="dataMeta" class="mut"></span>
      </div>
      <div style="overflow:auto;max-height:60vh">
        <table id="dataTable"><thead></thead><tbody></tbody></table>
      </div>
    </div>
  </div>
</main>
<script>
const $=id=>document.getElementById(id);
function fmt(n){return (n==null)?'—':Number(n).toLocaleString('ru-RU');}
function pill(ok){return ok?'<span class="pill ok">OK</span>':'<span class="pill bad">FAIL</span>';}
function showTab(t){
  $('tabStatus').classList.toggle('active',t==='status');
  $('tabData').classList.toggle('active',t==='data');
  $('statusView').style.display=t==='status'?'block':'none';
  $('dataView').style.display=t==='data'?'block':'none';
  if(t==='data')loadTables();
}
function renderServices(s){
  const svc=[
    {n:'ClickHouse', ok:s.clickhouse.ok, d:s.clickhouse.ok?('latency '+s.clickhouse.latency_ms+' ms'):(s.clickhouse.error||'')},
    {n:'Superset', ok:s.superset.ok, d:s.superset.ok?('HTTP '+s.superset.http):(s.superset.error||'')},
    {n:'Генератор', ok:s.generator.ok, d:s.generator.ok?(s.generator.flowing?'пишет данные':'нет данных за минуту'):(s.generator.error||'')},
  ];
  $('services').innerHTML=svc.map(v=>
    `<div class="row"><span>${v.n}</span><span>${pill(v.ok)} <span class="mut">${v.d}</span></span></div>`
  ).join('');
}
async function loadStatus(){
  try{
    const s=await (await fetch('/api/status')).json();
    $('clock').textContent='обновлено '+new Date().toLocaleTimeString('ru-RU');
    $('chPill').outerHTML='<div id="chPill" class="pill '+(s.clickhouse.ok?'ok':'bad')+'">'+(s.clickhouse.ok?'OK':'FAIL')+'</div>';
    $('chLatency').textContent=s.clickhouse.ok?('latency '+s.clickhouse.latency_ms+' ms'):(s.clickhouse.error||'');
    $('ssPill').outerHTML='<div id="ssPill" class="pill '+(s.superset.ok?'ok':'bad')+'">'+(s.superset.ok?'OK':'FAIL')+'</div>';
    $('ssHttp').textContent=s.superset.ok?('HTTP '+s.superset.http):(s.superset.error||'');
    const g=s.generator;
    $('genPill').outerHTML='<div id="genPill" class="pill '+(g.ok?(g.flowing?'ok':'warn'):'bad')+'">'+(g.ok?(g.flowing?'ЛЬЁТ':'ПАУЗА'):'FAIL')+'</div>';
    $('genStats').innerHTML=g.ok
      ?('станций: '+fmt(g.stations)+' · последнее: <span class="mono">'+(g.max_timestamp||'—')+'</span>')
      :(g.error||'');
    $('rowsTotal').textContent=fmt(g.rows_total);
    $('rowsMinute').textContent=g.ok?('+'+fmt(g.rows_last_minute)+' за последнюю минуту'):'';
    $('flowDetail').innerHTML=g.ok
      ?('<div class="row"><span>Всего строк</span><span class="num">'+fmt(g.rows_total)+'</span></div>'
       +'<div class="row"><span>Строк за минуту</span><span class="num">'+fmt(g.rows_last_minute)+'</span></div>'
       +'<div class="row"><span>Уникальных станций</span><span class="num">'+fmt(g.stations)+'</span></div>'
       +'<div class="row"><span>Последняя запись</span><span class="mono">'+(g.max_timestamp||'—')+'</span></div>')
      :'<span class="err">'+g.error+'</span>';
    renderServices(s);
  }catch(e){$('clock').textContent='ошибка: '+e;}
}
async function loadTables(){
  const r=await (await fetch('/api/tables')).json();
  const sel=$('tableSel');
  sel.innerHTML=(r.tables||[]).map(t=>
    '<option value="'+t.database+'.'+t.table+'">'+t.database+'.'+t.table+' · '+fmt(t.rows)+'</option>'
  ).join('');
  if(r.tables&&r.tables.length)loadData();
}
async function loadData(){
  const sel=$('tableSel').value;
  const [db,table]=sel.split('.');
  const limit=$('limitSel').value;
  const r=await (await fetch('/api/data?db='+db+'&table='+table+'&limit='+limit)).json();
  $('dataMeta').textContent=r.error?('Ошибка: '+r.error):('показано '+r.row_count+' строк');
  const th=document.createElement('tr');
  th.innerHTML=(r.columns||[]).map(c=>'<th>'+c+'</th>').join('');
  $('dataTable').querySelector('thead').innerHTML=th.outerHTML;
  const tb=(r.rows||[]).map(row=>'<tr>'+row.map(v=>'<td class="'+(typeof v==='number'?'num':'')+'">'+(v==null?'':String(v))+'</td>').join('')+'</tr>').join('');
  $('dataTable').querySelector('tbody').innerHTML=tb;
}
loadStatus();
setInterval(loadStatus, __POLL_SECONDS__*1000);
showTab('status');
</script>
</body>
</html>
"""