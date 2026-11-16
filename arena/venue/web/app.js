// 大厅：桌位列表 + SSE 实时刷新
const gridEl = document.getElementById('tables');

function pct(x){ return (Math.round((x||0)*1000)/10).toFixed(1) + '%'; }

function badgeCls(s){ return s === 'playing' ? 'badge playing' : 'badge'; }
function statusCn(s){ return {playing:'进行中', waiting:'等待', finished:'已结束'}[s] || s; }

function makeCard(t){
  const a = document.createElement('a');
  a.className = 'card';
  a.href = '/table/' + t.table;
  const bw = t.black_winrate || 0.5;
  a.innerHTML = `
    <div class="no">${t.table} 号桌 <span class="${badgeCls(t.status)}">${statusCn(t.status)}</span></div>
    <div class="meta">${t.game_name_cn} · 第 ${t.move_number} 手</div>
    <div class="players"><span>● ${t.player_black}</span><span>○ ${t.player_white}</span></div>
    <div class="bar"><i style="width:${(bw*100).toFixed(1)}%"></i></div>
    <div class="barlabel"><span>黑 ${pct(bw)}</span><span>白 ${pct(1-bw)}</span></div>
    <div class="meta">${t.verdict_cn || ''}</div>`;
  return a;
}

function render(list){
  gridEl.innerHTML = '';
  if(!list || !list.length){ gridEl.textContent = '暂无棋桌'; return; }
  list.forEach(t => gridEl.appendChild(makeCard(t)));
}

async function load(){
  try{
    const r = await fetch('/api/tables');
    const d = await r.json();
    render(d.tables);
  }catch(e){}
}

function connect(){
  const es = new EventSource('/events');
  es.onmessage = (e) => {
    try{
      const ev = JSON.parse(e.data);
      if(ev.type === 'snapshot'){ render((ev.payload && ev.payload.tables) || []); }
      else { load(); }
    }catch(_){}
  };
}

load();
connect();
setInterval(load, 8000);