// 首页：拉取实时统计（房间数 / 棋谱数）
async function getJson(url){
  try { const r = await fetch(url); return await r.json(); } catch (e) { return {}; }
}
function setText(id, text){ const el = document.getElementById(id); if(el) el.textContent = text; }

(async function(){
  const rooms = await getJson('/api/rooms');
  setText('st-rooms', String(((rooms && rooms.rooms) || []).length));

  const recs = await getJson('/api/records?limit=10000');
  setText('st-records', String(((recs && recs.records) || []).length));
})();
