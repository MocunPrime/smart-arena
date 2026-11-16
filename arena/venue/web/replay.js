// 棋谱回放：逐手播放 / 拖动进度 / 键盘控制 / 手数列表跳转
const NAME = decodeURIComponent((location.pathname.split('/').filter(Boolean).pop()) || '');
const canvas = document.getElementById('board');
const footEl = document.getElementById('foot');
const listEl = document.getElementById('movelist');
const scrub = document.getElementById('scrub');
const progEl = document.getElementById('progress');
const playBtn = document.getElementById('play');

let data = null;       // 回放数据
let idx = 0;           // 0 = 空盘，N = 第 N 手
let timer = null;

function el(id){ return document.getElementById(id); }
function coordStr(x, y, size){ return SABoard.coordStr(x, y, size); }
function colorCn(c){ return c === 'BLACK' ? '黑' : c === 'WHITE' ? '白' : '-'; }
function resultCn(r){
  return r === 'B+R' ? '黑中盘胜' : r === 'W+R' ? '白中盘胜' :
    r === 'B+' ? '黑胜' : r === 'W+' ? '白胜' : r === '0' ? '和棋' : (r || '-');
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

// ---- 自动播放 ----
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

// ---- 事件 ----
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
    if(!r.ok){ el('foot').textContent = '棋谱不存在或已删除。'; el('movesub').textContent = NAME; return; }
    data = await r.json();
    boot();
  } catch (e) {
    el('foot').textContent = '回放数据加载失败。';
  }
}

load();
