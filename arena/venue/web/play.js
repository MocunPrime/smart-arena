// 对弈大厅：创建房间 / 按对局码加入 / 房间列表
const NAME_KEY = 'arena_player_name';
const SIZES = { go: [9, 13, 19], gomoku: [15, 19], reversi: [6, 8, 10] };

function el(id){ return document.getElementById(id); }
function pct(x){ return (Math.round((x || 0) * 1000) / 10).toFixed(1) + '%'; }
function statusCn(s){ return {playing:'进行中', waiting:'等待对手', ready:'待开局', finished:'已结束'}[s] || s; }
function modeCn(m){ return m === 'pve' ? '人机' : '真人'; }

// ------------------------------------------------------------------ 表单
function fillSizes(){
  const gt = el('f-game').value;
  const list = SIZES[gt] || [8];
  el('f-size').innerHTML = list.map(s => '<option value="' + s + '">' + s + ' 路</option>').join('');
}
el('f-game').onchange = fillSizes;
fillSizes();

(function initName(){
  let name = '';
  try { name = localStorage.getItem(NAME_KEY) || ''; } catch (e) {}
  el('f-name').value = name;
  el('j-name').value = name;
})();

function remember(name){
  if(!name) return;
  try { localStorage.setItem(NAME_KEY, name); } catch (e) {}
}

function hint(id, text, cls){
  const box = el(id);
  box.textContent = text || '';
  box.className = 'hintbar' + (cls ? ' ' + cls : '');
}

async function post(url, obj){
  const r = await fetch(url, {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(obj || {})
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  return data || {};
}

function storeSeat(code, seat){
  try {
    localStorage.setItem('arena_token_' + code, seat.token);
    localStorage.setItem('arena_name_' + code, seat.name);
  } catch (e) {}
}

// ------------------------------------------------------------------ 创建
el('create-btn').onclick = async () => {
  const name = el('f-name').value.trim() || '玩家';
  const payload = {
    game_type: el('f-game').value,
    size: parseInt(el('f-size').value, 10) || null,
    mode: el('f-mode').value,
    color: el('f-color').value,
    name: name
  };
  hint('create-hint', '正在创建…');
  const btn = el('create-btn');
  btn.disabled = true;
  const d = await post('/api/room/create', payload);
  btn.disabled = false;
  if(d.error || !d.code){
    hint('create-hint', '创建失败：' + (d.error || '未知错误'), 'bad');
    return;
  }
  remember(name);
  storeSeat(d.code, d.seat);
  hint('create-hint', '创建成功，对局码 ' + d.code + '，正在进入棋盘…', 'ok');
  location.href = d.url || ('/room/' + d.code);
};

// ------------------------------------------------------------------ 加入
el('join-btn').onclick = async () => {
  const code = (el('j-code').value || '').trim().toUpperCase();
  const name = el('j-name').value.trim() || '玩家';
  if(!code){ hint('join-hint', '请先输入对局码', 'bad'); return; }
  hint('join-hint', '正在加入…');
  const btn = el('join-btn');
  btn.disabled = true;
  const d = await post('/api/room/' + encodeURIComponent(code) + '/join', {
    name: name, color: el('j-color').value || null
  });
  btn.disabled = false;
  if(d.error || !d.code){
    hint('join-hint', '加入失败：' + (d.error || '未知错误'), 'bad');
    return;
  }
  remember(name);
  storeSeat(d.code, d.seat);
  hint('join-hint', '已落座（' + d.seat.color_cn + '方），正在进入棋盘…', 'ok');
  location.href = d.url || ('/room/' + d.code);
};

el('j-code').addEventListener('input', (e) => {
  e.target.value = (e.target.value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
});

// ------------------------------------------------------------------ 房间列表
function seatText(room, color){
  const s = (room.seats || {})[color];
  return s ? (s.name + (s.is_ai ? '（AI）' : '')) : '空位';
}

function makeRoomCard(room){
  const a = document.createElement('a');
  a.className = 'card';
  a.href = '/room/' + room.code;
  const bw = room.black_winrate || 0.5;
  a.innerHTML =
    '<div class="no">' + room.code + ' <span class="badge ' + (room.status || '') + '">' +
      statusCn(room.status) + '</span></div>' +
    '<div class="meta">' + (room.game_name_cn || '') + ' · ' + modeCn(room.mode) +
      ' · 第 ' + (room.move_number || 0) + ' 手</div>' +
    '<div class="players"><span>● ' + seatText(room, 'BLACK') + '</span>' +
      '<span>○ ' + seatText(room, 'WHITE') + '</span></div>' +
    '<div class="bar"><i style="width:' + (bw * 100).toFixed(1) + '%"></i></div>' +
    '<div class="barlabel"><span>黑 ' + pct(bw) + '</span><span>白 ' + pct(1 - bw) + '</span></div>' +
    '<div class="meta">' + (room.full ? '点击观战 / 进入' : '有空位，可加入') + '</div>';
  return a;
}

async function loadRooms(){
  const box = el('rooms');
  try{
    const r = await fetch('/api/rooms');
    const d = await r.json();
    const list = (d && d.rooms) || [];
    el('rooms-count').textContent = list.length ? ('共 ' + list.length + ' 局') : '';
    box.innerHTML = '';
    if(!list.length){ box.textContent = '暂无对局，先创建一个吧'; return; }
    list.forEach(room => box.appendChild(makeRoomCard(room)));
  }catch(e){
    box.textContent = '房间列表加载失败';
  }
}

loadRooms();
setInterval(loadRooms, 5000);

// ------------------------------------------------------------------ 棋谱存档
function fmtTime(ts){
  if(!ts) return '';
  const d = new Date(ts * 1000);
  const p = n => (n < 10 ? '0' : '') + n;
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
    p(d.getHours()) + ':' + p(d.getMinutes());
}

function gameCn(g){ return {go:'围棋', gomoku:'五子棋', reversi:'翻转棋'}[g] || '对局'; }

function makeRecordCard(r){
  const wrap = document.createElement('div');
  wrap.className = 'reccard';
  const a = document.createElement('a');
  a.className = 'rec-main';
  a.href = '/replay/' + encodeURIComponent(r.name);
  a.title = '点击回放这局棋';
  a.innerHTML =
    '<div class="recrow"><span class="reccode">' + (r.code || '----') + '</span>' +
      '<span class="badge">' + gameCn(r.game_type) + '</span>' +
      '<span class="muted">' + (r.size_label ? r.size_label + ' 路' : '') + '</span></div>' +
    '<div class="recplayers"><span>● ' + (r.black || '黑方') + '</span>' +
      '<span>○ ' + (r.white || '白方') + '</span></div>' +
    '<div class="recmeta"><span>' + (r.date || '') + '</span>' +
      '<span class="res">' + (r.result || '-') + '</span></div>' +
    '<div class="muted">' + fmtTime(r.modified) + '</div>';
  wrap.appendChild(a);
  const dl = document.createElement('a');
  dl.className = 'recdl';
  dl.href = r.download_url || ('/api/records/' + encodeURIComponent(r.name));
  dl.setAttribute('download', r.name || '');
  dl.textContent = '下载 SGF';
  wrap.appendChild(dl);
  return wrap;
}

async function loadRecords(){
  const box = el('records');
  if(!box) return;
  try {
    const r = await fetch('/api/records?limit=24');
    const d = await r.json();
    const list = (d && d.records) || [];
    el('records-count').textContent = list.length ? ('共 ' + list.length + ' 份') : '';
    box.innerHTML = '';
    if(!list.length){ box.textContent = '暂无棋谱，对局结束或房间关闭后会自动保存'; return; }
    list.forEach(rec => box.appendChild(makeRecordCard(rec)));
  } catch(e) {
    box.textContent = '棋谱列表加载失败';
  }
}

loadRecords();
setInterval(loadRecords, 10000);
