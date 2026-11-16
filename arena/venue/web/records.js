// 棋谱存档：列表 + 棋种筛选 + 搜索 + 终局缩略图（懒加载，限并发）
const gridEl = document.getElementById('records');
const countEl = document.getElementById('rec-count');
let ALL = [];
let gtFilter = '';
let query = '';

function gameCn(g){ return {go:'围棋', gomoku:'五子棋', reversi:'翻转棋'}[g] || '对局'; }
function fmtTime(ts){
  if(!ts) return '';
  const d = new Date(ts * 1000);
  const p = n => (n < 10 ? '0' : '') + n;
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
    p(d.getHours()) + ':' + p(d.getMinutes());
}
function resultCn(r){
  return r === 'B+R' ? '黑中盘胜' : r === 'W+R' ? '白中盘胜' :
    r === 'B+' ? '黑胜' : r === 'W+' ? '白胜' : r === '0' ? '和棋' : (r || '-');
}

// ---- 缩略图：限并发拉取终局棋盘并绘制 ----
const queue = [];
let running = 0;
const MAX_CONCURRENT = 4;
function enqueueThumb(job){
  queue.push(job);
  pump();
}
function pump(){
  while(running < MAX_CONCURRENT && queue.length){
    const job = queue.shift();
    running++;
    paintThumb(job).finally(() => { running--; pump(); });
  }
}
async function paintThumb(job){
  try {
    const r = await fetch('/api/records/' + encodeURIComponent(job.rec.name) + '/replay?frames=0');
    if(!r.ok) return;
    const d = await r.json();
    SABoard.draw(job.canvas, {
      size: d.size, board: d.final_board, game_type: d.game_type, last_move: null
    }, { coord: false, number: false });
  } catch (e) {}
}

// ---- 渲染 ----
function matches(rec){
  if(gtFilter && rec.game_type !== gtFilter) return false;
  if(!query) return true;
  const q = query.toLowerCase();
  return [rec.black, rec.white, rec.code, rec.result, gameCn(rec.game_type)]
    .some(v => String(v == null ? '' : v).toLowerCase().indexOf(q) >= 0);
}

function makeCard(rec){
  const wrap = document.createElement('div');
  wrap.className = 'reccard';

  const a = document.createElement('a');
  a.className = 'rec-main';
  a.href = '/replay/' + encodeURIComponent(rec.name);
  a.title = '点击回放这局棋';

  const cv = document.createElement('canvas');
  cv.width = 168; cv.height = 168; cv.className = 'thumb';
  a.appendChild(cv);

  const body = document.createElement('div');
  body.className = 'recbody';
  body.innerHTML =
    '<div class="recrow"><span class="reccode">' + (rec.code || '----') + '</span>' +
      '<span class="badge">' + gameCn(rec.game_type) + '</span>' +
      '<span class="muted">' + (rec.size_label ? rec.size_label + ' 路' : '') + '</span></div>' +
    '<div class="recplayers"><span>&#9679; ' + (rec.black || '黑方') + '</span>' +
      '<span>&#9675; ' + (rec.white || '白方') + '</span></div>' +
    '<div class="recmeta"><span>' + (rec.date || '') + '</span>' +
      '<span class="res">' + resultCn(rec.result) + '</span></div>' +
    '<div class="muted">' + fmtTime(rec.modified) + '</div>';
  a.appendChild(body);
  wrap.appendChild(a);

  const dl = document.createElement('a');
  dl.className = 'recdl';
  dl.href = rec.download_url || ('/api/records/' + encodeURIComponent(rec.name));
  dl.setAttribute('download', rec.name || '');
  dl.textContent = '下载 SGF';
  wrap.appendChild(dl);

  enqueueThumb({ canvas: cv, rec: rec });
  return wrap;
}

function render(){
  const list = ALL.filter(matches);
  countEl.textContent = list.length ? ('共 ' + list.length + ' 份') : '';
  gridEl.innerHTML = '';
  if(!ALL.length){ gridEl.textContent = '暂无棋谱，对局结束或房间关闭后会自动保存。'; return; }
  if(!list.length){ gridEl.textContent = '没有符合条件的棋谱。'; return; }
  const grid = document.createElement('div');
  grid.className = 'recordgrid-inner';
  list.forEach(rec => grid.appendChild(makeCard(rec)));
  gridEl.appendChild(grid);
}

async function load(){
  try {
    const r = await fetch('/api/records?limit=500');
    const d = await r.json();
    ALL = (d && d.records) || [];
    render();
  } catch (e) {
    gridEl.textContent = '棋谱列表加载失败';
  }
}

// ---- 交互 ----
document.querySelectorAll('.chip').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    gtFilter = btn.dataset.gt || '';
    render();
  });
});
const qEl = document.getElementById('q');
qEl.addEventListener('input', () => { query = qEl.value.trim(); render(); });

load();
setInterval(load, 15000);
