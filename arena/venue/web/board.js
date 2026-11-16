// 共享棋盘绘制：对弈页 / 棋谱回放页 / 棋谱缩略图共用同一套画法。
// 用法：SABoard.draw(canvas, {size, board, game_type, last_move}, {coord:true, number:true})
(function(){
  var COL = 'ABCDEFGHJKLMNOPQRST';   // GTP 习惯：跳过 I

  function coordStr(x, y, size){ return COL[x] + (size - y); }

  function draw(canvas, view, opts){
    if(!canvas || !view) return;
    opts = opts || {};
    var ctx = canvas.getContext('2d');
    var N = view.size || 19;
    var W = canvas.width;
    var pad = W * 0.075;
    var step = (W - pad * 2) / (N - 1);
    var showCoord = opts.coord !== false;
    var showNumber = opts.number !== false;

    ctx.clearRect(0, 0, W, W);
    ctx.fillStyle = '#e8c892'; ctx.fillRect(0, 0, W, W);

    // 网格
    ctx.strokeStyle = '#5a4326';
    ctx.lineWidth = Math.max(1, W / 520);
    for(var i = 0; i < N; i++){
      var p = pad + i * step;
      ctx.beginPath(); ctx.moveTo(pad, p); ctx.lineTo(W - pad, p); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p, pad); ctx.lineTo(p, W - pad); ctx.stroke();
    }

    // 星位
    if(view.game_type === 'go' || view.game_type === 'gomoku'){
      var pts = [];
      if(view.game_type === 'go'){
        var c = (N - 1) / 2, off = (N >= 13) ? 3 : 0;
        var xs = (N >= 13) ? [off, c, N - 1 - off] : [c];
        var ys = (N >= 13) ? [off, c, N - 1 - off] : [c];
        for(var xi = 0; xi < xs.length; xi++)
          for(var yi = 0; yi < ys.length; yi++) pts.push([xs[xi], ys[yi]]);
      } else {
        pts = [[(N - 1) / 2, (N - 1) / 2]];
      }
      ctx.fillStyle = '#3a2c17';
      for(var k = 0; k < pts.length; k++){
        ctx.beginPath();
        ctx.arc(pad + pts[k][0] * step, pad + pts[k][1] * step, Math.max(1.5, step * 0.085), 0, 7);
        ctx.fill();
      }
    }

    // 坐标
    if(showCoord){
      ctx.fillStyle = '#8a7444';
      ctx.font = Math.max(8, step * 0.32) + 'px system-ui';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for(var a = 0; a < N; a++){
        ctx.fillText(COL[a], pad + a * step, pad * 0.48);
        ctx.fillText(String(N - a), pad * 0.48, pad + a * step);
      }
    }

    // 棋子
    var R = step * 0.46;
    var board = view.board || [];
    for(var y = 0; y < N; y++){
      var row = board[y] || [];
      for(var x = 0; x < N; x++){
        var v = row[x];
        if(!v) continue;
        var cx = pad + x * step, cy = pad + y * step;
        var g = ctx.createRadialGradient(cx - R / 3, cy - R / 3, R / 6, cx, cy, R);
        if(v === 1){ g.addColorStop(0, '#525866'); g.addColorStop(1, '#0b0d12'); }
        else { g.addColorStop(0, '#ffffff'); g.addColorStop(1, '#cfd6e4'); }
        ctx.beginPath(); ctx.fillStyle = g; ctx.arc(cx, cy, R, 0, 7); ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,.25)'; ctx.lineWidth = 1; ctx.stroke();
      }
    }

    // 最后一手标记
    var lm = view.last_move;
    if(lm && !lm.is_pass && lm.x !== null && lm.x !== undefined && lm.y !== null && lm.y !== undefined){
      var lx = pad + lm.x * step, ly = pad + lm.y * step;
      ctx.beginPath(); ctx.strokeStyle = '#ff4d4d';
      ctx.lineWidth = Math.max(1.6, W / 220);
      ctx.arc(lx, ly, R * 0.62, 0, 7); ctx.stroke();
      if(showNumber && lm.move_no){
        ctx.fillStyle = (lm.color === 'BLACK') ? '#fff' : '#111';
        ctx.font = 'bold ' + Math.max(9, step * 0.42) + 'px system-ui';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(String(lm.move_no), lx, ly);
      }
    }
  }

  window.SABoard = { draw: draw, coordStr: coordStr, COL: COL };
})();
