// RealTime Analytics — клиентский код дашборда.
// Графики — нативный SVG (без внешних CDN, надёжно в корп. сети).
// Семплы графиков сохраняются в localStorage, чтобы прогресс переживал перезагрузку.
const $=id=>document.getElementById(id);
const MAX_SAMPLES=60;

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
    `<div class="row"><span class="row-name">${v.n}</span><span class="row-val ${v.ok?'svc-ok':'svc-bad'}">${v.ok?'✓':'✕'} ${v.d}</span></div>`
  ).join('');
}

/* --- персистентность графиков (localStorage) --- */
const latSamples=[];   // задержка ClickHouse, мс
const rateSamples=[];  // поток генератора, строк/мин
function ts(){return new Date().toLocaleTimeString('ru-RU');}
function loadSamples(key, arr){
  try{
    const raw=localStorage.getItem(key);
    if(!raw)return;
    const d=JSON.parse(raw);
    if(Array.isArray(d)){arr.length=0;arr.push(...d.slice(-MAX_SAMPLES));}
  }catch(e){/* игнорируем битый кэш */}
}
function saveSamples(key, arr){
  try{localStorage.setItem(key, JSON.stringify(arr.slice(-MAX_SAMPLES)));}catch(e){/* квота/приватность */}
}

/* --- интерактивные графики (нативный SVG) --- */
function renderLineChart(id, data, opts){
  const el=$(id);
  const W=560,H=240,padL=46,padR=12,padT=14,padB=24;
  const innerW=W-padL-padR, innerH=H-padT-padB;
  const n=data.length;
  if(!n){el.innerHTML='<div class="mut">нет данных</div>';return;}
  const vals=data.map(d=>d.value);
  let min=Math.min(...vals), max=Math.max(...vals);
  if(min===max){min-=1;max+=1;}
  const padV=(max-min)*0.1; min-=padV; max+=padV;
  const x=i=>padL+(n===1?innerW/2:(i/(n-1))*innerW);
  const y=v=>padT+innerH-((v-min)/(max-min))*innerH;
  // сетка
  let g='';
  const yTicks=5, xTicks=6;
  for(let i=0;i<=yTicks;i++){
    const v=min+(max-min)*(i/yTicks), yy=y(v);
    g+='<line x1="'+padL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--border)" stroke-width="1"/>';
    g+='<text x="'+(padL-6)+'" y="'+(yy+3).toFixed(1)+'" fill="var(--muted)" font-size="9" text-anchor="end">'+Math.round(v*10)/10+'</text>';
  }
  for(let i=0;i<xTicks;i++){
    const xx=padL+(innerW)*(i/xTicks);
    g+='<line x1="'+xx.toFixed(1)+'" y1="'+padT+'" x2="'+xx.toFixed(1)+'" y2="'+(H-padB)+'" stroke="var(--border)" stroke-width="1"/>';
  }
  // линия + заливка под ней
  const pts=data.map((d,i)=>x(i).toFixed(1)+','+y(d.value).toFixed(1)).join(' ');
  const area=pts+' '+(W-padR).toFixed(1)+','+(H-padB)+' '+padL+','+(H-padB);
  el.innerHTML='<svg id="'+id+'-svg" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:100%;display:block">'
    +'<rect x="'+padL+'" y="'+padT+'" width="'+innerW+'" height="'+innerH+'" fill="none" pointer-events="all"/>'
    +g
    +'<polygon points="'+area+'" fill="'+opts.fill+'" stroke="none"/>'
    +'<polyline points="'+pts+'" fill="none" stroke="'+opts.color+'" stroke-width="2" stroke-linejoin="round"/>'
    +'<line id="'+id+'-guide" x1="0" y1="'+padT+'" x2="0" y2="'+(H-padB)+'" stroke="'+opts.color+'" stroke-width="1" stroke-dasharray="3,3" opacity="0"/>'
    +'<circle id="'+id+'-pt" r="4" fill="'+opts.color+'" opacity="0"/>'
    +'</svg><div id="'+id+'-tip" class="chart-tip"></div>';
  // интерактив: наведение
  const svg=$(id+'-svg'), guide=$(id+'-guide'), pt=$(id+'-pt'), tip=$(id+'-tip');
  const rect=svg.getBoundingClientRect();
  const scaleX=rect.width?W/rect.width:1;
  svg.addEventListener('mousemove',e=>{
    const rx=(e.clientX-rect.left)*scaleX;
    let idx=Math.round((rx-padL)/innerW*(n-1)); idx=Math.max(0,Math.min(n-1,idx));
    const xx=x(idx), yy=y(data[idx].value);
    guide.setAttribute('x1',xx); guide.setAttribute('x2',xx); guide.setAttribute('opacity',1);
    pt.setAttribute('cx',xx); pt.setAttribute('cy',yy); pt.setAttribute('opacity',1);
    tip.style.display='block';
    tip.style.left=((e.clientX-rect.left)+14)+'px';
    tip.style.top=((e.clientY-rect.top)-12)+'px';
    tip.innerHTML='<b>'+data[idx].value.toFixed(1)+' '+opts.unit+'</b><br><span style="color:var(--muted)">'+data[idx].label+'</span>';
  });
  svg.addEventListener('mouseleave',()=>{
    guide.setAttribute('opacity',0); pt.setAttribute('opacity',0); tip.style.display='none';
  });
}
function renderCharts(){
  renderLineChart('latChart', latSamples, {color:'var(--orange)', fill:'rgba(255,159,67,.08)', unit:'мс'});
  renderLineChart('rateChart', rateSamples, {color:'var(--teal)', fill:'rgba(45,212,191,.08)', unit:'стр/мин'});
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

/* --- остановка генератора --- */
async function stopGenerator(){
  const btn=$('stopBtn'), msg=$('stopMsg');
  if(!confirm('Остановить генератор? Данные перестанут поступать.'))return;
  btn.disabled=true; btn.textContent='Останавливаю…';
  msg.textContent='';
  const r=await (await fetch('/api/control/stop',{method:'POST'})).json();
  if(r.stopped){
    msg.textContent='Генератор остановлен ✓';
    btn.textContent='⏹ Остановлен';
  }else{
    msg.textContent='Ошибка: '+(r.error||'неизвестно');
    btn.disabled=false; btn.textContent='⏹ Стоп генератора';
  }
  loadStatus();
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
    if(s.clickhouse.ok){ latSamples.push({label:ts(), value:s.clickhouse.latency_ms}); if(latSamples.length>MAX_SAMPLES)latSamples.shift(); }
    if(g.ok){ rateSamples.push({label:ts(), value:g.rows_last_minute}); if(rateSamples.length>MAX_SAMPLES)rateSamples.shift(); }
    saveSamples('ui_latSamples', latSamples);
    saveSamples('ui_rateSamples', rateSamples);
    renderCharts();
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

/* --- инициализация: восстановить графики из localStorage и запустить опрос --- */
async function init(){
  loadSamples('ui_latSamples', latSamples);
  loadSamples('ui_rateSamples', rateSamples);
  renderCharts();
  let pollMs=3000;
  try{
    const s=await (await fetch('/api/status')).json();
    if(s.poll_seconds)pollMs=s.poll_seconds*1000;
  }catch(e){/* оставляем 3000 */}
  setInterval(loadStatus, pollMs);
  setInterval(loadControl, 5000);
  loadStatus();
  loadControl();
  showTab('status');
}
init();