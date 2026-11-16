// 单桌观看页：棋盘渲染 + 胜率曲线 + 团队投票 + SSE 实时刷新
const tableNo = parseInt(location.pathname.split('/').filter(Boolean).pop(), 10);
document.getElementById('title').textContent = tableNo + ' 号桌';

const canvas = document.getElementById('board');
const ctx = canvas.getContext('2d');
const curve = document.getElementById('curve');
const cctx = curve.getContext('2d');
const COL = 'ABCDEFGHJKLMNOPQRST';   // GTP 习惯：跳过 I

let current = null;      // 最新状态
let hist = [];           // 胜率历史
let voteMember = null;   // 当前选中的投票人
let voteClock = null;    // 倒计时定时器
let voteDeadline = 0;

function pct(x){ return (Math.round((x || 0) * 1000) / 10).toFixed(1) + '%'; }
function statusCn(s){ return {playing:'进行中', waiting:'等待', finished:'已结束'}[s] || s; }
function coordStr(c, size){ return COL[c[0]] + (size - c[1]); }
function el(id){ return document.getElementById(id); }

// ---------------------------------------------------------------- 棋盘
function drawBoard(v){
  const N = v.size, W = canvas.width, pad = W * 0.075;
  const step = (W - pad * 2) / (N - 1);
  ctx.clearRect(0, 0, W, W);
  ctx.fillStyle = '#e8c892'; ctx.fillRect(0, 0, W, W);
  // 网格
  ctx.strokeStyle = '#5a4326'; ctx.lineWidth = 1.3;
  for(let i = 0; i < N; i++){
    const p = pad + i * step;
    ctx.beginPath(); ctx.moveTo(pad, p); ctx.lineTo(W - pad, p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p, pad); ctx.lineTo(p, W - pad); ctx.stroke();
  }
  // 星位
  if(v.game_type === 'go' || v.game_type === 'gomoku'){
    let pts = [];
    if(v.game_type === 'go'){
      const c = (N - 1) / 2, off = (N >= 13) ? 3 : 0;
      const xs = (N >= 13) ? [off, c, N - 1 - off] : [c];
      const ys = (N >= 13) ? [off, c, N - 1 - off] : [c];
      for(const x of xs) for(const y of ys) pts.push([x, y]);
    } else { pts = [[(N - 1) / 2, (N - 1) / 2]]; }
    ctx.fillStyle = '#3a2c17';
    for(const [x, y] of pts){
      ctx.beginPath(); ctx.arc(pad + x * step, pad + y * step, Math.max(2, step * 0.09), 0, 7); ctx.fill();
    }
  }
  // 坐标
  ctx.fillStyle = '#8a7444'; ctx.font = Math.max(10, step * 0.32) + 'px system-ui';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for(let i = 0; i < N; i++){
    ctx.fillText(COL[i], pad + i * step, pad * 0.48);
    ctx.fillText(String(N - i), pad * 0.48, pad + i * step);
  }
  // 棋子
  const R = step * 0.46;
  for(let y = 0; y < N; y++) for(let x = 0; x < N; x++){
    const c = v.board[y][x]; if(!c) continue;
    const cx = pad + x * step, cy = pad + y * step;
    const g = ctx.createRadialGradient(cx - R / 3, cy - R / 3, R / 6, cx, cy, R);
    if(c === 1){ g.addColorStop(0, '#525866'); g.addColorStop(1, '#0b0d12'); }
    else { g.addColorStop(0, '#ffffff'); g.addColorStop(1, '#cfd6e4'); }
    ctx.beginPath(); ctx.fillStyle = g; ctx.arc(cx, cy, R, 0, 7); ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,.25)'; ctx.lineWidth = 1; ctx.stroke();
  }
  // 最后一手标记
  const lm = v.last_move;
  if(lm && (lm.is_pass || lm.x === null)){
    el('boardfoot').textContent = '第 ' + lm.move_no + ' 手：' + (lm.color === 'BLACK' ? '黑' : '白') + '方 停一手 (Pass)';
  } else if(lm){
    const cx = pad + lm.x * step, cy = pad + lm.y * step;
    ctx.beginPath(); ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 3.2;
    ctx.arc(cx, cy, R * 0.62, 0, 7); ctx.stroke();
    ctx.fillStyle = (lm.color === 'BLACK') ? '#fff' : '#111';
    ctx.font = 'bold ' + Math.max(11, step * 0.42) + 'px system-ui';
    ctx.fillText(String(lm.move_no), cx, cy);
    el('boardfoot').textContent = '第 ' + lm.move_no + ' 手：' + (lm.color === 'BLACK' ? '黑' : '白') +
      '方 ' + coordStr([lm.x, lm.y], N);
  } else {
    el('boardfoot').textContent = '　';
  }
}

// ---------------------------------------------------------------- 胜率曲线
function drawCurve(history){
  const W = curve.width, H = curve.height, pad = 34;
  cctx.clearRect(0, 0, W, H);
  cctx.fillStyle = '#121a2b'; cctx.fillRect(0, 0, W, H);
  cctx.strokeStyle = '#243149'; cctx.lineWidth = 1;
  for(let i = 0; i <= 4; i++){
    const y = pad + (H - 2 * pad) * i / 4;
    cctx.beginPath(); cctx.moveTo(pad, y); cctx.lineTo(W - pad, y); cctx.stroke();
  }
  const mid = pad + (H - 2 * pad) * 0.5;
  cctx.strokeStyle = '#3a4a68'; cctx.setLineDash([5, 5]);
  cctx.beginPath(); cctx.moveTo(pad, mid); cctx.lineTo(W - pad, mid); cctx.stroke();
  cctx.setLineDash([]);
  cctx.fillStyle = '#93a1bd'; cctx.font = '12px system-ui';
  cctx.textAlign = 'right'; cctx.textBaseline = 'middle';
  cctx.fillText('100%', pad - 6, pad);
  cctx.fillText('50%', pad - 6, mid);
  cctx.fillText('0%', pad - 6, H - pad);
  const data = (history || []).map(d => d.black_winrate);
  if(data.length < 1){
    cctx.textAlign = 'center'; cctx.fillStyle = '#6b7a99';
    cctx.fillText('尚无数据', W / 2, H / 2); return;
  }
  const n = data.length;
  const X = i => n <= 1 ? (W - pad) : pad + (W - 2 * pad) * i / (n - 1);
  const Y = v => pad + (H - 2 * pad) * (1 - Math.max(0, Math.min(1, v)));
  cctx.beginPath(); cctx.moveTo(X(0), H - pad);
  data.forEach((v, i) => cctx.lineTo(X(i), Y(v)));
  cctx.lineTo(X(n - 1), H - pad); cctx.closePath();
  const grd = cctx.createLinearGradient(0, pad, 0, H - pad);
  grd.addColorStop(0, 'rgba(76,141,255,.35)'); grd.addColorStop(1, 'rgba(76,141,255,0)');
  cctx.fillStyle = grd; cctx.fill();
  cctx.beginPath();
  data.forEach((v, i) => i ? cctx.lineTo(X(i), Y(v)) : cctx.moveTo(X(i), Y(v)));
  cctx.strokeStyle = '#4c8dff'; cctx.lineWidth = 2.4; cctx.stroke();
  const li = n - 1;
  cctx.beginPath(); cctx.fillStyle = '#ffb020'; cctx.arc(X(li), Y(data[li]), 4.5, 0, 7); cctx.fill();
  el('curve-hint').textContent = '黑方胜率 ' + pct(data[li]) + ' · 共 ' + n + ' 手';
}

// ---------------------------------------------------------------- 团队 / 投票
function sideOf(v){
  if(v.to_play === 'BLACK') return v.black_team;
  if(v.to_play === 'WHITE') return v.white_team;
  return null;
}
function activeNames(side, moveNo){
  if(!side) return [];
  const phases = (side.phases || []).slice().sort((a, b) => a.until_move - b.until_move);
  if(!phases.length) return (side.members || []).map(m => m.name);
  for(const p of phases) if(moveNo <= p.until_move) return p.active || [];
  return phases[phases.length - 1].active || [];
}
function phaseName(side, moveNo){
  const phases = ((side && side.phases) || []).slice().sort((a, b) => a.until_move - b.until_move);
  if(!phases.length) return '全程';
  for(const p of phases) if(moveNo <= p.until_move) return p.name;
  return phases[phases.length - 1].name;
}

function renderVote(v){
  const panel = el('votepanel'), side = sideOf(v);
  if(!v.vote && !side){ panel.hidden = true; return; }
  panel.hidden = false;
  const body = el('vote-body'), tools = el('vote-tools'), cnt = el('vote-count');
  el('vote-phase').textContent = side
    ? ((v.to_play === 'BLACK' ? '黑方' : '白方') + ' · ' + side.name + ' · ' + phaseName(side, v.move_number)) : '';
  const active = activeNames(side, v.move_number);

  if(!v.vote){
    if(voteClock){ clearInterval(voteClock); voteClock = null; }
    cnt.textContent = '';
    body.innerHTML = '<div class="roster">当前阶段上场：<b>' + (active.join('、') || '-') + '</b></div>';
    tools.innerHTML = side ? '<button id="vote-open">发起 60 秒投票</button>' : '';
    const b = el('vote-open');
    if(b) b.onclick = () => post('/api/table/' + tableNo + '/vote/open',
      {color: v.to_play, timeout_s: 60, remind_at_s: 15});
    return;
  }
  const vt = v.vote;
  if(!active.includes(voteMember)) voteMember = active[0] || null;
  const opts = active.map(n => '<option' + (n === voteMember ? ' selected' : '') + '>' + n + '</option>').join('');
  const max = Math.max(1, ...((vt.ranking || []).map(r => r.weight)));
  const rank = (vt.ranking || []).map(r => '<div class="rank">' +
      '<span class="pt">' + coordStr(r.coord, v.size) + '</span>' +
      '<span class="rw">' + r.weight.toFixed(1) + '</span>' +
      '<span class="rb"><i style="width:' + (r.weight / max * 100).toFixed(0) + '%"></i></span>' +
      '<span class="vc">' + r.count + '票</span></div>').join('')
    || '<div class="muted">尚无投票，点击棋盘投一票</div>';
  body.innerHTML = '<div class="roster">投票人：<select id="vote-member">' + opts + '</select></div>' +
    '<div class="ranks">' + rank + '</div>' +
    '<div class="muted votertip">已选 “' + (voteMember || '-') + '”，点击棋盘即为该成员投票（队长权重更高）</div>';
  const sel = el('vote-member');
  if(sel) sel.onchange = () => { voteMember = sel.value; };
  tools.innerHTML = '<button id="vote-cap">队长定最高票点</button>' +
    '<button id="vote-resolve">结算投票</button>' +
    '<button id="vote-cancel">取消</button>';
  el('vote-cap').onclick = () => {
    const top = vt.ranking && vt.ranking[0];
    if(top) post('/api/table/' + tableNo + '/vote/captain', {x: top.coord[0], y: top.coord[1]});
  };
  el('vote-resolve').onclick = () => post('/api/table/' + tableNo + '/vote/resolve', {});
  el('vote-cancel').onclick = () => post('/api/table/' + tableNo + '/vote/cancel', {});

  voteDeadline = Date.now() + (vt.remaining || 0) * 1000;
  if(voteClock) clearInterval(voteClock);
  voteClock = setInterval(() => {
    const left = Math.max(0, Math.round((voteDeadline - Date.now()) / 1000));
    cnt.textContent = '剩余 ' + left + ' 秒' +
      (left <= 15 ? ' · 提醒队长决定' : '') + (left <= 0 ? ' · 超时将按最高票强制落子' : '');
    cnt.className = 'countdown' + (left <= 15 ? ' warn' : '');
  }, 250);
}

// ---------------------------------------------------------------- 更新
function update(v){
  current = v;
  const st = el('status'); st.className = 'badge ' + (v.status || ''); st.textContent = statusCn(v.status);
  const bw = v.black_winrate || 0.5;
  el('bwr').textContent = pct(bw);
  el('wwr').textContent = pct(1 - bw);
  el('mv').textContent = v.move_number + ' 手 · ' + (v.to_play === 'BLACK' ? '黑行' : (v.to_play === 'WHITE' ? '白行' : '-'));
  el('eng').textContent = (v.engine || '-') + (v.score_lead ? (' · 领先 ' + v.score_lead.toFixed(1)) : '');
  const fl = el('fouls');
  if(v.fouls && v.fouls.length){
    fl.innerHTML = v.fouls.map(f => '<div class="f">⚠ ' + f.color_cn + '方 ' + f.foul_type_cn +
      (f.note ? (' ' + f.note) : '') + '（第' + f.move_no + '手）</div>').join('');
  } else fl.textContent = '暂无犯规';
  if(v.history && v.history.length) hist = v.history;
  drawBoard(v);
  drawCurve(hist);
  renderVote(v);
  if(v.game_over) showOverlay(v);
}

function showOverlay(v){
  el('ov-title').textContent = '终局 · ' + (v.verdict_cn || '');
  const fl = (v.fouls || []).length;
  el('ov-body').innerHTML =
    '<p>' + v.player_black + ' ● vs ○ ' + v.player_white + '</p>' +
    '<p>共 ' + v.move_number + ' 手 · ' + v.game_name_cn + '</p>' +
    '<p>犯规 ' + fl + ' 次 · ' + (v.first_pass ? ('先弃权：' + v.first_pass) : '无弃权') + '</p>' +
    '<p class="muted">点击任意处关闭</p>';
  el('overlay').classList.add('show');
}
el('overlay').addEventListener('click', () => el('overlay').classList.remove('show'));

// ---------------------------------------------------------------- 交互
async function post(url, obj){
  try{
    await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(obj || {})});
  }catch(e){}
  load();
}

canvas.addEventListener('click', async (ev) => {
  if(!current || current.game_over) return;
  const rect = canvas.getBoundingClientRect();
  const N = current.size, W = canvas.width, pad = W * 0.075, step = (W - pad * 2) / (N - 1);
  const px = (ev.clientX - rect.left) / rect.width * W, py = (ev.clientY - rect.top) / rect.height * W;
  const x = Math.round((px - pad) / step), y = Math.round((py - pad) / step);
  if(x < 0 || y < 0 || x >= N || y >= N) return;
  if(current.vote){
    if(!voteMember) return;
    post('/api/table/' + tableNo + '/vote/cast', {member: voteMember, x, y});
  } else {
    post('/api/play', {table: tableNo, color: current.to_play, x, y});
  }
});

el('toolbar').innerHTML = '<button id="passbtn">停一手 (Pass)</button>';
el('passbtn').onclick = () => {
  if(!current || current.game_over) return;
  post('/api/play', {table: tableNo, color: current.to_play, pass: true});
};

async function load(){
  try{
    const r = await fetch('/api/table/' + tableNo);
    const v = await r.json();
    if(v && v.game_type) update(v);
  }catch(e){}
}
function connect(){
  const es = new EventSource('/events?table=' + tableNo);
  es.onmessage = (e) => {
    try{
      const ev = JSON.parse(e.data);
      if(ev.type === 'snapshot' || ev.type === 'state'){ if(ev.payload) update(ev.payload); }
      else { load(); }
    }catch(_){}
  };
}
load();
connect();
setInterval(load, 8000);