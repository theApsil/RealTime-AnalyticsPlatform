# -*- coding: utf-8 -*-
"""Веб-интерфейс платформы: статус сервисов, поток данных и просмотр данных ClickHouse.

Отдельный сервис в docker-compose (`ui`). Работает в общей compose-сети,
поэтому видит clickhouse, superset и generator по их служебным именам.

Endpoints:
- GET /            — SPA-дашборд (статус + поток + данные + управление скоростью)
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
GENERATOR_CONTROL_URL = os.environ.get("GENERATOR_CONTROL_URL", "http://generator:9100").rstrip("/")

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


# --- SPA: одна HTML-страница, обновление по /api/status и /api/tables ---
HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RealTime Analytics Platform — UI</title>
<style>
:root{
  --bg:#0d1117; --surface:#161b22; --border:#21262d; --border-strong:#30363d;
  --text:#e6edf3; --muted:#8b949e;
  --accent:#58a6ff; --accent-weak:#1f2b45;
  --ok:#3fb950; --ok-bg:#12261a; --bad:#f85149; --bad-bg:#2d1216;
  --warn:#d29922; --warn-bg:#2e2413;
  --shadow:0 1px 3px rgba(0,0,0,.4);
  --radius:12px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;
  -webkit-font-smoothing:antialiased}
header{position:sticky;top:0;z-index:10;background:var(--surface);border-bottom:1px solid var(--border)}
.header-inner{max-width:1200px;margin:0 auto;padding:0 24px;height:60px;
  display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:28px;height:28px;border-radius:8px;background:var(--accent);
  display:flex;align-items:center;justify-content:center;color:#0d1117;font-size:15px;font-weight:700}
.brand-name{font-weight:650;font-size:15px;letter-spacing:-.01em}
.brand-sub{color:var(--muted);font-size:12.5px;margin-left:10px;padding-left:12px;border-left:1px solid var(--border)}
.header-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.live{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);
  background:var(--bg);border:1px solid var(--border);border-radius:999px;padding:4px 10px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block}
#clock{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
main{max-width:1200px;margin:0 auto;padding:28px 24px 48px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:18px 20px}
.card-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600}
.card-value{font-size:30px;font-weight:650;letter-spacing:-.02em;margin:6px 0 2px;font-variant-numeric:tabular-nums}
.card-sub{font-size:12.5px;color:var(--muted);margin-top:2px}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-top:10px}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.loading{background:var(--bg);color:var(--muted)}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
.panel-head{padding:18px 20px 0;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.seg{display:inline-flex;background:var(--bg);border:1px solid var(--border);border-radius:9px;padding:3px;gap:3px}
.seg button{border:none;background:transparent;color:var(--muted);font-size:13px;font-weight:550;
  padding:7px 14px;border-radius:7px;cursor:pointer;font-family:inherit;transition:.12s}
.seg button.active{background:var(--surface);color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.4)}
.panel-body{padding:20px}
.panel-body h2{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  font-weight:600;margin:4px 0 14px}
.rows .row{display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid var(--border)}
.rows .row:last-child{border-bottom:none}
.row-name{font-weight:550}
.row-val{font-variant-numeric:tabular-nums}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
select,input,button.ghost{background:var(--surface);color:var(--text);border:1px solid var(--border-strong);
  border-radius:8px;padding:8px 12px;font-size:13px;font-family:inherit}
select,input{background:var(--bg)}
button.ghost{cursor:pointer}
button.ghost:hover{border-color:#8b949e;background:var(--bg)}
button.primary{cursor:pointer;background:var(--accent);color:#0d1117;border:1px solid var(--accent);
  border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600;font-family:inherit}
button.primary:hover{filter:brightness(1.1)}
.preset{background:var(--bg);border:1px solid var(--border-strong);color:var(--text);
  border-radius:8px;padding:6px 12px;font-size:12px;cursor:pointer;font-family:inherit}
.preset:hover{border-color:var(--accent);color:var(--accent)}
#dataMeta{font-size:12.5px;color:var(--muted);margin-left:auto}
.table-wrap{overflow:auto;max-height:62vh;border:1px solid var(--border);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{position:sticky;top:0;background:#1c2129;text-align:left;padding:9px 14px;
  text-transform:uppercase;font-size:10.5px;letter-spacing:.06em;color:var(--muted);font-weight:600;
  border-bottom:1px solid var(--border)}
tbody td{padding:8px 14px;border-bottom:1px solid var(--border);white-space:nowrap;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#1c2129}
#dataView{display:none}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.err{color:var(--bad)}
.rate-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.rate-cur{font-size:15px;font-weight:600}
.chart-box{position:relative;margin-top:6px}
#rateErr{font-size:12.5px;color:var(--muted)}
#rateErr.ok{color:var(--ok)}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="brand">
      <div class="logo">◉</div>
      <div class="brand-name">RealTime Analytics</div>
    </div>
    <div class="brand-sub">статус · поток данных · ClickHouse</div>
    <div class="header-right">
      <span class="live"><span class="dot" id="liveDot"></span><span id="liveText">опрашиваю…</span></span>
      <span id="clock"></span>
    </div>
  </div>
</header>

<main>
  <div class="grid">
    <div class="card">
      <div class="card-label">ClickHouse</div>
      <div id="chPill" class="pill loading">…</div>
      <div id="chLatency" class="card-sub"></div>
    </div>
    <div class="card">
      <div class="card-label">Superset</div>
      <div id="ssPill" class="pill loading">…</div>
      <div id="ssHttp" class="card-sub"></div>
    </div>
    <div class="card">
      <div class="card-label">Генератор</div>
      <div id="genPill" class="pill loading">…</div>
      <div id="genStats" class="card-sub"></div>
    </div>
    <div class="card">
      <div class="card-label">Всего строк</div>
      <div id="rowsTotal" class="card-value">—</div>
      <div id="rowsMinute" class="card-sub"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <div class="seg">
        <button id="tabStatus" class="active" onclick="showTab('status')">Статус</button>
        <button id="tabData" onclick="showTab('data')">Данные в ClickHouse</button>
      </div>
    </div>
    <div class="panel-body">
      <div id="statusView">
        <h2>Задержка ClickHouse</h2>
        <div class="chart-box" id="latChart"><span class="mut">—</span></div>

        <h2 style="margin-top:22px">Интенсивность генерации</h2>
        <div class="rate-row">
          <span class="rate-cur" id="rateCur">—</span>
          <span class="mut">цель, записей/мин:</span>
          <input type="number" id="rateTarget" min="1" step="1000" placeholder="напр. 300000" style="width:160px">
          <button class="primary" onclick="applyRate()">Применить</button>
          <span id="rateErr"></span>
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
          <span class="mut">пресеты:</span>
          <button class="preset" onclick="applyRate(120000)">120к/мин</button>
          <button class="preset" onclick="applyRate(300000)">300к/мин</button>
          <button class="preset" onclick="applyRate(600000)">600к/мин</button>
        </div>

        <h2 style="margin-top:22px">Поток данных</h2>
        <div class="rows" id="flowDetail"></div>
        <h2 style="margin-top:22px">Службы</h2>
        <div class="rows" id="services"></div>
      </div>
      <div id="dataView">
        <h2>Просмотр таблиц</h2>
        <div class="controls">
          <select id="tableSel"></select>
          <select id="limitSel">
            <option>10</option><option selected>20</option><option>50</option><option>100</option>
          </select>
          <button class="ghost" onclick="loadData()">Обновить</button>
          <span id="dataMeta"></span>
        </div>
        <div class="table-wrap">
          <table id="dataTable"><thead></thead><tbody></tbody></table>
        </div>
      </div>
    </div>
  </div>
</main>

<script>
const $=id=>document.getElementById(id);
function fmt(n){return (n==null)?'—':Number(n).toLocaleString('ru-RU');}
function setPill(id,cls,label){const el=$(id);el.className='pill '+cls;el.textContent=label;}
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
    `<div class="row"><span class="row-name">${v.n}</span><span class="row-val">${v.ok?'✓':'✕'} <span class="mono" style="color:var(--muted)">${v.d}</span></span></div>`
  ).join('');
}
/* --- график latency --- */
const latSamples=[];
function renderLatency(){
  const el=$('latChart');
  if(!latSamples.length){el.innerHTML='<span class="mut">—</span>';return;}
  const W=900,H=110,pad=8;
  const vals=latSamples.map(s=>s.ms);
  const min=Math.min(...vals),max=Math.max(...vals),range=(max-min)||1;
  const pts=latSamples.map((s,i)=>{
    const x=pad+(i/(latSamples.length-1||1))*(W-2*pad);
    const y=H-pad-((s.ms-min)/range)*(H-2*pad);
    return x.toFixed(1)+','+y.toFixed(1);
  }).join(' ');
  const last=vals[vals.length-1];
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:110px;display:block">'
    +'<polyline points="'+pts+'" fill="none" stroke="var(--accent)" stroke-width="2"/>'
    +'</svg><div class="mut" style="margin-top:6px">'+last+' ms · последние '+latSamples.length+' отсчётов</div>';
}
/* --- управление скоростью --- */
let curRate=null;
async function loadControl(){
  const r=await (await fetch('/api/control')).json();
  if(r.error){$('rateCur').textContent='—';$('rateErr').textContent='control недоступен: '+r.error;return;}
  curRate=r;
  $('rateCur').textContent=fmt(r.records_per_minute)+' / мин · батч '+r.batch_size;
}
async function applyRate(target){
  const targetMin=target||parseInt($('rateTarget').value,10);
  const errEl=$('rateErr');
  if(!curRate||!targetMin||targetMin<=0){errEl.textContent='введите цель';return;}
  const interval=curRate.interval_seconds||1.0;
  const batch_size=Math.max(1,Math.round(targetMin/60*interval));
  const r=await (await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_size})})).json();
  if(r.error){errEl.textContent='Ошибка: '+r.error;errEl.className='';}
  else{
    curRate=r;
    $('rateCur').textContent=fmt(r.records_per_minute)+' / мин · батч '+r.batch_size;
    errEl.textContent='Применено ✓ ('+fmt(r.records_per_minute)+' / мин)';errEl.className='ok';
    $('rateTarget').value='';
    loadStatus();
  }
}
async function loadStatus(){
  try{
    const s=await (await fetch('/api/status')).json();
    const g=s.generator;
    $('liveText').textContent=g.ok&&g.flowing?'данные льются':'опрашиваю…';
    $('liveDot').style.background=(g.ok&&g.flowing)?'var(--ok)':'var(--warn)';
    $('clock').textContent='обновлено '+new Date().toLocaleTimeString('ru-RU');
    setPill('chPill', s.clickhouse.ok?'ok':'bad', s.clickhouse.ok?'OK':'FAIL');
    $('chLatency').textContent=s.clickhouse.ok?('latency '+s.clickhouse.latency_ms+' ms'):(s.clickhouse.error||'');
    if(s.clickhouse.ok){ latSamples.push({ms:s.clickhouse.latency_ms}); if(latSamples.length>60)latSamples.shift(); renderLatency(); }
    setPill('ssPill', s.superset.ok?'ok':'bad', s.superset.ok?'OK':'FAIL');
    $('ssHttp').textContent=s.superset.ok?('HTTP '+s.superset.http):(s.superset.error||'');
    setPill('genPill', g.ok?(g.flowing?'ok':'warn'):'bad', g.ok?(g.flowing?'ЛЬЁТ':'ПАУЗА'):'FAIL');
    $('genStats').innerHTML=g.ok
      ?('станций: '+fmt(g.stations)+' · последнее <span class="mono">'+(g.max_timestamp||'—')+'</span>')
      :(g.error||'');
    $('rowsTotal').textContent=fmt(g.rows_total);
    $('rowsMinute').textContent=g.ok?('+'+fmt(g.rows_last_minute)+' за последнюю минуту'):'';
    $('flowDetail').innerHTML=g.ok
      ?(`<div class="row"><span class="row-name">Всего строк</span><span class="row-val">${fmt(g.rows_total)}</span></div>
         <div class="row"><span class="row-name">Строк за минуту</span><span class="row-val">${fmt(g.rows_last_minute)}</span></div>
         <div class="row"><span class="row-name">Уникальных станций</span><span class="row-val">${fmt(g.stations)}</span></div>
         <div class="row"><span class="row-name">Последняя запись</span><span class="row-val mono">${g.max_timestamp||'—'}</span></div>`)
      :'<div class="err">'+g.error+'</div>';
    renderServices(s);
  }catch(e){$('clock').textContent='ошибка: '+e;}
}
async function loadTables(){
  const r=await (await fetch('/api/tables')).json();
  $('tableSel').innerHTML=(r.tables||[]).map(t=>
    '<option value="'+t.database+'.'+t.table+'">'+t.database+'.'+t.table+' · '+fmt(t.rows)+'</option>'
  ).join('');
  if(r.tables&&r.tables.length)loadData();
}
async function loadData(){
  const sel=$('tableSel').value;
  const [db,table]=sel.split('.');
  const limit=$('limitSel').value;
  const r=await (await fetch('/api/data?db='+db+'&table='+table+'&limit='+limit)).json();
  $('dataMeta').textContent=r.error?('Ошибка: '+r.error):(db+'.'+table+' · показано '+r.row_count);
  $('dataTable').querySelector('thead').innerHTML=(r.columns||[]).map(c=>'<th>'+c+'</th>').join('');
  $('dataTable').querySelector('tbody').innerHTML=(r.rows||[]).map(row=>
    '<tr>'+row.map(v=>'<td'+(typeof v==='number'?' class="mono"':'')+'>'+(v==null?'':String(v))+'</td>').join('')+'</tr>'
  ).join('');
}
loadStatus();
loadControl();
setInterval(loadStatus, __POLL_SECONDS__*1000);
setInterval(loadControl, 5000);
showTab('status');
</script>
</body>
</html>
"""