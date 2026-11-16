"""智慧赛场 HTTP 服务。

一个零依赖（仅需 segno 生成二维码）的局域网服务：
* ``/``               大厅：桌号列表 + 扫码入口（二维码）
* ``/table/<n>``      单桌实时棋盘（家长手机观看）
* ``/api/tables``     桌位快照（JSON）
* ``/api/table/<n>``  单桌状态（JSON）
* ``/events``         SSE 实时事件流（可按 table 过滤）
* ``/qr.svg`` ``/qr.png``  服务地址二维码
* ``/api/play``       落子（供裁判端/演示 POST）

设计目标：场馆内主机开热点 -> 家长连 WiFi -> 手机浏览，无需外网、无需手机卡。
"""
from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse, parse_qs

from ..model import Color, GameType
from ..tournament import EventBus, Tournament
from .qr import qr_png_data_uri, qr_svg

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
}


def local_ip() -> str:
    """获取本机在局域网中的地址（用于生成二维码/播报地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class VenueServer:
    def __init__(self, tournament: Tournament, host: str = "0.0.0.0", port: int = 8000,
                 advertised_host: Optional[str] = None):
        self.tournament = tournament
        self.bus: EventBus = tournament.bus
        self.host = host
        self.port = port
        self.advertised_host = advertised_host
        self.httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ URL / 二维码
    @property
    def base_url(self) -> str:
        host = self.advertised_host or local_ip()
        shown = host if host != "0.0.0.0" else local_ip()
        return f"http://{shown}:{self.port}/"

    def table_url(self, no: int) -> str:
        return f"{self.base_url}table/{no}"

    # ------------------------------------------------------------------ 生命周期
    def build(self) -> ThreadingHTTPServer:
        handler = _make_handler(self)
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]   # port==0 时回填真实端口
        return self.httpd

    def start_background(self) -> None:
        self.build()
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        self.build()
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def _make_handler(venue: "VenueServer"):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SmartArena/0.1"

        def log_message(self, fmt, *args):     # 静默日志
            pass

        # ---------------------------------------------------------- 工具
        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, body: bytes, ctype: str, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, name: str):
            path = os.path.join(WEB_DIR, name)
            if not os.path.isfile(path):
                self._json({"error": "not found", "path": name}, 404)
                return
            ext = os.path.splitext(name)[1].lower()
            with open(path, "rb") as f:
                body = f.read()
            if ext == ".html":
                body = self._render_html(body.decode("utf-8")).encode("utf-8")
            self._bytes(body, MIME.get(ext, "application/octet-stream"))

        def _render_html(self, text: str) -> str:
            qr = qr_png_data_uri(venue.base_url, scale=6) or ""
            return (text
                    .replace("{{BASE_URL}}", venue.base_url)
                    .replace("{{QR_DATA_URI}}", qr)
                    .replace("{{TABLE_COUNT}}", str(len(venue.tournament.tables))))

        # ---------------------------------------------------------- GET
        def do_GET(self):
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query)
            if path in ("/", "/index.html"):
                return self._file("index.html")
            if path.startswith("/table/"):
                return self._file("table.html")
            if path == "/healthz":
                return self._json({"ok": True, "time": time.time()})
            if path == "/api/tables":
                return self._json(venue.tournament.snapshot())
            if path.startswith("/api/table/"):
                no = _as_int(path.rsplit("/", 1)[-1])
                view = venue.tournament.table_view(no) if no is not None else None
                return self._json(view or {"error": "no such table"}, 200 if view else 404)
            if path == "/events":
                no = _as_int(qs.get("table", [None])[0])
                return self._sse(no)
            if path == "/qr.svg":
                svg = qr_svg(qs.get("url", [venue.base_url])[0])
                if svg is None:
                    return self._json({"error": "segno 未安装"}, 500)
                return self._bytes(svg.encode("utf-8"), "image/svg+xml")
            if path == "/qr.png":
                uri = qr_png_data_uri(qs.get("url", [venue.base_url])[0])
                if uri is None:
                    return self._json({"error": "segno 未安装"}, 500)
                import base64
                return self._bytes(base64.b64decode(uri.split(",", 1)[1]), "image/png")
            if path.startswith("/static/"):
                return self._file(path[len("/static/"):])
            return self._json({"error": "not found", "path": path}, 404)

        # ---------------------------------------------------------- POST
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._json({"error": "bad json"}, 400)
            path = urlparse(self.path).path
            if path == "/api/play":
                return self._api_play(data)
            if path == "/api/newtable":
                return self._api_newtable(data)
            if path.startswith("/api/table/"):
                return self._api_vote(path, data)
            return self._json({"error": "not found"}, 404)

        def _api_play(self, data):
            no = data.get("table")
            color = (data.get("color") or "BLACK").upper()
            x, y = data.get("x"), data.get("y")
            if data.get("pass"):
                x = y = None
            outcome = venue.tournament.play(no, Color[color], x, y)
            if outcome is None:
                return self._json({"error": "no such table"}, 404)
            return self._json(outcome)

        def _api_newtable(self, data):
            gt = data.get("game_type", "go")
            try:
                game_type = GameType(gt)
            except ValueError:
                return self._json({"error": f"未知棋种 {gt}"}, 400)
            no = data.get("table") or (max(venue.tournament.tables or {0: 0}) + 1)
            t = venue.tournament.create_table(
                no, game_type, size=data.get("size"),
                black=data.get("black", "黑方"), white=data.get("white", "白方"),
                label=data.get("label", ""))
            return self._json(t.brief(), 201)

        def _publish_state(self, no):
            t = venue.tournament.get(no)
            if t:
                venue.bus.publish({"type": "state", "table": no,
                                   "payload": t.view(), "ts": time.time()})

        def _api_vote(self, path, data):
            parts = [q for q in path.split("/") if q]        # api/table/<n>/vote/<action>
            if len(parts) < 5 or parts[:2] != ["api", "table"] or parts[3] != "vote":
                return self._json({"error": "not found", "path": path}, 404)
            no = _as_int(parts[2])
            action = parts[4]
            t = venue.tournament.get(no) if no is not None else None
            if not t:
                return self._json({"error": "no such table"}, 404)
            if action == "open":
                color = (data.get("color") or "BLACK").upper()
                cands = data.get("candidates")
                if cands:
                    cands = [(int(c[0]), int(c[1])) for c in cands]
                v = t.begin_vote(Color[color],
                                 timeout_s=float(data.get("timeout_s", 60)),
                                 remind_at_s=float(data.get("remind_at_s", 30)),
                                 candidates=cands)
                if v is None:
                    return self._json({"error": "本桌未挂载团队名册"}, 400)
                self._publish_state(no)
                return self._json({"ok": True, "vote": v.to_dict()})
            if not t.vote:
                return self._json({"error": "无进行中的投票"}, 400)
            if action == "cast":
                try:
                    t.vote.cast(data.get("member"), (int(data.get("x")), int(data.get("y"))),
                                weight=data.get("weight"))
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
                self._publish_state(no)
                return self._json({"ok": True, "vote": t.vote.to_dict()})
            if action == "captain":
                t.vote.captain_choose((int(data.get("x")), int(data.get("y"))), by=data.get("by"))
                self._publish_state(no)
                return self._json({"ok": True, "vote": t.vote.to_dict()})
            if action == "resolve":
                outcome, decision = t.apply_vote()
                if outcome and outcome.accepted:
                    t.record_winrate()
                self._publish_state(no)
                return self._json({"ok": True, "decision": decision,
                                   "outcome": outcome.to_dict() if outcome else None})
            if action == "cancel":
                t.vote = None
                self._publish_state(no)
                return self._json({"ok": True})
            return self._json({"error": f"未知操作 {action}"}, 404)

        # ---------------------------------------------------------- SSE
        def _sse(self, table_no: Optional[int]):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q: "queue.Queue[dict]" = queue.Queue()

            def on_event(ev: dict):
                if table_no is None or ev.get("table") == table_no:
                    q.put(ev)
            venue.bus.subscribe(on_event)
            try:
                # 先推一次当前状态
                snapshot = (venue.tournament.table_view(table_no) if table_no
                            else venue.tournament.snapshot())
                q.put({"type": "snapshot", "table": table_no, "payload": snapshot,
                       "ts": time.time()})
                while True:
                    try:
                        ev = q.get(timeout=15)
                        payload = json.dumps(ev, ensure_ascii=False)
                    except queue.Empty:
                        payload = json.dumps({"type": "ping", "ts": time.time()})
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                venue.bus.unsubscribe(on_event)

    return Handler


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_server(tournament: Tournament, host: str = "0.0.0.0", port: int = 8000,
                 advertised_host: Optional[str] = None) -> VenueServer:
    return VenueServer(tournament, host=host, port=port, advertised_host=advertised_host)