"""智慧赛场 HTTP 服务。

一个零依赖（仅需 segno 生成二维码）的局域网服务：
* ``/``               大厅：桌号列表 + 扫码入口（二维码）
* ``/table/<n>``      单桌实时棋盘（家长手机观看）
* ``/api/tables``     桌位快照（JSON）
* ``/api/table/<n>``  单桌状态（JSON）
* ``/events``         SSE 实时事件流（可按 table 过滤）
* ``/qr.svg`` ``/qr.png``  服务地址二维码
* ``/api/play``       落子（供裁判端/演示 POST）

线上对弈（本阶段主功能，**始终启用**）：

* ``/play``                对弈大厅（创建 / 按对局码加入）
* ``/room/<code>``         对弈页（落子 / 停一手 / 认输 / 终局汇总）
* ``/api/rooms``           房间列表（JSON）
* ``/api/room/<code>``     房间状态（JSON；带 ``token`` 时含"我是谁 / 能否走子"）
* ``/api/records``         棋谱存档列表（JSON）
* ``/api/room/<code>/record``  下载该房间最近保存的 SGF 棋谱（GET）
* ``/api/room/create``     创建房间（POST）
* ``/api/room/<code>/join|move|pass|resign``  加入 / 落子 / 停一手 / 认输（POST）

死活题改卷（会议："软件要有改卷功能"，本阶段主功能之一，**始终启用**）：

* ``/study``                     改卷页（按难度选死活题来做）
* ``/api/study/problems``        题库列表（JSON，不含解答）
* ``/api/study/<sid>``           单次做题会话状态（JSON）
* ``/api/study/start``           开始一题（POST ``{id, streak_needed?, threshold?}``）
* ``/api/study/<sid>/move``      人类落子（POST ``{x, y}``，返回本手胜率/是否连对）
* ``/api/study/<sid>/reset``     重做本题（POST）

"智慧赛场"（场馆观赛、多桌导播）按会议阶段性安排**暂时关闭**，由 ``VENUE_ENABLED``
统一控制，详见 ``docs/OPEN-ISSUES.md`` ISSUE-004。

设计目标：同一台主机开热点 -> 棋手手机/电脑连上即可对弈；家长在同一局域网内
扫码观赛（该部分见 ISSUE-004），无需外网、无需手机卡。
"""
from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse, parse_qs

from ..model import Color, GameType
from ..play import PlayError, RoomManager, build_replay, close_reason_text, parse_color
from ..study import QuizError, StudyManager
from ..tournament import EventBus, Tournament
from .qr import qr_png_data_uri, qr_svg

def _web_dir() -> str:
    """定位前端静态资源目录（兼容 PyInstaller 冻结后的单文件运行）。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        cand = os.path.join(bundle, "arena", "venue", "web")
        if os.path.isdir(cand):
            return cand
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


WEB_DIR = _web_dir()

# ---------------------------------------------------------------------------
# "智慧赛场"（场馆观赛 / 多桌导播）总开关。
#
# 会议约定：本阶段先把"线上对弈"做完整，场馆观赛部分暂缓启用，因此这里整体
# 关闭（代码与页面全部保留，等 ISSUE-004 验收后把下面一行改成 True 即可恢复）。
# ---------------------------------------------------------------------------
VENUE_ENABLED = False          # <- 待 docs/OPEN-ISSUES.md ISSUE-004 完成后置为 True

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
                 advertised_host: Optional[str] = None,
                 idle_timeout: Optional[float] = None,
                 records_dir: Optional[str] = None):
        self.tournament = tournament
        self.bus: EventBus = tournament.bus
        room_kwargs = {}
        if idle_timeout is not None:
            room_kwargs["idle_timeout"] = idle_timeout
        if records_dir is not None:
            room_kwargs["records_dir"] = records_dir
        # 线上对弈房间（默认空闲 30 分钟自动关闭，并自动保存棋谱）
        self.rooms = RoomManager(tournament, **room_kwargs)
        self.study = StudyManager()                  # 死活题改卷会话
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
        self.rooms.shutdown()
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
            # -------------------------------------------------- 线上对弈（始终启用）
            if path == "/play":
                return self._file("play.html")
            if path == "/records":
                return self._file("records.html")
            if path.startswith("/replay/"):
                return self._file("replay.html")
            if path.startswith("/room/"):
                return self._file("game.html")
            if path == "/api/rooms":
                return self._json(venue.rooms.snapshot())
            if path == "/api/records":
                limit = _as_int((qs.get("limit") or ["100"])[0]) or 100
                return self._json(venue.rooms.records(limit=limit))
            if path.startswith("/api/records/") and path.endswith("/replay"):
                return self._api_record_replay(path, qs)
            if path.startswith("/api/records/"):
                return self._api_record_file(path)
            if path.startswith("/api/room/") and path.endswith("/record"):
                return self._api_room_record(path)
            if path.startswith("/api/room/"):
                return self._api_room_view(path, qs)
            # -------------------------------------------------- 死活题改卷
            if path == "/study":
                return self._file("study.html")
            if path == "/api/study/problems":
                return self._json(venue.study.list_problems())
            if path.startswith("/api/study/"):
                return self._api_study_view(path)
            if path in ("/", "/index.html"):
                return self._file("hub.html")
            if path == "/venue":
                if not VENUE_ENABLED:
                    return self._venue_disabled()
                return self._file("index.html")
            # ---------------------------------------- 智慧赛场（场馆观赛，暂时关闭）
            if path.startswith("/table/"):
                if not VENUE_ENABLED:
                    return self._venue_disabled()
                return self._file("table.html")
            if path == "/healthz":
                return self._json({"ok": True, "time": time.time()})
            if path == "/api/tables":
                if not VENUE_ENABLED:
                    return self._venue_disabled()
                return self._json(venue.tournament.snapshot())
            if path.startswith("/api/table/"):
                if not VENUE_ENABLED:
                    return self._venue_disabled()
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
            if path == "/api/room/create":
                return self._api_room_create(data)
            if path.startswith("/api/room/"):
                return self._api_room_action(path, data)
            if path == "/api/study/start":
                return self._api_study_start(data)
            if path.startswith("/api/study/"):
                return self._api_study_action(path, data)
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

        # ---------------------------------------------------------- 线上对弈 API
        def _venue_disabled(self):
            return self._json({
                "error": "智慧赛场（场馆观赛）已按阶段安排暂停启用",
                "hint": "见 docs/OPEN-ISSUES.md ISSUE-004；"
                        "启用请把 arena/venue/server.py 的 VENUE_ENABLED 置为 True",
                "play": "/play",
            }, 503)

        def _api_room_view(self, path, qs):
            code = path[len("/api/room/"):].strip("/")
            room = venue.rooms.get(code)
            if room is None:
                return self._json({"error": "对局不存在或已关闭"}, 404)
            if room.closed:
                record = venue.rooms.record_file_path(code)
                return self._json({
                    "code": room.code, "closed": True,
                    "closed_reason": room.closed_reason,
                    "message": close_reason_text(room.closed_reason),
                    "record_url": (f"/api/room/{room.code}/record") if record else None,
                })
            token = (qs.get("token") or [None])[0]
            return self._json(venue.rooms.view(room, token))

        def _send_sgf(self, fp):
            """把一份 SGF 棋谱作为附件下载。"""
            try:
                with open(fp, "rb") as f:
                    body = f.read()
            except OSError:
                return self._json({"error": "棋谱读取失败"}, 500)
            name = os.path.basename(fp)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-go-sgf; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _api_room_record(self, path):
            """下载某房间最近保存的 SGF 棋谱。"""
            code = path[len("/api/room/"):].rsplit("/", 1)[0].strip("/")
            fp = venue.rooms.record_file_path(code)
            if not fp:
                return self._json({"error": "该对局暂无棋谱"}, 404)
            return self._send_sgf(fp)

        def _api_record_replay(self, path, qs):
            """回放一局棋谱：返回逐手棋盘快照（frames=0 只返回终局，供列表缩略图）。"""
            name = path[len("/api/records/"):]
            if name.endswith("/replay"):
                name = name[: -len("/replay")]
            name = name.strip("/")
            frames = (qs.get("frames", ["1"])[0] or "1").lower() not in ("0", "false", "no")
            data = build_replay(name, venue.rooms.records_dir, include_frames=frames)
            if not data:
                return self._json({"error": "棋谱不存在"}, 404)
            return self._json(data)

        def _api_record_file(self, path):
            """按文件名下载棋谱（拒绝路径穿越）。"""
            name = path[len("/api/records/"):].strip("/")
            fp = venue.rooms.resolve_record(name)
            if not fp:
                return self._json({"error": "棋谱不存在"}, 404)
            return self._send_sgf(fp)

        def _api_room_create(self, data):
            try:
                game_type = GameType(data.get("game_type") or "go")
            except ValueError:
                return self._json({"error": f"未知棋种 {data.get('game_type')}"}, 400)
            mode = (data.get("mode") or "pvp").lower()
            host_color = parse_color(data.get("color")) or Color.BLACK
            size = data.get("size")
            try:
                size = int(size) if size else None
            except (TypeError, ValueError):
                size = None
            kwargs = {}
            if game_type is GameType.GOMOKU and "forbidden" in data:
                kwargs["forbidden"] = bool(data.get("forbidden"))
            try:
                room, seat = venue.rooms.create(
                    game_type, size=size, mode=mode,
                    host_name=(data.get("name") or "玩家"),
                    host_color=host_color,
                    label=data.get("label", ""),
                    **kwargs)
            except PlayError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({
                "ok": True, "code": room.code, "table": room.no,
                "url": f"/room/{room.code}",
                "seat": seat.to_dict(with_token=True),
                "room": room.to_dict(),
                "view": venue.rooms.view(room, seat.token),
            }, 201)

        def _api_room_action(self, path, data):
            parts = [q for q in path.split("/") if q]      # api/room/<code>/<action>
            if len(parts) < 3 or parts[:2] != ["api", "room"]:
                return self._json({"error": "not found", "path": path}, 404)
            code = parts[2]
            action = parts[3] if len(parts) > 3 else ""
            try:
                room = venue.rooms.require(code)
            except PlayError as exc:
                return self._json({"error": str(exc)}, 404)
            token = data.get("token") or ""
            try:
                if action == "join":
                    room, seat = venue.rooms.join(code, data.get("name", ""),
                                                  data.get("color"))
                    return self._json({
                        "ok": True, "code": room.code, "table": room.no,
                        "url": f"/room/{room.code}",
                        "seat": seat.to_dict(with_token=True),
                        "room": room.to_dict(),
                        "view": venue.rooms.view(room, seat.token),
                    })
                if action == "move":
                    result = venue.rooms.move(code, token,
                                              int(data.get("x")), int(data.get("y")))
                elif action == "pass":
                    result = venue.rooms.pass_turn(code, token)
                elif action == "resign":
                    result = venue.rooms.resign(code, token)
                else:
                    return self._json({"error": f"未知操作 {action}"}, 404)
            except PlayError as exc:
                return self._json({"error": str(exc)}, 400)
            except (TypeError, ValueError):
                return self._json({"error": "参数不完整"}, 400)
            return self._json(result)

        # ---------------------------------------------------------- 死活题改卷 API
        def _api_study_view(self, path):
            sid = path[len("/api/study/"):].strip("/")
            try:
                return self._json(venue.study.get(sid).to_dict())
            except QuizError as exc:
                return self._json({"error": str(exc)}, 404)

        def _api_study_start(self, data):
            pid = data.get("id") or data.get("problem")
            try:
                streak = data.get("streak_needed")
                streak = int(streak) if streak else None
                threshold = float(data.get("threshold") or 0.90)
                session = venue.study.start(
                    pid, streak_needed=streak, threshold=threshold)
            except QuizError as exc:
                return self._json({"error": str(exc)}, 400)
            except (TypeError, ValueError):
                return self._json({"error": "参数不合法"}, 400)
            return self._json(session.to_dict(), 201)

        def _api_study_action(self, path, data):
            parts = [q for q in path.split("/") if q]   # api/study/<sid>/<action>
            if len(parts) < 3 or parts[:2] != ["api", "study"]:
                return self._json({"error": "not found", "path": path}, 404)
            sid = parts[2]
            action = parts[3] if len(parts) > 3 else ""
            try:
                if action == "move":
                    return self._json(venue.study.move(sid, data.get("x"), data.get("y")))
                if action == "reset":
                    return self._json(venue.study.reset(sid))
            except QuizError as exc:
                return self._json({"error": str(exc)}, 400)
            except (TypeError, ValueError):
                return self._json({"error": "参数不完整"}, 400)
            return self._json({"error": f"未知操作 {action}"}, 404)

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
                 advertised_host: Optional[str] = None,
                 idle_timeout: Optional[float] = None,
                 records_dir: Optional[str] = None) -> VenueServer:
    return VenueServer(tournament, host=host, port=port,
                       advertised_host=advertised_host,
                       idle_timeout=idle_timeout, records_dir=records_dir)
