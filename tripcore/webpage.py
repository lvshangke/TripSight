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
#side{width:var(--sw,400px);flex:none;display:flex;flex-direction:column;border-right:1px solid #ddd;background:#fafafa}
#scroll{flex:1;overflow:auto}
#map{flex:1;min-width:0;height:100%}
.sp{flex:none;width:6px;margin:0 -3px;z-index:1500;cursor:col-resize;background:transparent;touch-action:none}
.sp:hover,.sp.on{background:#2563eb55}
body.resizing{cursor:col-resize;user-select:none}
body.resizing #map{pointer-events:none}
header{padding:10px 12px;border-bottom:1px solid #ddd;display:flex;align-items:center;gap:8px;background:#fff}
header b{flex:1;font-size:16px}
#trip{flex:1;min-width:0;font:inherit;font-size:15px;font-weight:700;padding:3px 4px;border:1px solid #bbb;border-radius:6px;background:#fff;color:#222}
button{border:1px solid #bbb;border-radius:6px;background:#fff;padding:4px 10px;cursor:pointer;color:#222}
button:disabled{opacity:.4;cursor:default}
button.pri{background:#2563eb;border-color:#2563eb;color:#fff}
#msg{padding:4px 12px;font-size:13px;color:#555;min-height:6px}
#msg.err{color:#b91c1c}
#nt{position:fixed;inset:0;background:#0006;z-index:3000;display:none;align-items:center;justify-content:center}
#nt.on{display:flex}
#nt form{background:#fff;border-radius:10px;padding:16px 18px;width:min(380px,92vw);box-shadow:0 8px 30px #0005;font-size:14px}
#nt h3{margin:0 0 10px;font-size:16px}
#nt label{display:block;margin:8px 0 2px;color:#444;font-size:13px}
#nt input,#nt select{width:100%;box-sizing:border-box;font:inherit;padding:5px 6px;border:1px solid #bbb;border-radius:6px;background:#fff;color:#222}
#nt .row{display:flex;gap:8px}#nt .row>div{flex:1}
#nt .btns{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
#nt .err{color:#b91c1c;font-size:13px;min-height:16px;margin-top:6px}
#ap{position:fixed;inset:0;background:#0006;z-index:3000;display:none;align-items:center;justify-content:center}
#ap.on{display:flex}
#ap .box{background:#fff;border-radius:10px;padding:16px 18px;width:min(440px,94vw);max-height:88vh;overflow:auto;box-shadow:0 8px 30px #0005;font-size:14px}
#ap h3{margin:0 0 10px;font-size:16px}
#ap .q{display:flex;gap:6px}#ap .q input{flex:1;font:inherit;padding:5px 6px;border:1px solid #bbb;border-radius:6px}
.cand{display:block;border:1px solid #ddd;border-radius:8px;padding:7px 9px;margin:6px 0;cursor:pointer}
.cand:has(input:checked){border-color:#2563eb;background:#eff6ff}
.cand input{margin-right:6px}.cand .a{font-size:12px;color:#555;margin-left:22px}
#ap .w{color:#b45309;font-size:12px;margin:6px 0}
#ap .err{color:#b91c1c;font-size:13px;min-height:16px;margin-top:6px}
#ap .btns{display:flex;justify-content:flex-end;gap:8px;margin-top:12px;align-items:center}
.dur{width:54px;font:inherit;font-size:12px;padding:1px 3px;border:1px solid #bbb;border-radius:4px}
.editonly{display:none}
#app.edit .editonly{display:block}
#app.edit #tabs{display:none}
#tabs{position:sticky;top:0;background:#fff;padding:8px;border-bottom:1px solid #ddd;display:flex;flex-wrap:wrap;gap:6px;z-index:5}
#tabs button.on{color:#fff;border-color:transparent}
.sec{border-bottom:1px solid #eee;padding:8px 12px;background:#fff}
#datedet summary{cursor:pointer;font-weight:700;font-size:14px;padding:2px 0}
#datedet[open] summary{margin-bottom:6px}
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
.day{border:1px dashed transparent;border-radius:6px;margin:6px 0 10px;padding:0}
.day.over{border-color:#2563eb;background:#eff6ff}
.dh{font-weight:700;font-size:14px;padding:8px 12px;cursor:pointer;display:flex;gap:6px;align-items:center;background:#fff;border-bottom:1px solid #eee}
.dh .dot{width:10px;height:10px;border-radius:50%}
.dh.cur{background:#eef3ff}
.it{padding:8px 12px;border-bottom:1px solid #eee;cursor:pointer;background:#fafafa}
.it:hover{background:#f0f4ff}
.it .h{display:flex;gap:8px;align-items:baseline}
.it .tm{font-variant-numeric:tabular-nums;color:#666;min-width:42px;font-size:13px}
.it .nm{font-weight:600;flex:1}
.it .sub{margin:2px 0 0 50px;font-size:12px;color:#555;line-height:1.5}
.it.drag{opacity:.4}
.it .mv button{padding:0 5px;font-size:11px}
.leg{padding:4px 12px 4px 62px;font-size:12px;color:#444;border-bottom:1px dashed #e4e4e4;cursor:pointer;background:#fff}
.leg:hover{background:#f0f4ff}
.leg a{color:#1a6fe8;text-decoration:none;margin-left:6px}
.est{color:#b26a00}
.ins{height:3px;background:#2563eb;border-radius:2px}
.empty{font-size:12px;color:#999;padding:8px 12px}
.pin{border-radius:50%;color:#fff;font-weight:700;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px #0006;width:26px;height:26px;line-height:22px;font-size:13px}
.emo{font-size:22px;line-height:24px;text-align:center;filter:drop-shadow(0 1px 2px #0008)}
#prev{font-size:13px;border-top:2px solid #2563eb;padding:6px 12px;background:#f8fbff;display:none;max-height:28%;overflow:auto}
#prev ul{margin:4px 0 6px 18px;padding:0}
#prev .w{color:#b45309}
#note{position:absolute;bottom:0;left:calc(var(--sw,400px) + 6px);max-width:calc(100vw - var(--sw,400px) - var(--cw,340px) - 24px);z-index:1000;background:#fffc;font-size:11px;padding:2px 6px}
#chat{width:var(--cw,340px);flex:none;display:flex;flex-direction:column;border-left:1px solid #ddd;background:#fff}
#chat.hide{display:none}
#chead{padding:8px 12px;border-bottom:1px solid #ddd;display:flex;gap:8px;align-items:center}#chead b{flex:1}#cstat{font-size:12px;color:#b45309;white-space:nowrap}#cstat.ok{color:#15803d}#chead button{border:0;font-size:18px;padding:0 4px}
#cmsgs{flex:1;overflow:auto;padding:8px 10px;font-size:13px}
.m{margin:6px 0;padding:6px 9px;border-radius:8px;white-space:pre-wrap;word-break:break-word;line-height:1.5}
.m.u{background:#dbeafe;margin-left:30px}.m.a{background:#f3f4f6;margin-right:20px}.m.e{background:#fee2e2;color:#991b1b}
#chips{padding:4px 8px;display:flex;gap:4px;flex-wrap:wrap}#chips button{font-size:12px;padding:2px 8px;border-radius:12px}
#cin{display:flex;gap:6px;padding:8px;border-top:1px solid #ddd}#cin textarea{flex:1;resize:none;font:inherit;font-size:13px;padding:4px 6px}
@media (max-width:760px){.sp{display:none}#side{width:auto}#note{left:0;max-width:100vw;bottom:auto;top:0}#app{flex-direction:column-reverse}#side{height:50%;border-right:0;border-top:1px solid #ddd}#map{height:50%;flex:none}#chat{position:fixed;left:0;right:0;bottom:0;width:auto;max-width:none;height:55%;z-index:2000;border-top:2px solid #2563eb}}
</style></head><body>
<div id="app"><div id="side">
<header><select id="trip" title="切换行程"></select><span id="rev" style="font-size:12px;color:#777"></span><button id="ctoggle">💬 助手</button><button id="edit">编辑</button></header>
<div id="msg"></div>
<div class="editonly sec"><button id="undo">撤销</button> <button id="refine" title="给还没查过的路段查真实路线">更新路线</button></div>
<div id="tabs"></div>
<div id="scroll"><details class="editonly sec" id="datedet"><summary>日期：<span id="dstate"></span></summary>
<div id="cal"></div><div id="calinfo"></div>
<button id="dapply" class="pri" disabled>应用日期</button> <button id="dclear">清除日期</button></details><div id="list"></div></div>
<div id="prev"><b>预览（还没有改动）</b><ul id="chg"></ul><div id="iss"></div><button id="ok" class="pri">确认</button> <button id="cancel">取消</button></div>
</div><div class="sp" id="sp1" title="拖动调整宽度，双击恢复"></div><div id="map" style="position:relative"></div><div class="sp" id="sp2" title="拖动调整宽度，双击恢复"></div>
<div id="chat"><div id="chead"><b>助手</b><span id="cstat"></span><button id="cclose" title="收起">×</button></div>
<div id="cmsgs"></div>
<div id="chips"><button data-t="我想把【景点名】加进行程，查一下位置给我确认；我确认后请直接排进某一天并更新路线。">加景点</button><button data-t="帮我在【区域】附近找几家酒店，给我对比；我选定后请直接设为住宿并更新路线。">找酒店</button><button data-t="帮我查【日期】从【出发地】到【目的地】的火车票/机票。">查车票机票</button><button data-t="查一下行程这几天的天气。">查天气</button></div>
<div id="cin"><textarea id="ctext" rows="2" placeholder="对助手说点什么…（Enter 发送，Shift+Enter 换行）"></textarea><button id="csend" class="pri">发送</button></div></div></div>
<div id="note"></div>
<div id="ap"><div class="box"><h3>加景点</h3>
<div class="q"><input id="ap_q" maxlength="60" placeholder="景点名称，例如：大雁塔"><button id="ap_go" class="pri">查找</button></div>
<div id="ap_list"></div><div class="w" id="ap_warn"></div>
<div class="btns"><span style="flex:1;font-size:13px;color:#555">停留 <input id="ap_dur" class="dur" type="number" min="10" max="720" step="15" value="90"> 分钟</span>
<button id="ap_cancel">取消</button><button id="ap_ok" class="pri" disabled>加入行程</button></div><div class="err" id="ap_err"></div></div></div>
<div id="nt"><form id="ntf" autocomplete="off"><h3>新建行程</h3>
<label>行程名称（必填）</label><input id="nt_name" maxlength="40" placeholder="例如：东京5日">
<label>目的地城市（选填，之后查坐标会限定在这个城市附近）</label><input id="nt_city" maxlength="40" placeholder="例如：东京">
<div class="row"><div><label>天数（1–30）</label><input id="nt_days" type="number" min="1" max="30" value="3"></div><div><label>出行人数</label><input id="nt_tv" type="number" min="1" max="50" value="1"></div></div>
<div class="row"><div><label>出发日（选填）</label><input id="nt_sd" type="date"></div><div><label>结束日（选填）</label><input id="nt_ed" type="date"></div></div>
<label>节奏</label><select id="nt_pace"><option value="">沿用我的长期偏好</option><option value="relaxed">悠闲</option><option value="normal">正常</option><option value="packed">紧凑</option></select>
<div class="err" id="nt_err"></div>
<div class="btns"><button type="button" id="nt_cancel">取消</button><button type="submit" class="pri" id="nt_ok">创建</button></div></form></div>
<script>__JS__</script>
<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = id => document.getElementById(id);
let S = null, selDay = 0, edit = false, pending = null, drag = null, picks = [], calMonth = null;
const map = L.map('map'); let layer = null, tileLayer = null, tileUrl = null;
const pin = (txt, color) => L.divIcon({className:'', html:'<div class="pin" style="background:'+color+'">'+esc(txt)+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const emo = e => L.divIcon({className:'', html:'<div class="emo">'+e+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const popup = (name, lines) => '<b>'+esc(name)+'</b>'+(lines.length?'<br>':'')+lines.map(esc).join('<br>');

function say(t, err) { const m = $('msg'); m.textContent = t || ''; m.className = err ? 'err' : ''; }
async function api(path, body) {
  const r = await fetch('api/' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: '服务没有响应'}));
  if (!r.ok) { const e = new Error(j.error || ('出错了 ' + r.status)); e.status = r.status; throw e; }
  return j;
}
async function load() {
  try { S = await api('state'); } catch (e) { say(e.message, true); return; }
  $('rev').textContent = '版本 ' + S.revision; $('undo').disabled = !S.can_undo;
  if (S.map.tiles && (!tileLayer || tileUrl !== S.map.tiles.url)) { if (tileLayer) map.removeLayer(tileLayer); tileUrl = S.map.tiles.url; tileLayer = L.tileLayer(tileUrl, {subdomains: S.map.tiles.sub, maxZoom: 18, minZoom: 3, attribution: S.map.tiles.attr}).addTo(map); $('note').textContent = S.map.tiles.note; }
  await loadTrips();
  if (selDay >= S.map.days.length) selDay = 0;
  renderAll();
}
async function loadTrips() {
  try {
    const r = await api('trips'), sel = $('trip'); sel.innerHTML = '';
    r.trips.forEach(t => { const o = document.createElement('option'); o.value = t.slug; o.textContent = t.name + (t.num_days ? '（' + t.num_days + '天）' : ''); o.selected = t.slug === r.current || r.single; sel.appendChild(o); });
    if (!r.single) { const o = document.createElement('option'); o.value = '__new__'; o.textContent = '＋ 新建行程…'; sel.appendChild(o); }
    sel.disabled = r.single; sel.title = r.single ? '单文件模式不能切换或新建' : '切换行程 / 新建行程'; curTrip = r.current;
  } catch (e) {}
}
let curTrip = null, apPicked = null;
function apOpen() { $('ap_q').value = ''; $('ap_list').innerHTML = ''; $('ap_warn').textContent = ''; $('ap_err').textContent = ''; $('ap_dur').value = 90; apPicked = null; $('ap_ok').disabled = true; $('ap').classList.add('on'); $('ap_q').focus(); }
function apClose() { $('ap').classList.remove('on'); }
$('ap_cancel').onclick = apClose; $('ap').onclick = e => { if (e.target === $('ap')) apClose(); };
async function apSearch() {
  const q = $('ap_q').value.trim(); if (!q) return; $('ap_err').textContent = ''; $('ap_go').disabled = true; $('ap_list').innerHTML = '<div class="empty">查询中…</div>'; apPicked = null; $('ap_ok').disabled = true;
  try {
    const r = await api('lookup', {query: q}); $('ap_warn').textContent = r.warning || '';
    if (!r.candidates.length) { $('ap_list').innerHTML = '<div class="empty">' + esc(r.message || '没有找到') + '</div>'; }
    else { $('ap_list').innerHTML = r.candidates.map((c, i) => '<label class="cand"><input type="radio" name="apc" value="' + esc(c.cid) + '"><b>' + esc(c.name) + '</b>' + (c.rating ? ' ⭐' + esc(c.rating) : '') + '<div class="a">' + esc(c.address) + (c.category ? ' · ' + esc(c.category) : '') + (c.opentime_today ? '<br>今日营业：' + esc(c.opentime_today) : '') + '</div></label>').join('');
      $('ap_list').querySelectorAll('input').forEach(i => i.onchange = () => { apPicked = i.value; $('ap_ok').disabled = false; }); }
  } catch (e) { $('ap_list').innerHTML = ''; $('ap_err').textContent = e.message; }
  $('ap_go').disabled = false;
}
$('ap_go').onclick = apSearch; $('ap_q').onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); apSearch(); } };
$('ap_ok').onclick = async () => {
  if (!apPicked) return; $('ap_ok').disabled = true;
  try {
    const r = await api('add_place', {base_revision: S.revision, cid: apPicked, duration_min: Number($('ap_dur').value)});
    apClose(); say(r.message); await load(); }
  catch (e) { $('ap_err').textContent = e.message; $('ap_ok').disabled = false; if (e.status === 409) { apClose(); load(); } }
};
function ntOpen() { $('nt_err').textContent = ''; $('nt').classList.add('on'); $('nt_name').focus(); }
function ntClose() { $('nt').classList.remove('on'); }
$('nt_cancel').onclick = ntClose; $('nt').onclick = e => { if (e.target === $('nt')) ntClose(); };
$('nt_sd').onchange = () => { const a = $('nt_sd').value, b = $('nt_ed').value; if (a && (!b || b < a)) $('nt_ed').value = a; if (a && $('nt_ed').value) $('nt_days').value = Math.round((parse($('nt_ed').value) - parse(a)) / 864e5) + 1; };
$('nt_ed').onchange = () => { const a = $('nt_sd').value, b = $('nt_ed').value; if (a && b) $('nt_days').value = Math.round((parse(b) - parse(a)) / 864e5) + 1; };
$('ntf').onsubmit = async e => {
  e.preventDefault(); const sd = $('nt_sd').value, ed = $('nt_ed').value;
  const body = {name: $('nt_name').value, city: $('nt_city').value, num_days: Number($('nt_days').value), travelers: Number($('nt_tv').value), start: sd || null, end: ed || null, pace: $('nt_pace').value || null};
  $('nt_ok').disabled = true;
  try { const r = await api('new_trip', body); ntClose(); closePrev(); picks = []; calMonth = null; selDay = 0; $('ntf').reset(); say(r.message + ' 现在可以在右侧助手里说想去哪、想看什么。'); await load(); if ($('chat').classList.contains('hide')) $('chat').classList.remove('hide'), syncSp2(), fit(); $('ctext').focus(); }
  catch (er) { $('nt_err').textContent = er.message; }
  $('nt_ok').disabled = false;
};
$('trip').onchange = async () => {
  const sel = $('trip'), want = sel.value;
  if (want === '__new__') { await loadTrips(); ntOpen(); return; }
  if (pending && !confirm('有一个还没确认的修改预览，切换行程会放弃它。继续吗？')) { await loadTrips(); return; }
  try { const r = await api('switch', {slug: want}); closePrev(); picks = []; calMonth = null; selDay = 0; say('已切换到「' + r.title + '」。助手之后也针对这个行程。'); await load(); }
  catch (e) { say(e.message, true); await loadTrips(); }
};
function renderAll() { renderDates(); renderTabs(); renderList(); }
$('edit').onclick = () => { edit = !edit; $('app').classList.toggle('edit', edit); $('edit').textContent = edit ? '完成编辑' : '编辑'; $('edit').className = edit ? 'pri' : ''; closePrev(); if (S) renderAll(); };
// ---- 日期 ----
const iso = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
const parse = s => { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); };
function renderDates() {
  if (!edit) return;
  const cur = S.dates;
  $('dstate').textContent = cur.start ? cur.start + ' 至 ' + cur.end + '（共 ' + cur.num_days + ' 天）' : '还没有设置（点开选择）';
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
// ---- 标签页（查看模式）----
function renderTabs() {
  const tabs = $('tabs'); tabs.innerHTML = '';
  S.map.days.forEach((d, i) => { const b = document.createElement('button'); b.textContent = d.label; b.className = i === selDay ? 'on' : ''; b.style.background = i === selDay ? d.color : '#fff'; b.onclick = () => { selDay = i; renderAll(); }; tabs.appendChild(b); });
}
// ---- 地图：画某一天，返回每个条目对应的标记/线 ----
function drawMap(di) {
  if (layer) map.removeLayer(layer); layer = L.featureGroup().addTo(map); const ctx = {m: {}, l: {}};
  const d = S.map.days[di]; if (!d) { map.setView([35, 105], 4); return ctx; }
  d.timeline.forEach((e, idx) => {
    if (e.type === 'leg') {
      const pts = e.path.length ? e.path : [e.a, e.b];
      const pl = L.polyline(pts, {color: d.color, weight: e.real ? 5 : 3, opacity: .85, dashArray: e.real ? null : '6 8'}).addTo(layer);
      pl.bindTooltip(esc(e.mode) + ' 约' + e.minutes + '分钟' + (e.real ? '' : '（估算）'), {sticky: true}); ctx.l[idx] = pl;
    } else if (e.type !== 'conn' && !(e.type === 'hotel' && e.role === '返回')) {
      let icon, title;
      if (e.type === 'hotel') { icon = emo('🏨'); title = e.name; }
      else if (e.type === 'term') { icon = emo(e.icon); title = e.role + '：' + e.name; }
      else if (e.type === 'meal') { icon = emo('🍜'); title = '用餐：' + e.name; }
      else { icon = pin(e.n, d.color); title = e.n + '. ' + e.name; }
      ctx.m[idx] = L.marker(e.show || e.pos, {icon}).bindPopup(popup(d.label + ' · ' + title, e.type === 'hotel' ? [] : (e.lines || []))).addTo(layer);
      if (e.route) {
        e.route.paths.forEach(p => L.polyline(p.path, {color: d.color, weight: 4, opacity: .9, dashArray: p.real ? null : '4 6'}).bindTooltip('步行约' + p.minutes + '分钟' + (p.real ? '' : '（估算）'), {sticky: true}).addTo(layer));
        e.route.points.forEach((w, k) => L.circleMarker(w.pos, {radius: 6, color: d.color, fillColor: '#fff', fillOpacity: 1, weight: 3}).bindTooltip((k+1) + '. ' + w.name).addTo(layer));
      }
    }
  });
  try { const b = layer.getBounds(); if (b.isValid()) map.fitBounds(b.pad(0.15)); } catch (e) {}
  return ctx;
}
// ---- 列表：一行 = 酒店/景点/通勤/用餐/航班车次 ----
function lockedOf(pid) { for (const d of S.days) for (const it of d.items) if (it.place_id === pid) return it.locked; return false; }
function rowEl(d, e, idx, di, ctx, stopIdx, nStops) {
  const row = document.createElement('div'), mk = ctx && ctx.m[idx], pl = ctx && ctx.l[idx];
  const sel = () => { if (di !== selDay) { selDay = di; renderAll(); return true; } return false; };
  if (e.type === 'conn') { row.className = 'leg'; row.style.cursor = 'default'; row.textContent = '⏱ ' + e.text; return row; }
  if (e.type === 'leg') {
    row.className = 'leg';
    row.innerHTML = '↓ ' + esc(e.mode) + ' 约' + e.minutes + '分钟 · ' + e.km + ' km · ' + (e.real ? '真实路线' : '<span class="est">估算</span>') + (e.note ? '<br>' + esc(e.note) : '') + '<a href="' + esc(e.link) + '" target="_blank" rel="noopener noreferrer">导航</a>';
    row.onclick = ev => { if (ev.target.tagName === 'A' || sel()) return; if (pl) { map.fitBounds(pl.getBounds().pad(0.4)); pl.setStyle({weight: 8}); setTimeout(() => pl.setStyle({weight: e.real ? 5 : 3}), 1500); } };
    return row;
  }
  row.className = 'it';
  const lines = (e.lines || []).map(esc).join('<br>');
  if (e.type === 'hotel') row.innerHTML = '<div class="h"><span class="tm">' + e.time + '</span><span class="nm">🏨 ' + esc(e.role) + '：' + esc(e.name) + '</span></div>';
  else if (e.type === 'term') row.innerHTML = '<div class="h"><span class="tm">' + e.time + '</span><span class="nm">' + e.icon + ' ' + esc(e.role) + '：' + esc(e.name) + '</span></div><div class="sub">' + lines + '</div>';
  else if (e.type === 'meal') row.innerHTML = '<div class="h"><span class="tm"></span><span class="nm">🍜 ' + esc(e.name) + '</span></div><div class="sub">' + lines + (e.web ? '<br><a href="' + esc(e.web) + '" target="_blank" rel="noopener noreferrer" style="color:#1a6fe8">地图</a>' : '') + '</div>';
  else {
    row.innerHTML = '<div class="h"><span class="tm">' + e.arrive + '</span><span class="nm">' + e.n + '. ' + esc(e.name) + (edit && lockedOf(e.pid) ? ' 🔒' : '') + '</span>' + (edit ? '<span class="mv"><button data-a="up" title="上移">▲</button><button data-a="dn" title="下移">▼</button></span>' : '') + '</div><div class="sub">停留 ' + (edit ? '<input class="dur" type="number" min="10" max="720" step="15" value="' + e.stay + '"> ' : e.stay + ' ') + '分钟，约 ' + e.leave + ' 离开<br>' + lines + '</div>';
    if (edit) {
      wireDur(row, e.pid, e.stay);
      row.dataset.pid = e.pid; row.draggable = true;
      row.querySelector('[data-a=up]').onclick = ev => { ev.stopPropagation(); move(e.pid, d.index, Math.max(stopIdx - 1, 0)); };
      row.querySelector('[data-a=dn]').onclick = ev => { ev.stopPropagation(); move(e.pid, d.index, Math.min(stopIdx + 1, nStops - 1)); };
      row.ondragstart = ev => { drag = e.pid; row.classList.add('drag'); ev.dataTransfer.setData('text/plain', e.pid); ev.dataTransfer.effectAllowed = 'move'; };
      row.ondragend = () => { drag = null; document.querySelectorAll('.drag,.over').forEach(x => x.classList.remove('drag', 'over')); document.querySelectorAll('.ins').forEach(x => x.remove()); };
    }
  }
  row.onclick = () => { if (sel()) return; if (mk) { map.setView(mk.getLatLng(), Math.max(map.getZoom(), 15)); mk.openPopup(); } };
  return row;
}
function renderList() {
  const list = $('list'); list.innerHTML = '';
  if (!S.map.days.length) { list.innerHTML = '<div class="empty">还没有分天的行程。先对 agent 说“安排行程”，或者在右侧助手里说。</div>'; drawMap(-1); renderUnscheduled(list); return; }
  const ctx = drawMap(selDay);
  const days = edit ? S.map.days.map((d, i) => i) : [selDay];
  days.forEach(di => {
    const d = S.map.days[di], box = edit ? document.createElement('div') : list; if (edit) { box.className = 'day'; box.dataset.day = d.index; list.appendChild(box); }
    if (edit) { const h = document.createElement('div'); h.className = 'dh' + (di === selDay ? ' cur' : ''); h.innerHTML = '<span class="dot" style="background:' + d.color + '"></span>' + esc(d.label); h.onclick = () => { selDay = di; renderAll(); }; box.appendChild(h); }
    if (!d.closed_loop) { const w = document.createElement('div'); w.className = 'leg'; w.style.cursor = 'default'; w.textContent = d.timeline.some(e => e.type === 'stop') ? (S.map.has_lodging ? '这一天没有从酒店出发再回到酒店的闭环。' : '还没有选定住宿，所以不是从酒店出发的闭环。') : '这一天没有景点。'; box.appendChild(w); }
    const nStops = d.timeline.filter(e => e.type === 'stop').length; let si = 0;
    d.timeline.forEach((e, idx) => box.appendChild(rowEl(d, e, idx, di, di === selDay ? ctx : null, e.type === 'stop' ? si++ : 0, nStops)));
    if (edit && !nStops) box.insertAdjacentHTML('beforeend', '<div class="empty">把景点拖到这里</div>');
    if (edit) wire(box, () => ({kind: 'day', day: d.index}));
  });
  renderUnscheduled(list);
}
function wireDur(el, pid, cur) {
  const inp = el.querySelector('.dur'); if (!inp) return;
  ['click', 'dblclick'].forEach(t => inp.addEventListener(t, ev => ev.stopPropagation()));
  inp.addEventListener('focus', () => { el.draggable = false; }); inp.addEventListener('blur', () => { el.draggable = true; });
  const commit = () => { const v = Number(inp.value); if (!Number.isInteger(v) || v < 10 || v > 720) { say('停留时间要在 10 到 720 分钟之间。', true); inp.value = cur; return; } if (v !== cur) propose([{kind: 'set_duration', place_id: pid, minutes: v}]); };
  inp.addEventListener('change', commit); inp.addEventListener('keydown', ev => { ev.stopPropagation(); if (ev.key === 'Enter') { ev.preventDefault(); inp.blur(); } });
}
function renderUnscheduled(list) {
  if (!S.unscheduled.length && !(S.orphan_meals || []).length && !edit) return;
  const u = document.createElement('div'); u.className = 'day'; u.innerHTML = '<div class="dh">未安排' + (edit ? '（拖到这里表示移出行程）' : '') + (edit ? '<button id="addp" style="margin-left:auto">＋ 加景点</button>' : '') + '</div>';
  if (edit) u.querySelector('#addp').onclick = apOpen;
  S.unscheduled.forEach(it => { const c = document.createElement('div'); c.className = 'it'; c.dataset.pid = it.place_id; c.style.cursor = edit ? 'grab' : 'default';
    c.innerHTML = '<div class="h"><span class="nm">' + esc(it.name) + '</span><span class="tm" style="min-width:0">' + esc(it.reason || '') + '</span></div>' + (edit ? '<div class="sub">停留 <input class="dur" type="number" min="10" max="720" step="15" value="' + it.duration_min + '"> 分钟</div>' : '');
    if (edit) wireDur(c, it.place_id, it.duration_min);
    if (edit) { c.draggable = true; c.ondragstart = e => { drag = it.place_id; c.classList.add('drag'); e.dataTransfer.setData('text/plain', it.place_id); }; c.ondragend = () => { drag = null; }; } u.appendChild(c); });
  (S.orphan_meals || []).forEach(m => u.insertAdjacentHTML('beforeend', '<div class="it" style="cursor:default"><div class="h"><span class="nm">🍜 ' + esc(m.name) + '</span></div><div class="sub">原来挂在「' + esc(m.after) + '」之后，该景点现在不在行程里（用餐点没有删除）</div></div>'));
  if (edit) wire(u, () => ({kind: 'none'}));
  list.appendChild(u);
}
function wire(zone, info) {
  zone.ondragover = e => { if (!drag) return; e.preventDefault(); zone.classList.add('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    const cards = [...zone.querySelectorAll('.it[data-pid]')].filter(c => c.dataset.pid !== drag); let idx = cards.findIndex(c => e.clientY < c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2); if (idx < 0) idx = cards.length;
    zone.dataset.idx = idx; const bar = document.createElement('div'); bar.className = 'ins'; if (cards[idx]) zone.insertBefore(bar, cards[idx]); else zone.appendChild(bar); };
  zone.ondragleave = e => { if (!zone.contains(e.relatedTarget)) { zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove()); } };
  zone.ondrop = e => { e.preventDefault(); const pid = drag || e.dataTransfer.getData('text/plain'); const t = info(); zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    if (t.kind === 'day') move(pid, t.day, Number(zone.dataset.idx || 0)); else if (t.kind === 'none') propose([{kind: 'remove', place_id: pid}]); };
}
function move(pid, day, pos) {
  const ops = []; if (lockedOf(pid)) ops.push({kind: 'lock', place_id: pid, locked: false});
  ops.push({kind: 'move', place_id: pid, to_day: day, to_position: pos}); propose(ops);
}
async function propose(ops) {
  let r; try { r = await api('preview', {base_revision: S.revision, ops}); } catch (e) { say(e.message, true); if (e.status === 409) load(); return; }
  showPrev(r);
}
function showPrev(r) {
  pending = r;
  $('chg').innerHTML = pending.changes.map(x => '<li>' + esc(x) + '</li>').join('');
  $('iss').innerHTML = pending.new_issues.length ? '<div class="w">改完后新增的问题：</div><ul>' + pending.new_issues.map(i => '<li class="w">' + esc(i) + '</li>').join('') + '</ul>' : '<div style="color:#15803d">没有新增问题。</div>';
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
  try { const r = await api('refine', {base_revision: S.revision, day: day || null}); say(r.ok ? r.message + (r.more ? '。还有部分路段没查，请再点“更新路线”。' : '') : r.message + '（路线仍是估算）', false); } catch (e) { say(e.message, true); }
  await load();
}
$('refine').onclick = () => refineRoutes(null);
$('cancel').onclick = closePrev; function closePrev() { pending = null; $('prev').style.display = 'none'; }
$('undo').onclick = async () => { try { await api('undo', {base_revision: S.revision}); say('已撤销。'); } catch (e) { say(e.message, true); } closePrev(); load(); };
// ---- 聊天 + 自动刷新 ----
const msgs = $('cmsgs'); let busy = false;
function bubble(cls, text) { const d = document.createElement('div'); d.className = 'm ' + cls; d.textContent = text; msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight; return d; }
let chatUp = null;
function chatMark(up, msg) {
  const el = $('cstat'); el.textContent = up ? '● 已连接' : '● 未连接'; el.className = up ? 'ok' : '';
  if (!up && msg && chatUp !== false) bubble('e', msg);
  chatUp = up;
}
async function chatStatus() { try { const r = await api('chat_status'); chatMark(r.connected, r.message); return r.connected; } catch (e) { chatMark(false, '没连上工作台服务。'); return false; } }
async function send() {
  const text = $('ctext').value.trim(); if (!text || busy) return;
  busy = true; $('csend').disabled = true; const rev0 = S ? S.revision : null, trip0 = S ? S.trip : null; $('ctext').value = ''; bubble('u', text); const out = bubble('a', '…'); let got = '', done = false;
  try {
    const r = await fetch('api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text})});
    if (!r.ok) { const j = await r.json().catch(() => ({})); out.className = 'm e'; out.textContent = j.error || ('出错了 ' + r.status); if (r.status >= 500) chatMark(false); }
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
  if (S && S.days.length && S.trip === trip0 && S.revision !== rev0) await refineRoutes(null);      // 助手改了行程：自动补查还没有真实路线的路段（已查过的不会重查）
}
$('csend').onclick = send; $('ctext').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
document.querySelectorAll('#chips button').forEach(b => b.onclick = () => { $('ctext').value = b.dataset.t; $('ctext').focus(); });
const fit = () => setTimeout(() => map.invalidateSize(), 50); window.addEventListener('resize', fit);
$('ctoggle').onclick = () => { $('chat').classList.toggle('hide'); syncSp2(); fit(); }; $('cclose').onclick = () => { $('chat').classList.add('hide'); syncSp2(); fit(); };
setInterval(async () => {
  if (document.hidden || !S || drag) return;
  try { const r = await api('rev'); if (r.revision !== S.revision || (r.trip || null) !== (S.trip || null)) { if (pending) { closePrev(); say('行程在别处被修改了，刚才的预览已取消。'); } await load(); } } catch (e) {}
}, 2000);
chatStatus(); setInterval(() => { if (!document.hidden && !$('chat').classList.contains('hide')) chatStatus(); }, 10000);
// ---- 三栏宽度可拖动（记住上次的宽度；双击分隔条恢复默认）----
const WK = {sw: ['--sw', 400, 240, 0.6], cw: ['--cw', 340, 260, 0.5]};
function wget(k) { try { return Number(localStorage.getItem('tsw_' + k)) || 0; } catch (e) { return 0; } }
function wset(k, v) { try { v === null ? localStorage.removeItem('tsw_' + k) : localStorage.setItem('tsw_' + k, String(v)); } catch (e) {} }
function clampW(k, v) { const [, , min, frac] = WK[k]; const other = k === 'sw' ? ($('chat').classList.contains('hide') ? 0 : $('chat').offsetWidth) : $('side').offsetWidth; return Math.max(min, Math.min(v, Math.min(innerWidth * frac, innerWidth - other - 280))); }
function applyW(k, v) { document.documentElement.style.setProperty(WK[k][0], v === null ? WK[k][1] + 'px' : clampW(k, v) + 'px'); fit(); }
function splitter(id, k, dir) {
  const el = $(id);
  el.onpointerdown = e => { e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add('on'); document.body.classList.add('resizing'); const x0 = e.clientX, w0 = (k === 'sw' ? $('side') : $('chat')).offsetWidth; let last = null;
    el.onpointermove = m => { last = clampW(k, w0 + dir * (m.clientX - x0)); applyW(k, last); };
    el.onpointerup = () => { el.onpointermove = el.onpointerup = null; el.classList.remove('on'); document.body.classList.remove('resizing'); if (last !== null) wset(k, Math.round(last)); fit(); }; };
  el.ondblclick = () => { wset(k, null); applyW(k, null); };
}
splitter('sp1', 'sw', 1); splitter('sp2', 'cw', -1);
for (const k of ['sw', 'cw']) { const v = wget(k); if (v) applyW(k, v); }
window.addEventListener('resize', () => { for (const k of ['sw', 'cw']) { const v = wget(k); if (v) applyW(k, v); } });
function syncSp2() { $('sp2').style.display = $('chat').classList.contains('hide') ? 'none' : ''; }
syncSp2();
load();
</script></body></html>
"""


def page_html() -> str:
    return (TEMPLATE
            .replace("__CSS__", (_ASSETS / "leaflet.css").read_text(encoding="utf-8"))
            .replace("__JS__", (_ASSETS / "leaflet.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
