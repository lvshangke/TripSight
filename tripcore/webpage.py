"""网页工作台的页面（单个自包含 HTML，地图脚本内嵌，只有底图瓦片要联网）。"""

from pathlib import Path

_ASSETS = Path(__file__).with_name("assets")

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TripSight 工作台</title>
<style>__CSS__</style>
<style>
html,body{height:100%;margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222;background:#fafafa}
#app{display:flex;height:100%}
#side{width:400px;max-width:50vw;display:flex;flex-direction:column;border-right:1px solid #ddd;background:#fff}
#scroll{flex:1;overflow:auto}
#map{flex:1;height:100%}
header{padding:10px 12px;border-bottom:1px solid #ddd;display:flex;align-items:center;gap:8px}
header b{flex:1;font-size:16px}
button{border:1px solid #bbb;border-radius:6px;background:#fff;padding:4px 10px;cursor:pointer;color:#222}
button:disabled{opacity:.4;cursor:default}
button.pri{background:#2563eb;border-color:#2563eb;color:#fff}
#msg{padding:6px 12px;font-size:13px;color:#555;min-height:18px}
#msg.err{color:#b91c1c}
.sec{border-bottom:1px solid #eee;padding:8px 12px}
.sec h3{margin:0 0 6px;font-size:14px;display:flex;justify-content:space-between;align-items:center}
#cal .nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
#cal table{width:100%;border-collapse:collapse;text-align:center;font-size:13px}
#cal td,#cal th{padding:0}
#cal td button{width:100%;border:0;border-radius:4px;padding:5px 0;background:none}
#cal td button:hover{background:#e8efff}
#cal td.fc button{background:#f1f8e9}
#cal td.in button{background:#dbeafe}
#cal td.edge button{background:#2563eb;color:#fff}
#calinfo{font-size:13px;margin:6px 0;color:#444}
.day{border:1px dashed transparent;border-radius:6px;margin:4px 0;padding:2px}
.day.over{border-color:#2563eb;background:#eff6ff}
.dh{font-weight:600;font-size:13px;padding:4px 2px;cursor:pointer;display:flex;gap:6px;align-items:center}
.dh .dot{width:10px;height:10px;border-radius:50%}
.card{display:flex;gap:6px;align-items:center;background:#fff;border:1px solid #ddd;border-radius:6px;padding:6px 8px;margin:4px 0;cursor:grab}
.card.drag{opacity:.4}
.card .n{font-size:12px;color:#fff;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;flex:none}
.card .nm{flex:1;font-size:14px}
.card .tm{font-size:12px;color:#666;font-variant-numeric:tabular-nums}
.card .mv button{padding:0 5px;font-size:11px}
.ins{height:3px;background:#2563eb;border-radius:2px;margin:-2px 0}
.empty{font-size:12px;color:#999;padding:6px}
.leg,.meal,.info{font-size:12px;color:#555;padding:2px 8px 2px 34px}
.leg .real{color:#15803d}.leg .est{color:#b45309}
.sub{font-size:11px;color:#888;margin-top:1px}
.meal{background:#fff8ed;border-radius:6px;margin:2px 0;padding:4px 8px 4px 34px}
.card .nm small{display:block;font-size:11px;color:#888}
a{color:#2563eb;text-decoration:none}
#prev{font-size:13px;border-top:2px solid #2563eb;padding:8px 12px;background:#f8fbff;display:none;max-height:40%;overflow:auto}
#prev ul{margin:4px 0 6px 18px;padding:0;font-size:13px}
#prev .w{color:#b45309}
.pin{border-radius:50%;color:#fff;font-weight:700;width:26px;height:26px;line-height:26px;text-align:center;font-size:13px;border:2px solid #fff;box-shadow:0 0 3px #0006}
#note{position:absolute;bottom:0;left:400px;max-width:calc(100vw - 760px);z-index:1000;background:#fffc;font-size:11px;padding:2px 6px}
#chat{width:340px;max-width:40vw;display:flex;flex-direction:column;border-left:1px solid #ddd;background:#fff}
#chat.hide{display:none}
#chead{padding:8px 12px;border-bottom:1px solid #ddd;display:flex;gap:8px;align-items:center}#chead b{flex:1}#cstat{font-size:12px;color:#b45309}#chead button{border:0;font-size:18px;padding:0 4px}
#cmsgs{flex:1;overflow:auto;padding:8px 10px;font-size:13px}
.m{margin:6px 0;padding:6px 9px;border-radius:8px;white-space:pre-wrap;word-break:break-word;line-height:1.5}
.m.u{background:#dbeafe;margin-left:30px}.m.a{background:#f3f4f6;margin-right:20px}.m.e{background:#fee2e2;color:#991b1b}
#chips{padding:4px 8px;display:flex;gap:4px;flex-wrap:wrap}#chips button{font-size:12px;padding:2px 8px;border-radius:12px}
#cin{display:flex;gap:6px;padding:8px;border-top:1px solid #ddd}#cin textarea{flex:1;resize:none;font:inherit;font-size:13px;padding:4px 6px}
@media (max-width:760px){#chat{position:fixed;left:0;right:0;bottom:0;width:auto;max-width:none;height:55%;z-index:2000;border-top:2px solid #2563eb}}
@media (max-width:760px){#note{left:0;max-width:100vw;bottom:auto;top:0}#app{flex-direction:column}#side{width:auto;max-width:none;height:60%}#map{height:40%}}
</style></head><body>
<div id="app"><div id="side">
<header><b id="title"></b><span id="rev" style="font-size:12px;color:#777"></span><button id="ctoggle">💬 助手</button><button id="refine" title="给还没查过的路段查真实路线">更新路线</button><button id="undo">撤销</button></header>
<div id="msg"></div>
<div id="scroll">
<div class="sec"><h3>日期 <span id="dstate" style="font-weight:400;font-size:12px;color:#666"></span></h3>
<div id="cal"></div><div id="calinfo"></div>
<button id="dapply" class="pri" disabled>应用日期</button> <button id="dclear">清除日期</button></div>
<div class="sec" id="days"></div>
</div>
<div id="prev"><b>预览（还没有改动）</b><ul id="chg"></ul><div id="iss"></div><button id="ok" class="pri">确认</button> <button id="cancel">取消</button></div>
</div><div id="map" style="position:relative"></div>
<div id="chat"><div id="chead"><b>助手</b><span id="cstat"></span><button id="cclose" title="收起">×</button></div>
<div id="cmsgs"></div>
<div id="chips"><button data-t="我想把【景点名】加进行程，查一下位置给我确认。">加景点</button><button data-t="帮我在【区域】附近找几家酒店，给我对比。">找酒店</button><button data-t="帮我查【日期】从【出发地】到【目的地】的火车票/机票。">查车票机票</button><button data-t="查一下行程这几天的天气。">查天气</button></div>
<div id="cin"><textarea id="ctext" rows="2" placeholder="对助手说点什么…（Enter 发送，Shift+Enter 换行）"></textarea><button id="csend" class="pri">发送</button></div></div></div>
<div id="note"></div>
<script>__JS__</script>
<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = id => document.getElementById(id);
let S = null, selDay = 0, pending = null, drag = null, picks = [], calMonth = null;
const map = L.map('map'); let layer = L.layerGroup().addTo(map), tileLayer = null;

function say(t, err) { const m = $('msg'); m.textContent = t || ''; m.className = err ? 'err' : ''; }
async function api(path, body) {
  const r = await fetch('api/' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: '服务没有响应'}));
  if (!r.ok) { const e = new Error(j.error || ('出错了 ' + r.status)); e.status = r.status; throw e; }
  return j;
}
async function load() {
  try { S = await api('state'); } catch (e) { say(e.message, true); return; }
  $('title').textContent = S.title; $('rev').textContent = '版本 ' + S.revision; $('undo').disabled = !S.can_undo;
  if (!tileLayer && S.map.tiles) { tileLayer = L.tileLayer(S.map.tiles.url, {subdomains: S.map.tiles.sub, maxZoom: 18, minZoom: 3, attribution: S.map.tiles.attr}).addTo(map); $('note').textContent = S.map.tiles.note; }
  if (selDay >= S.days.length) selDay = 0;
  renderDates(); renderDays(); renderMap();
}
// ---- 日期 ----
const iso = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
const parse = s => { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); };
function renderDates() {
  const cur = S.dates;
  $('dstate').textContent = cur.start ? cur.start + ' 至 ' + cur.end : '还没有设置日期';
  if (!picks.length && cur.start) picks = [cur.start, cur.end];
  const base = calMonth || parse(cur.start || iso(new Date())); calMonth = new Date(base.getFullYear(), base.getMonth(), 1);
  const y = calMonth.getFullYear(), m = calMonth.getMonth(), first = (new Date(y, m, 1).getDay() + 6) % 7, n = new Date(y, m+1, 0).getDate();
  const today = new Date(); today.setHours(0,0,0,0); const fcEnd = new Date(today); fcEnd.setDate(fcEnd.getDate() + 15);
  let h = '<div class="nav"><button id="pm">‹</button><b>' + y + ' 年 ' + (m+1) + ' 月</b><button id="nm">›</button></div><table><tr>' + '一二三四五六日'.split('').map(x => '<th>' + x + '</th>').join('') + '</tr><tr>';
  for (let i = 0; i < first; i++) h += '<td></td>';
  for (let d = 1; d <= n; d++) {
    const dt = new Date(y, m, d), k = iso(dt); if ((first + d - 1) % 7 === 0 && d > 1) h += '</tr><tr>';
    const a = picks[0], b = picks[1] || picks[0]; const cls = [];
    if (dt >= today && dt <= fcEnd) cls.push('fc');
    if (a && k >= a && k <= b) cls.push('in'); if (k === a || k === b) cls.push('edge');
    h += '<td class="' + cls.join(' ') + '"><button data-d="' + k + '">' + d + '</button></td>';
  }
  $('cal').innerHTML = h + '</tr></table>';
  $('pm').onclick = () => { calMonth = new Date(y, m-1, 1); renderDates(); }; $('nm').onclick = () => { calMonth = new Date(y, m+1, 1); renderDates(); };
  $('cal').querySelectorAll('td button').forEach(b => b.onclick = () => {
    const k = b.dataset.d; if (picks.length !== 1) picks = [k]; else picks = k < picks[0] ? [k, picks[0]] : [picks[0], k]; renderDates(); });
  const full = picks.length === 2, days = full ? Math.round((parse(picks[1]) - parse(picks[0])) / 864e5) + 1 : 0;
  $('calinfo').textContent = !picks.length ? '先点出发日，再点结束日。绿色底是天气预报能覆盖的范围（约未来 16 天）。' : (full ? '已选 ' + picks[0] + ' 至 ' + picks[1] + '，共 ' + days + ' 天' + (days > 30 ? '（最多 30 天）' : '') : '已选出发日 ' + picks[0] + '，再点结束日');
  if (full && S.days.length && days !== S.dates.num_days) $('calinfo').textContent += '。应用后天数会从 ' + S.dates.num_days + ' 天变成 ' + days + ' 天，并自动重新分天（已锁定且仍在范围内的景点保持原位）。';
  $('dapply').disabled = !full || days > 30 || (cur.start === picks[0] && cur.end === picks[1]);
}
$('dapply').onclick = async () => { try { const r = await api('dates', {base_revision: S.revision, start: picks[0], end: picks[1]}); say(r.message); await load(); } catch (e) { say(e.message, true); if (e.status === 409) load(); } };
$('dclear').onclick = async () => { if (!S.dates.start) return; try { const r = await api('dates', {base_revision: S.revision, start: null, end: null}); picks = []; say(r.message); await load(); } catch (e) { say(e.message, true); } };
// ---- 每天的卡片 ----
const link = (u, t) => u ? ' <a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + t + '</a>' : '';
function renderDays() {
  const root = $('days'); root.innerHTML = '';
  if (!S.days.length) { root.innerHTML = '<div class="empty">还没有分天。先对 agent 说“安排行程”（schedule_days）。</div>'; }
  S.days.forEach(d => {
    const z = document.createElement('div'); z.className = 'day'; z.dataset.day = d.index;
    z.innerHTML = '<div class="dh"><span class="dot" style="background:' + d.color + '"></span>' + esc(d.label) + '</div>';
    z.querySelector('.dh').onclick = () => { selDay = d.index; renderMap(); };
    const stops = d.rows.filter(r => r.t === 'stop'); let si = 0;
    d.rows.forEach(r => {
      if (r.t === 'stop') {
        const i = si++, c = document.createElement('div'); c.className = 'card'; c.draggable = true; c.dataset.pid = r.place_id;
        const hours = (r.lines || []).find(x => x.indexOf('营业时间') === 0);
        c.innerHTML = '<span class="n" style="background:' + d.color + '">' + r.n + '</span><span class="nm">' + esc(r.name) + (r.locked ? ' 🔒' : '') + (hours ? '<small>' + esc(hours) + '</small>' : '') + '</span><span class="tm">' + esc(r.time) + '</span><span class="mv"><button data-a="up" title="上移">▲</button><button data-a="dn" title="下移">▼</button></span>';
        c.querySelector('[data-a=up]').onclick = () => move(r.place_id, d.index, Math.max(i-1, 0));
        c.querySelector('[data-a=dn]').onclick = () => move(r.place_id, d.index, Math.min(i+1, stops.length-1));
        c.ondragstart = e => { drag = r.place_id; c.classList.add('drag'); e.dataTransfer.setData('text/plain', r.place_id); e.dataTransfer.effectAllowed = 'move'; };
        c.ondragend = () => { drag = null; document.querySelectorAll('.drag,.over').forEach(x => x.classList.remove('drag', 'over')); document.querySelectorAll('.ins').forEach(x => x.remove()); };
        z.appendChild(c);
      } else {
        const e = document.createElement('div');
        if (r.t === 'leg') { e.className = 'leg'; e.innerHTML = '↓ ' + r.minutes + ' 分钟 · ' + esc(r.mode) + ' · ' + r.km + ' km · <span class="' + (r.real ? 'real' : 'est') + '">' + (r.real ? '真实路线' : '估算') + '</span>' + link(r.link, '导航') + (r.note ? '<div class="sub">' + esc(r.note) + '</div>' : ''); }
        else if (r.t === 'meal') { e.className = 'meal'; e.innerHTML = '🍜 <b>' + esc(r.name) + '</b>' + link(r.link, '地图') + '<div class="sub">' + (r.lines || []).map(esc).join(' · ') + '</div>'; }
        else if (r.t === 'hotel') { e.className = 'info'; e.textContent = '🏨 ' + r.role + ' ' + r.time + ' ' + r.name; }
        else { e.className = 'info'; e.textContent = r.text; }
        z.appendChild(e);
      }
    });
    if (!stops.length) z.insertAdjacentHTML('beforeend', '<div class="empty">把景点拖到这里</div>');
    wire(z, () => ({kind: 'day', day: d.index})); root.appendChild(z);
  });
  const u = document.createElement('div'); u.className = 'day'; u.innerHTML = '<div class="dh">未安排（拖到这里表示移出行程）</div>';
  S.unscheduled.forEach(it => { const c = document.createElement('div'); c.className = 'card'; c.draggable = true; c.dataset.pid = it.place_id;
    c.innerHTML = '<span class="nm">' + esc(it.name) + '</span><span class="tm">' + esc(it.reason || '') + '</span>';
    c.ondragstart = e => { drag = it.place_id; c.classList.add('drag'); e.dataTransfer.setData('text/plain', it.place_id); }; c.ondragend = () => { drag = null; }; u.appendChild(c); });
  (S.orphan_meals || []).forEach(m => u.insertAdjacentHTML('beforeend', '<div class="meal">🍜 <b>' + esc(m.name) + '</b><div class="sub">原来挂在「' + esc(m.after) + '」之后，该景点现在不在行程里（用餐点没有删除）</div></div>'));
  wire(u, () => ({kind: 'none'})); root.appendChild(u);
}
function wire(zone, info) {
  zone.ondragover = e => { if (!drag) return; e.preventDefault(); zone.classList.add('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    const cards = [...zone.querySelectorAll('.card')].filter(c => c.dataset.pid !== drag); let idx = cards.findIndex(c => e.clientY < c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2); if (idx < 0) idx = cards.length;
    zone.dataset.idx = idx; const bar = document.createElement('div'); bar.className = 'ins'; if (cards[idx]) zone.insertBefore(bar, cards[idx]); else zone.appendChild(bar); };
  zone.ondragleave = e => { if (!zone.contains(e.relatedTarget)) { zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove()); } };
  zone.ondrop = e => { e.preventDefault(); const pid = drag || e.dataTransfer.getData('text/plain'); const t = info(); zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    if (t.kind === 'day') move(pid, t.day, Number(zone.dataset.idx || 0)); else if (t.kind === 'none') propose([{kind: 'remove', place_id: pid}]); };
}
function findItem(pid) { for (const d of S.days) for (const it of d.items) if (it.place_id === pid) return it; return null; }
function move(pid, day, pos) {
  const ops = []; const it = findItem(pid); if (it && it.locked) ops.push({kind: 'lock', place_id: pid, locked: false});
  ops.push({kind: 'move', place_id: pid, to_day: day, to_position: pos}); propose(ops);
}
async function propose(ops) {
  try { pending = await api('preview', {base_revision: S.revision, ops}); } catch (e) { say(e.message, true); if (e.status === 409) load(); return; }
  $('chg').innerHTML = pending.changes.map(x => '<li>' + esc(x) + '</li>').join('');
  $('iss').innerHTML = pending.new_issues.length ? '<div class="w">改完后新增的问题：</div><ul>' + pending.new_issues.map(i => '<li class="w">' + esc(i) + '</li>').join('') + '</ul>' : '<div style="font-size:13px;color:#15803d">没有新增问题。</div>';
  $('prev').style.display = 'block'; say('');
}
$('ok').onclick = async () => {
  if (!pending) return; const days = pending.affected_days || [];
  try { await api('apply', {base_revision: S.revision, proposal_id: pending.proposal_id}); say('已套用。'); } catch (e) { say(e.message, true); closePrev(); load(); return; }
  closePrev(); await load();
  for (const dn of days) await refineRoutes(dn);
};
async function refineRoutes(day) {
  say(day ? '正在查询第' + day + '天的真实路线…' : '正在查询真实路线…');
  try { const r = await api('refine', {base_revision: S.revision, day: day || null}); say(r.ok ? r.message : r.message + '（路线仍是估算）', false); } catch (e) { say(e.message, true); }
  await load();
}
$('refine').onclick = () => refineRoutes(null);
$('cancel').onclick = closePrev; function closePrev() { pending = null; $('prev').style.display = 'none'; }
$('undo').onclick = async () => { try { await api('undo', {base_revision: S.revision}); say('已撤销。'); } catch (e) { say(e.message, true); } closePrev(); load(); };
// ---- 地图 ----
function renderMap() {
  layer.clearLayers(); const d = S.map.days.find(x => x.index === selDay); if (!d) { map.setView([35, 105], 4); return; }
  const pts = [];
  d.timeline.forEach(e => {
    if (e.type === 'leg') { const p = e.real && e.path.length ? e.path : [e.a, e.b]; L.polyline(p, {color: d.color, weight: 4, opacity: .8, dashArray: e.real ? null : '6 6'}).addTo(layer); pts.push(...p); }
    else if (e.type === 'stop') { L.marker(e.show || e.pos, {icon: L.divIcon({className: '', html: '<div class="pin" style="background:' + d.color + '">' + e.n + '</div>', iconSize: [26, 26], iconAnchor: [13, 13]})}).bindPopup('<b>' + esc(e.name) + '</b><br>' + esc(e.arrive) + '–' + esc(e.leave)).addTo(layer); pts.push(e.pos); }
    else if (e.type === 'hotel') { L.marker(e.pos, {icon: L.divIcon({className: '', html: '<div style="font-size:20px">🏨</div>', iconSize: [26, 26], iconAnchor: [13, 13]})}).bindPopup(esc(e.name)).addTo(layer); pts.push(e.pos); }
  });
  if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.2));
}
// ---- 聊天 + 自动刷新 ----
const msgs = $('cmsgs'); let busy = false;
function bubble(cls, text) { const d = document.createElement('div'); d.className = 'm ' + cls; d.textContent = text; msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight; return d; }
async function chatStatus() { try { const r = await api('chat_status'); $('cstat').textContent = r.connected ? '' : '未连接'; if (!r.connected && !msgs.children.length) bubble('e', r.message); return r.connected; } catch (e) { $('cstat').textContent = '未连接'; return false; } }
async function send() {
  const text = $('ctext').value.trim(); if (!text || busy) return;
  busy = true; $('csend').disabled = true; $('ctext').value = ''; bubble('u', text); const out = bubble('a', '…'); let got = '', done = false;
  try {
    const r = await fetch('api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text})});
    if (!r.ok) { const j = await r.json().catch(() => ({})); out.className = 'm e'; out.textContent = j.error || ('出错了 ' + r.status); }
    else {
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) { const {value, done: end} = await rd.read(); if (end) break; buf += dec.decode(value, {stream: true}); let i;
        while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          if (!line.startsWith('data:')) continue; const d = line.slice(5).trim(); if (d === '[DONE]') { done = true; continue; }
          try { const t = (JSON.parse(d).choices || [{}])[0].delta; if (t && t.content) { got += t.content; out.textContent = got; msgs.scrollTop = msgs.scrollHeight; } } catch (e) {} } }
      if (!got) out.textContent = '（没有收到回复）';
      if (!done) { const w = document.createElement('div'); w.className = 'm e'; w.textContent = '回复可能不完整（连接中断或超时）。agent 已经做完的操作不会撤销，请看看行程再决定。'; msgs.appendChild(w); }
    }
  } catch (e) { out.className = 'm e'; out.textContent = '请求失败：' + e.message; }
  busy = false; $('csend').disabled = false; await load();
}
$('csend').onclick = send; $('ctext').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
document.querySelectorAll('#chips button').forEach(b => b.onclick = () => { $('ctext').value = b.dataset.t; $('ctext').focus(); });
$('ctoggle').onclick = () => $('chat').classList.toggle('hide'); $('cclose').onclick = () => $('chat').classList.add('hide');
setInterval(async () => {
  if (document.hidden || !S || drag) return;
  try { const r = await api('rev'); if (r.revision !== S.revision) { if (pending) { closePrev(); say('行程在别处被修改了，刚才的预览已取消。'); } await load(); } } catch (e) {}
}, 2000);
chatStatus();
load();
</script></body></html>
"""


def page_html() -> str:
    return (TEMPLATE
            .replace("__CSS__", (_ASSETS / "leaflet.css").read_text(encoding="utf-8"))
            .replace("__JS__", (_ASSETS / "leaflet.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
