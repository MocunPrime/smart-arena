// 线上对弈页：棋盘渲染 + 落子 / 停一手 / 认输 + 犯规提示 + 终局汇总 + SSE 刷新
const code = (location.pathname.split('/').filter(Boolean).pop() || '').toUpperCase();
const canvas = document.getElementById('board');
const ctx = canvas.getContext('2d');
const COL = 'ABCDEFGHJKLMNOPQRST';        // GTP 习惯：跳过 I
const TOKEN_KEY = 'arena_token_' + code;   // 座位凭证：只存在本人浏览器
const NAME_KEY = 'arena_name_' + code;

function el(id){ return document.getElementById(id); }
function pct(x){ return (Math.round((x || 0) * 1000) / 10).toFixed(1) + '%'; }
function statusCn(s){ return {playing:'进行中', waiting:'等待对手', ready:'待开局', finished:'已结束'}[s] || s; }
function coordStr(c, size){ return COL[c[0]] + (size - c[1]); }
function colorCn(c){ return c === 'BLACK' ? '黑' : (c === 'WHITE' ? '白' : '-'); }

let current = null;                       // 最新房间视图
let token = '';
try { token = localStorage.getItem(TOKEN_KEY) || ''; } catch (e) {}

el('code').textContent = code || '----';
document.title = '对局 ' + code + ' · 线上对弈';

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
    el('boardfoot').textContent = '第 ' + lm.move_no + ' 手：' + colorCn(lm.color) + '方 停一手 (Pass)';
  } else if(lm){
    const cx = pad + lm.x * step, cy = pad + lm.y * step;
    ctx.beginPath(); ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 3.2;
    ctx.arc(cx, cy, R * 0.62, 0, 7); ctx.stroke();
    ctx.fillStyle = (lm.color === 'BLACK') ? '#fff' : '#111';
    ctx.font = 'bold ' + Math.max(11, step * 0.42) + 'px system-ui';
    ctx.fillText(String(lm.move_no), cx, cy);
    el('boardfoot').textContent = '第 ' + lm.move_no + ' 手：' + colorCn(lm.color) +
      '方 ' + coordStr([lm.x, lm.y], N);
  } else {
    el('boardfoot').textContent = '　';
  }
}

// ---------------------------------------------------------------- 声音 / 提示
let audioCtx = null;
function beep(times){
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    let t = audioCtx.currentTime;
    for(let i = 0; i < times; i++){
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = 'square'; o.frequency.value = 660;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
      o.connect(g); g.connect(audioCtx.destination);
      o.start(t); o.stop(t + 0.2);
      t += 0.24;
    }
  } catch (e) {}
}

let toastTimer = null;
function toast(text, cls){
  const box = el('toast');
  box.textContent = text;
  box.className = 'toast show' + (cls ? ' ' + cls : '');
  if(toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = 'toast'; }, 2600);
}

// 犯规弹窗（会议：犯规要"声音 + 弹窗 + 记录"）
function showFoul(rec, loss){
  beep(loss ? 3 : 1);
  const wrap = document.createElement('div');
  wrap.className = 'overlay show foulbox';
  wrap.innerHTML =
    '<div class="box">' +
      '<h2>' + (loss ? '⚠ 两次犯规 · 判负' : '⚠ 犯规警告') + '</h2>' +
      '<div class="ov-body">' +
        '<p class="foulbig">' + rec.color_cn + '方 · ' + rec.foul_type_cn + '</p>' +
        (rec.note ? ('<p class="muted">' + rec.note + '</p>') : '') +
        '<p class="muted">发生在第 ' + rec.move_no + ' 手</p>' +
        '<p>' + (loss
            ? '本局按赛事规定累计两次犯规，直接判负，比赛结束。'
            : '这是该方第一次犯规：口头警告一次，再次犯规即判负。') + '</p>' +
      '</div>' +
      '<div class="toolbar"><button>知道了</button></div>' +
    '</div>';
  wrap.querySelector('button').onclick = () => wrap.remove();
  wrap.addEventListener('click', (e) => { if(e.target === wrap) wrap.remove(); });
  document.body.appendChild(wrap);
}

// 弃权（停一手）查询：记录"某方在对方某手之后弃权"，并标出第一个弃权方
function showPassLog(v){
  const log = v.pass_log || [];
  let body;
  if(!log.length){
    body = '<p>本局暂无弃权（停一手）记录。</p>';
  } else {
    body = '<p>第一个弃权方：<b>' + (v.first_pass ? (colorCn(v.first_pass) + '方') : '（无）') + '</b></p>';
    body += log.map(r => {
      const after = r.after_move_no
        ? ('在' + (r.after_color_cn || colorCn(r.after_color)) + '方第 ' + r.after_move_no + ' 手之后')
        : '在开局第 1 手之前';
      return '<p>第 ' + r.order + ' 次弃权：<b>' + r.color_cn + '方</b> ' + after +
        ' 停一手（该手为第 ' + r.move_no + ' 手）</p>';
    }).join('');
  }
  el('ov-title').textContent = '弃权（停一手）记录';
  el('ov-body').innerHTML = body + '<p class="muted">点击空白处关闭</p>';
  el('overlay').classList.add('show');
}

// ---------------------------------------------------------------- 更新
function update(v){
  if(!v || !v.game_type) return;
  current = v;
  const st = el('status');
  st.className = 'badge ' + (v.status || ''); st.textContent = statusCn(v.status);
  el('pblack').textContent = v.player_black || '--';
  el('pwhite').textContent = v.player_white || '--';
  const bw = v.black_winrate || 0.5;
  el('bwr').textContent = pct(bw) + ' / ' + pct(1 - bw);
  el('mv').textContent = v.move_number + ' 手 · ' + (v.to_play === 'BLACK' ? '黑行' : (v.to_play === 'WHITE' ? '白行' : '-'));

  // 座位徽标
  const seat = el('seat');
  if(v.viewer && v.viewer.seated){
    seat.textContent = '你执' + v.viewer.color_cn + '（' + v.viewer.name + '）';
    seat.className = 'muted ok';
  } else {
    seat.textContent = '未落座（仅观看）';
    seat.className = 'muted';
  }

  // 犯规列表
  const fl = el('fouls');
  if(v.fouls && v.fouls.length){
    fl.innerHTML = v.fouls.map(f => '<div class="f">⚠ ' + f.color_cn + '方 ' + f.foul_type_cn +
      (f.note ? (' ' + f.note) : '') + '（第' + f.move_no + ' 手）</div>').join('');
  } else fl.textContent = '暂无犯规';

  drawBoard(v);
  renderJoin(v);
  renderToolbar(v);

  if(v.game_over) showOverlay(v);
}

function renderJoin(v){
  const panel = el('joinpanel');
  const seated = !!(v.viewer && v.viewer.seated);
  if(seated || !v.joinable && seated){ panel.hidden = true; return; }
  // 未落座：显示加入面板（对局已满或已结束时只提示观战）
  if(seated){ panel.hidden = true; return; }
  panel.hidden = false;
  el('join-sub').textContent = v.mode_cn + ' · ' + (v.game_name_cn || '') + ' ' + v.size + ' 路' +
    (v.joinable ? '' : ' · 已满，仅可观看');
  el('roomcode').textContent = code;
  const qr = el('roomqr');
  if(qr && !qr.getAttribute('src')){
    const url = location.origin + '/room/' + code;
    qr.setAttribute('src', '/qr.png?url=' + encodeURIComponent(url));
  }
  const sel = el('join-color');
  if(sel && sel.dataset.filled !== '1'){
    const free = v.free_colors || [];
    sel.innerHTML = '<option value="">自动（坐空位）</option>' +
      free.map(c => '<option value="' + c + '">' + (c === 'BLACK' ? '执黑' : '执白') + '</option>').join('');
    sel.dataset.filled = '1';
  }
  const btn = el('join-btn');
  if(btn){
    btn.disabled = !v.joinable;
    btn.textContent = v.joinable ? '落座' : '席位已满';
  }
  if(!seated){
    try { const n = localStorage.getItem(NAME_KEY); if(n && !el('join-name').value) el('join-name').value = n; } catch (e) {}
  }
}

function renderToolbar(v){
  const can = !!(v.can_move);
  const pass = el('passbtn'), res = el('resignbtn');
  if(pass){ pass.disabled = !can; }
  if(res){ res.disabled = !(v.viewer && v.viewer.seated) || v.game_over; }
  const hint = el('hint');
  if(v.game_over){ hint.textContent = '本局已结束。'; hint.className = 'hintbar'; return; }
  if(!v.viewer || !v.viewer.seated){ hint.textContent = '你还没有落座，可先用上面对局码加入。'; hint.className = 'hintbar'; return; }
  if(v.status === 'waiting'){ hint.textContent = '等待对手进入房间（把对局码发给他）。'; hint.className = 'hintbar'; return; }
  hint.textContent = can ? ('轮到你落子，点击棋盘交叉点。') : ('等待对方（' + colorCn(v.to_play) + '方）落子…');
  hint.className = 'hintbar' + (can ? ' ok' : '');
}

function showOverlay(v){
  el('ov-title').textContent = '终局 · ' + (v.verdict_cn || '');
  const fl = (v.fouls || []).length;
  const lines = [
    '<p>' + (v.player_black || '黑方') + ' ● vs ○ ' + (v.player_white || '白方') + '</p>',
    '<p>' + (v.game_name_cn || '') + ' · 共 ' + v.move_number + ' 手</p>',
    v.resigned ? ('<p>认输方：' + colorCn(v.resigned) + '方（对方获胜）</p>') : '',
    v.first_pass ? ('<p>先停一手（弃权）：' + colorCn(v.first_pass) + '方</p>') : '',
    '<p>犯规 ' + fl + ' 次' +
      (v.foul_counts ? ('（黑 ' + (v.foul_counts.BLACK || 0) + ' / 白 ' + (v.foul_counts.WHITE || 0) + '）') : '') + '</p>',
    '<p class="muted">点击空白处关闭</p>',
  ];
  el('ov-body').innerHTML = lines.filter(Boolean).join('');
  el('overlay').classList.add('show');
}

// ---------------------------------------------------------------- 交互
async function post(url, obj){
  try {
    const r = await fetch(url, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(obj || {})
    });
    let d = {};
    try { d = await r.json(); } catch (e) {}
    return d || {};
  } catch (e) {
    return { error: '网络错误，请检查是否仍连接同一网络' };
  }
}

function afterAction(d){
  if(!d) return;
  if(d.error){ toast(d.error, 'bad'); return; }
  if(d.view) update(d.view);
  else load();
  const o = d.outcome || {};
  if(o.foul) showFoul(o.foul, !!o.loss_by_foul);
  if(d.game_over && d.view) showOverlay(d.view);
}

canvas.addEventListener('click', async (ev) => {
  if(!current || current.game_over) return;
  const N = current.size, W = canvas.width, pad = W * 0.075, step = (W - pad * 2) / (N - 1);
  const rect = canvas.getBoundingClientRect();
  const px = (ev.clientX - rect.left) / rect.width * W, py = (ev.clientY - rect.top) / rect.height * W;
  const x = Math.round((px - pad) / step), y = Math.round((py - pad) / step);
  if(x < 0 || y < 0 || x >= N || y >= N) return;
  if(!current.viewer || !current.viewer.seated){ toast('请先落座再加入对局', 'bad'); return; }
  if(!current.can_move){ toast('还没有轮到你落子', 'bad'); return; }
  const d = await post('/api/room/' + code + '/move', {token, x, y});
  afterAction(d);
});

el('passbtn').onclick = async () => {
  if(!current || current.game_over) return;
  if(!current.can_move){ toast('还没有轮到你', 'bad'); return; }
  if(!confirm('确认停一手（Pass）？')) return;
  afterAction(await post('/api/room/' + code + '/pass', {token}));
};

el('resignbtn').onclick = async () => {
  if(!current || current.game_over) return;
  if(!current.viewer || !current.viewer.seated){ toast('请先落座', 'bad'); return; }
  if(!confirm('确认认输？本局将判对方获胜。')) return;
  afterAction(await post('/api/room/' + code + '/resign', {token}));
};

el('passlogbtn').onclick = () => {
  if(!current){ toast('尚无对局数据', 'bad'); return; }
  showPassLog(current);
};

el('join-btn').onclick = async () => {
  const name = (el('join-name').value || '').trim() || '玩家';
  const color = el('join-color').value || null;
  el('join-btn').disabled = true;
  const d = await post('/api/room/' + code + '/join', {name, color});
  el('join-btn').disabled = false;
  if(d.error || !d.seat){ toast('加入失败：' + (d.error || '未知错误'), 'bad'); return; }
  token = d.seat.token;
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(NAME_KEY, d.seat.name);
    localStorage.setItem('arena_player_name', d.seat.name);
  } catch (e) {}
  toast('已落座（' + (d.seat.color_cn || '') + '方）', 'ok');
  if(d.view) update(d.view);
  else load();
};

el('overlay').addEventListener('click', (e) => {
  if(e.target === el('overlay')) el('overlay').classList.remove('show');
});
el('againbtn').onclick = () => { location.href = '/play'; };
el('backbtn').onclick = () => { location.href = '/play'; };

// ---------------------------------------------------------------- 载入 / SSE
async function load(){
  try {
    const url = '/api/room/' + code + (token ? ('?token=' + encodeURIComponent(token)) : '');
    const r = await fetch(url);
    if(r.status === 404){
      el('hint').textContent = '对局不存在或已关闭：' + code;
      el('hint').className = 'hintbar bad';
      return;
    }
    const v = await r.json();
    update(v);
  } catch (e) {}
}

let es = null;
function connect(tableNo){
  if(es) es.close();
  es = new EventSource('/events?table=' + tableNo);
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      if(ev.type === 'state' && ev.table === tableNo){ load(); }
      else if(ev.type === 'snapshot'){ /* 首帧由 load() 处理 */ }
    } catch (err) {}
  };
  es.onerror = () => { /* EventSource 自动重连 */ };
}

(async function boot(){
  await load();
  if(current && current.table) connect(current.table);
})();
setInterval(load, 8000);