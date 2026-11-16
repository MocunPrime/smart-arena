// 死活题改卷页：选难度做题 + 逐手胜率 + 连续做对判定 + 记录
const COL = 'ABCDEFGHJKLMNOPQRST';        // GTP 习惯：跳过 I
const canvas = document.getElementById('board');
const ctx = canvas.getContext('2d');

function el(id){ return document.getElementById(id); }
function pct(x){ return (x === null || x === undefined)
  ? '--' : (Math.round(x * 1000) / 10).toFixed(1) + '%'; }
function colorCn(c){ return c === 'BLACK' ? '黑' : (c === 'WHITE' ? '白' : '-'); }
function coordStr(c, size){ return COL[c[0]] + (size - c[1]); }

let problems = [];       // 题库（不含解答）
let current = null;      // 当前做题会话视图

// ---------------------------------------------------------------- 题库
async function getJson(url){
  try { const r = await fetch(url); return await r.json(); } catch (e) { return {}; }
}

async function loadProblems(){
  const d = await getJson('/api/study/problems');
  problems = (d && d.problems) || [];
  const diffSel = el('f-difficulty');
  const diffs = [];
  problems.forEach(p => { if(p.difficulty && !diffs.includes(p.difficulty)) diffs.push(p.difficulty); });
  diffSel.innerHTML = '<option value="">全部难度</option>' +
    diffs.map(x => '<option value="' + x + '">' + x + '</option>').join('');
  fillProblemOptions();
}

function fillProblemOptions(){
  const diff = el('f-difficulty').value;
  const list = problems.filter(p => !diff || p.difficulty === diff);
  el('f-problem').innerHTML = list.map(p =>
    '<option value="' + p.id + '">' + p.difficulty + ' · ' + p.name +
    '（' + p.mo_count + ' 手）</option>').join('');
  hint('pick-hint', list.length ? ('共 ' + list.length + ' 道题可选。') : '该难度暂无题目。');
}

// ---------------------------------------------------------------- 棋盘
function drawBoard(v){
  const N = v.size, W = canvas.width, pad = W * 0.1;
  const step = (W - pad * 2) / (N - 1);
  ctx.clearRect(0, 0, W, W);
  ctx.fillStyle = '#e8c892'; ctx.fillRect(0, 0, W, W);
  ctx.strokeStyle = '#5a4326'; ctx.lineWidth = 1.3;
  for(let i = 0; i < N; i++){
    const p = pad + i * step;
    ctx.beginPath(); ctx.moveTo(pad, p); ctx.lineTo(W - pad, p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p, pad); ctx.lineTo(p, W - pad); ctx.stroke();
  }
  // 星位
  ctx.fillStyle = '#3a2c17';
  let pts = [];
  if(N >= 13){ const c = (N - 1) / 2, off = 3;
    for(const x of [off, c, N - 1 - off]) for(const y of [off, c, N - 1 - off]) pts.push([x, y]);
  } else { const c = (N - 1) / 2; pts = [[c, c]]; }
  for(const [x, y] of pts){
    ctx.beginPath(); ctx.arc(pad + x * step, pad + y * step, Math.max(2, step * 0.09), 0, 7); ctx.fill();
  }
  // 坐标
  ctx.fillStyle = '#8a7444'; ctx.font = Math.max(10, step * 0.34) + 'px system-ui';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for(let i = 0; i < N; i++){
    ctx.fillText(COL[i], pad + i * step, pad * 0.5);
    ctx.fillText(String(N - i), pad * 0.5, pad + i * step);
  }
  // 目标（要被提掉的白棋）
  if(Array.isArray(v.target)){
    const [tx, ty] = v.target;
    ctx.save();
    ctx.strokeStyle = '#d43b3b'; ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.arc(pad + tx * step, pad + ty * step, step * 0.62, 0, 7); ctx.stroke();
    ctx.restore();
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
  // 最后一手
  const lm = v.last_move;
  if(lm && lm.x !== null && lm.x !== undefined){
    const cx = pad + lm.x * step, cy = pad + lm.y * step;
    ctx.beginPath(); ctx.strokeStyle = '#1a7f37'; ctx.lineWidth = 3.2;
    ctx.arc(cx, cy, R * 0.62, 0, 7); ctx.stroke();
    el('boardfoot').textContent = '第 ' + lm.move_no + ' 手：' + colorCn(lm.color) +
      '方 ' + coordStr([lm.x, lm.y], N);
  } else {
    el('boardfoot').textContent = '轮到' + colorCn(v.to_play) + '方落子';
  }
}

// ---------------------------------------------------------------- 提示 / 弹窗
let toastTimer = null;
function toast(text, cls){
  const box = el('toast');
  box.textContent = text;
  box.className = 'toast show' + (cls ? ' ' + cls : '');
  if(toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = 'toast'; }, 2600);
}
function hint(id, text, cls){
  const box = el(id);
  box.textContent = text || '';
  box.className = 'hintbar' + (cls ? ' ' + cls : '');
}

// ---------------------------------------------------------------- 渲染
function render(v){
  if(!v || !v.size) return;
  current = v;
  el('difficulty').textContent = v.difficulty;
  document.title = v.name + ' · 死活题改卷';
  el('s-name').textContent = v.difficulty + ' · ' + v.name;
  el('s-streak').textContent = v.streak + ' / ' + v.streak_needed;
  el('s-winrate').textContent = pct(v.last_winrate);
  el('s-wrong').textContent = v.wrong_count;
  drawBoard(v);

  const h = el('hint');
  h.textContent = v.message || '';
  h.className = 'hintbar ' + (v.solved ? 'ok' : (v.finished ? 'bad' : ''));

  // 本次记录
  const hp = el('historypanel');
  if(v.history && v.history.length){
    hp.hidden = false;
    el('hist-count').textContent = '共 ' + v.history.length + ' 手';
    el('history').innerHTML = v.history.map(m => {
      const who = m.side === 'engine' ? '引擎' : '你';
      const res = m.side === 'engine' ? '自动应手'
        : (m.correct ? '✔ 胜率 ' + pct(m.winrate) : '✘ 胜率 ' + pct(m.winrate));
      return '<div class="f">' + who + ' · ' + colorCn(m.color) + '方 ' +
        coordStr([m.x, m.y], v.size) + ' · ' + res + '</div>';
    }).join('');
  } else { hp.hidden = true; }

  el('hintbtn').disabled = !v.hint;
  if(v.solved || v.finished) showResult(v);
}

function showResult(v){
  el('ov-title').textContent = v.solved ? '✔ 做对了' : '本题结束';
  const lines = [
    '<p>' + v.difficulty + ' · ' + v.name + '</p>',
    '<p>' + (v.message || '') + '</p>',
    '<p>连续做对 <b>' + v.streak + '</b> / ' + v.streak_needed +
      ' 手（阈值 ' + pct(v.threshold) + '）</p>',
    '<p>做错 <b>' + v.wrong_count + '</b> 次</p>',
    '<p class="muted">胜率来源：' + (v.winrate_source || '参考解答模型') + '</p>',
  ];
  el('ov-body').innerHTML = lines.join('');
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
  } catch (e) { return { error: '网络错误' }; }
}

function afterMove(d){
  if(!d) return;
  if(d.error){ toast(d.error, 'bad'); return; }
  if(d.solved){ toast('做对了！', 'ok'); }
  render(d);
}

el('start-btn').onclick = async () => {
  const id = el('f-problem').value;
  if(!id){ toast('请先选择题目', 'bad'); return; }
  const btn = el('start-btn');
  btn.disabled = true;
  const d = await post('/api/study/start', {id});
  btn.disabled = false;
  if(d.error){ toast('开始失败：' + d.error, 'bad'); return; }
  hint('pick-hint', '已开始：' + d.name, 'ok');
  render(d);
};

canvas.addEventListener('click', async (ev) => {
  if(!current || current.solved || current.finished) return;
  if(current.to_play !== current.solver){ toast('请等引擎应手后再落子', 'bad'); return; }
  const N = current.size, W = canvas.width, pad = W * 0.1, step = (W - pad * 2) / (N - 1);
  const rect = canvas.getBoundingClientRect();
  const px = (ev.clientX - rect.left) / rect.width * W;
  const py = (ev.clientY - rect.top) / rect.height * W;
  const x = Math.round((px - pad) / step), y = Math.round((py - pad) / step);
  if(x < 0 || y < 0 || x >= N || y >= N) return;
  afterMove(await post('/api/study/' + current.sid + '/move', {x, y}));
});

el('resetbtn').onclick = async () => {
  if(!current){ toast('还没开始做题', 'bad'); return; }
  const d = await post('/api/study/' + current.sid + '/reset', {});
  if(d.error){ toast(d.error, 'bad'); return; }
  el('overlay').classList.remove('show');
  render(d);
  toast('已重做本题', 'ok');
};

el('resetbtn2').onclick = () => el('resetbtn').click();
el('hintbtn').onclick = () => {
  if(!current || !current.hint) return;
  toast(current.hint);
};
el('againbtn').onclick = () => {
  el('overlay').classList.remove('show');
  el('f-problem').focus();
  window.scrollTo({top:0, behavior:'smooth'});
};
el('overlay').addEventListener('click', (e) => {
  if(e.target === el('overlay')) el('overlay').classList.remove('show');
});
el('f-difficulty').onchange = fillProblemOptions;

// ---------------------------------------------------------------- 启动
loadProblems();
