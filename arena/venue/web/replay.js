// 棋谱回放：逐手播放 / 拖动进度 / 键盘控制 / 手数列表跳转 / 双方胜率实时显示
const NAME = decodeURIComponent((location.pathname.split('/').filter(Boolean).pop()) || '');
const canvas = document.getElementById('board');
const curve = document.getElementById('wrcurve');
const footEl = document.getElementById('foot');
const listEl = document.getElementById('movelist');
const scrub = document.getElementById('scrub');
const progEl = document.getElementById('progress');
const playBtn = document.getElementById('play');

let data = null;       // 回放数据
let idx = 0;           // 0 = 空盘，N = 第 N 手
let timer = null;
let EVAL = null;       // 胜率数组，EVAL[i] 对应第 i 手之后的局面（i=0 为空盘）
let evalSource = '';   // 'heuristic' | 'katago'
let evalDone = false;

function el(id){ return document.getElementById(id); }
function setText(id, t){ const e = document.getElementById(id); if(e) e.textContent = t; }
function coordStr(x, y, size){ return SABoard.coordStr(x, y, size); }
function colorCn(c){ return c === 'BLACK' ? '黑' : c === 'WHITE' ? '白' : '-'; }
function resultCn(r){
  return r === 'B+R' ? '黑中盘胜' : r === 'W+R' ? '白中盘胜' :
    r === 'B+' ? '黑胜' : r === 'W+' ? '白胜' : r === '0' ? '和棋' : (r || '-');
}
function evalLabel(src){
  return src === 'katago' ? '胜率：KataGo 引擎' : '胜率：内置评估（未接入引擎）';
}

function frameAt(i){ return i <= 0 ? null : data.moves[i - 1]; }

function render(){
  const fr = frameAt(idx);
  const board = fr ? fr.board : data.initial_board;
  const lm = fr ? { x: fr.x, y: fr.y, color: fr.color, move_no: fr.no, is_pass: fr.pass } : null;
  SABoard.draw(canvas, {
    size: data.size, board: board, game_type: data.game_type, last_move: lm
  }, { coord: true, number: true });

  if(fr){
    footEl.textContent = '第 ' + fr.no + ' 手：' + colorCn(fr.color) + '方 ' +
      (fr.pass ? '停一手 (Pass)' : coordStr(fr.x, fr.y, data.size));
  } else {
    footEl.textContent = '开局（空盘）';
  }

  const caps = (fr ? fr.captures : data.captures) || { BLACK: 0, WHITE: 0 };
  el('cur').textContent = idx + ' / ' + data.move_count;
  el('cap').textContent = (caps.BLACK || 0) + ' / ' + (caps.WHITE || 0);
  scrub.value = String(idx);
  progEl.textContent = idx + ' / ' + data.move_count;

  el('first').disabled = idx === 0;
  el('prev').disabled = idx === 0;
  el('next').disabled = idx >= data.move_count;
  el('last').disabled = idx >= data.move_count;

  updateWinrate();
  highlightMove();
}

function highlightMove(){
  const cur = listEl.querySelector('.mv.active');
  if(cur) cur.classList.remove('active');
  if(idx > 0){
    const node = listEl.querySelector('.mv[data-i="' + idx + '"]');
    if(node){
      node.classList.add('active');
      if(node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
    }
  }
}

function go(i){
  idx = Math.max(0, Math.min(data.move_count, i));
  render();
}

// ------------------------------------------------------------ 胜率
function updateWinrate(){
  const bn = el('wr-black'), wn = el('wr-white');
  const bs = el('wr-black-bar'), ws = el('wr-white-bar');
  const p = (EVAL && idx < EVAL.length) ? EVAL[idx] : null;
  if(p){
    const b = Math.round(p.black * 1000) / 10, w = Math.round(p.white * 1000) / 10;
    bn.textContent = b.toFixed(1) + '%';
    wn.textContent = w.toFixed(1) + '%';
    bs.style.width = b + '%';
    ws.style.width = w + '%';
  } else if(!evalDone){
    bn.textContent = '分析中…'; wn.textContent = '';
    bs.style.width = '50%'; ws.style.width = '50%';
  } else {
    bn.textContent = '--'; wn.textContent = '--';
    bs.style.width = '50%'; ws.style.width = '50%';
  }
  drawCurve();
}

function drawCurve(){
  if(!curve || !data) return;
  const ctx = curve.getContext('2d');
  const W = curve.width, H = curve.height;
  const padL = 10, padR = 10, padT = 12, padB = 14;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const n = Math.max(1, data.move_count);
  const xOf = i => padL + innerW * (i / n);
  const yOf = wr => padT + innerH * (1 - wr);

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#121a2b'; ctx.fillRect(0, 0, W, H);

  // 50% 中线
  ctx.strokeStyle = 'rgba(147,161,189,.35)'; ctx.lineWidth = 1;
  ctx.setLineDash([5, 5]);
  ctx.beginPath(); ctx.moveTo(padL, yOf(0.5)); ctx.lineTo(W - padR, yOf(0.5)); ctx.stroke();
  ctx.setLineDash([]);

  const pts = EVAL || [];
  if(pts.length){
    // 阴影面积（曲线与中线之间）
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(pts[0].black));
    for(let i = 1; i < pts.length; i++) ctx.lineTo(xOf(i), yOf(pts[i].black));
    ctx.lineTo(xOf(pts.length - 1), yOf(0.5));
    ctx.lineTo(xOf(0), yOf(0.5));
    ctx.closePath();
    const g = ctx.createLinearGradient(0, padT, 0, padT + innerH);
    g.addColorStop(0, 'rgba(76,141,255,.55)');
    g.addColorStop(1, 'rgba(76,141,255,.05)');
    ctx.fillStyle = g; ctx.fill();

    // 折线
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(pts[0].black));
    for(let i = 1; i < pts.length; i++) ctx.lineTo(xOf(i), yOf(pts[i].black));
    if(pts.length === 1) ctx.lineTo(xOf(0) + 0.5, yOf(pts[0].black));
    ctx.strokeStyle = '#4c8dff'; ctx.lineWidth = 2; ctx.stroke();

    // 当前手标记
    const ci = Math.min(idx, pts.length - 1);
    const cx = xOf(ci), cy = yOf(pts[ci].black);
    ctx.strokeStyle = 'rgba(232,238,252,.45)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx, padT); ctx.lineTo(cx, H - padB); ctx.stroke();
    ctx.beginPath(); ctx.fillStyle = '#ffd166'; ctx.arc(cx, cy, 3.2, 0, 7); ctx.fill();
  } else {
    ctx.fillStyle = '#93a1bd'; ctx.font = '13px system-ui';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(evalDone ? '本局暂无胜率数据' : '胜率分析中…', W / 2, H / 2);
  }

  // 纵轴提示（黑方视角）
  ctx.fillStyle = 'rgba(147,161,189,.7)'; ctx.font = '11px system-ui';
  ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText('黑 100%', padL + 2, 1);
  ctx.textBaseline = 'bottom';
  ctx.fillText('黑 0%', padL + 2, H - 1);
}

if(curve){
  curve.addEventListener('click', e => {
    if(!data || data.move_count <= 0) return;
    const rect = curve.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / Math.max(1, rect.width);
    const frac = Math.min(1, Math.max(0, (rel - 0.014) / (1 - 0.028)));
    stopPlay();
    go(Math.round(frac * data.move_count));
  });
}

// ------------------------------------------------------------ 胜率加载
async function getJson(url){
  try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch(e){ return null; }
}
function evalUrl(to){
  const base = '/api/records/' + encodeURIComponent(NAME) + '/eval';
  return (to === null || to === undefined) ? base : (base + '?to=' + to);
}

async function loadEval(){
  setText('evalsrc', '分析中…');
  const probe = await getJson(evalUrl(0));
  if(!probe){ evalDone = true; setText('evalsrc', '胜率不可用'); updateWinrate(); return; }
  evalSource = probe.source || '';
  EVAL = probe.points || [];
  evalDone = !!probe.done;
  const total = probe.total || 0;
  setText('evalsrc', evalDone ? evalLabel(evalSource) : ('分析中… ' + Math.max(0, EVAL.length - 1) + '/' + total));
  updateWinrate();
  if(total <= 0) return;

  // 内置评估瞬时完成，一次拿全；真实引擎较慢，分小块增量拉取
  const chunk = (evalSource === 'katago') ? 5 : total;   // 引擎分析较慢：小块拉取，进度更平滑
  for(let from = EVAL.length || 1; from <= total; from += chunk){
    const upto = Math.min(total, from + chunk - 1);
    const r = await getJson(evalUrl(upto));
    if(!r) break;
    EVAL = r.points || EVAL;
    evalDone = !!r.done;
    setText('evalsrc', evalDone ? evalLabel(evalSource)
      : ('分析中… ' + Math.max(0, EVAL.length - 1) + '/' + total));
    updateWinrate();
    if(evalDone) break;
  }
  if(!evalDone){ evalDone = true; setText('evalsrc', evalLabel(evalSource)); updateWinrate(); }
}

// ------------------------------------------------------------ 自动播放
function stopPlay(){
  if(timer){ clearInterval(timer); timer = null; }
  playBtn.textContent = '\u25b6 \u64ad\u653e';
  playBtn.classList.add('primary');
}
function startPlay(){
  if(idx >= data.move_count) idx = 0;
  timer = setInterval(() => {
    if(idx >= data.move_count){ stopPlay(); return; }
    go(idx + 1);
  }, parseInt(el('speed').value, 10) || 700);
  playBtn.textContent = '\u23f8 \u6682\u505c';
}

// ------------------------------------------------------------ 事件
el('first').onclick = () => { stopPlay(); go(0); };
el('prev').onclick  = () => { stopPlay(); go(idx - 1); };
el('next').onclick  = () => { stopPlay(); go(idx + 1); };
el('last').onclick  = () => { stopPlay(); go(data.move_count); };
playBtn.onclick = () => { timer ? stopPlay() : startPlay(); };
el('speed').onchange = () => { if(timer){ stopPlay(); startPlay(); } };
scrub.addEventListener('input', () => { stopPlay(); go(parseInt(scrub.value, 10) || 0); });

document.addEventListener('keydown', (e) => {
  if(e.key === 'ArrowLeft'){ stopPlay(); go(idx - 1); e.preventDefault(); }
  else if(e.key === 'ArrowRight'){ stopPlay(); go(idx + 1); e.preventDefault(); }
  else if(e.key === ' '){ e.preventDefault(); timer ? stopPlay() : startPlay(); }
  else if(e.key === 'Home'){ stopPlay(); go(0); }
  else if(e.key === 'End'){ stopPlay(); go(data.move_count); }
});

function buildMoveList(){
  listEl.innerHTML = '';
  if(!data.move_count){ listEl.textContent = '本局没有落子记录。'; return; }
  data.moves.forEach(m => {
    const b = document.createElement('button');
    b.className = 'mv';
    b.dataset.i = String(m.no);
    b.innerHTML = '<span class="mvi">' + m.no + '</span>' +
      '<span class="mvc ' + (m.color === 'BLACK' ? 'b' : 'w') + '">' + colorCn(m.color) + '</span>' +
      '<span class="mvp">' + (m.pass ? 'pass' : coordStr(m.x, m.y, data.size)) + '</span>';
    b.onclick = () => { stopPlay(); go(m.no); };
    listEl.appendChild(b);
  });
}

function boot(){
  el('title').textContent = '棋谱回放 · ' + (data.code || '');
  document.title = '棋谱回放 ' + (data.code || '') + ' · 智慧棋赛';
  el('gt').textContent = data.game_name_cn + ' ' + data.size + ' 路';
  el('res').textContent = resultCn(data.result);
  el('black').textContent = data.black || '黑方';
  el('white').textContent = data.white || '白方';
  el('dl').href = data.record_url || ('/api/records/' + encodeURIComponent(NAME));
  el('dl').setAttribute('download', NAME);
  el('movesub').textContent = (data.date || '') + ' · 共 ' + data.move_count + ' 手' +
    (data.komi ? ' · 贴目 ' + data.komi : '');
  el('comment').textContent = data.comment || '';
  scrub.max = String(data.move_count);
  buildMoveList();
  go(0);
}

async function load(){
  try {
    const r = await fetch('/api/records/' + encodeURIComponent(NAME) + '/replay');
    if(!r.ok){ el('foot').textContent = '棋谱不存在或已删除。'; el('movesub').textContent = NAME;
      evalDone = true; updateWinrate(); return; }
    data = await r.json();
    boot();
    loadEval();
  } catch (e) {
    el('foot').textContent = '回放数据加载失败。';
    evalDone = true; updateWinrate();
  }
}

load();