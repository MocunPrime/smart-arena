"""\u68cb\u8c31\u4fdd\u5b58 / \u623f\u95f4\u7a7a\u95f2\u81ea\u52a8\u5173\u95ed / \u68cb\u8c31\u4e0b\u8f7d \u6d4b\u8bd5\u3002"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arena.venue.server as venue_server  # noqa: E402
from arena.model import Color, GameType  # noqa: E402
from arena.play import RoomManager  # noqa: E402
from arena.play.record import list_records, room_to_sgf  # noqa: E402
from arena.tournament import Tournament  # noqa: E402
from arena.venue.server import VenueServer  # noqa: E402

BLACK, WHITE = Color.BLACK, Color.WHITE


class _Clock:
    """\u53ef\u63a7\u65f6\u949f\uff1a\u907f\u514d\u6d4b\u8bd5\u771f\u7684\u7b49 30 \u5206\u949f\u3002"""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class IdleCloseTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.clock = _Clock()
        self.t = Tournament()
        self.mgr = RoomManager(self.t, idle_timeout=60.0, records_dir=self.dir,
                               auto_sweep=False, clock=self.clock)

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_sweep_closes_idle_room_and_saves_record(self):
        room, seat = self.mgr.create(GameType.GO, size=9, host_name="\u7532")
        self.mgr.move(room.code, seat.token, 4, 4)
        self.assertFalse(room.closed)
        self.assertEqual(self.mgr.sweep_idle(), [])            # \u672a\u8d85\u65f6
        self.clock.advance(61)
        closed = self.mgr.sweep_idle()
        self.assertEqual(closed, [room.code])
        self.assertTrue(room.closed)
        self.assertEqual(room.closed_reason, "inactivity")
        # \u68cb\u8c31\u5df2\u81ea\u52a8\u4fdd\u5b58
        self.assertTrue(room.record_path and os.path.isfile(room.record_path))
        text = self._read(room.record_path)
        self.assertIn("RO[" + room.code + "]", text)
        self.assertIn("GM[1]", text)
        self.assertIn(";B[ee]", text)                          # (4,4) -> e,e
        self.assertEqual(len(list_records(self.dir)), 1)

    def test_activity_resets_idle_timer(self):
        room, seat = self.mgr.create(GameType.GOMOKU, size=15)
        self.clock.advance(50)
        self.mgr.move(room.code, seat.token, 7, 7)             # \u6d3b\u52a8\u5237\u65b0\u8ba1\u65f6
        self.clock.advance(50)
        self.assertEqual(self.mgr.sweep_idle(), [])            # \u8ddd\u4e0a\u6b21\u6d3b\u52a8\u4ec5 50s
        self.clock.advance(11)
        self.assertEqual(self.mgr.sweep_idle(), [room.code])

    def test_close_is_idempotent(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        self.mgr.move(room.code, seat.token, 4, 4)
        self.mgr.close(room.code, reason="manual")
        first = room.record_path
        self.assertTrue(os.path.isfile(first))
        self.assertFalse(self.mgr.close(room.code))            # \u5df2\u5173\u95ed
        self.assertEqual(room.record_path, first)              # \u672a\u91cd\u590d\u4fdd\u5b58
        self.assertEqual(len(list_records(self.dir)), 1)

    def test_record_saved_on_game_over(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        self.mgr.join(room.code, "\u4e59", "WHITE")
        self.mgr.resign(room.code, seat.token)                 # \u9ed1\u8ba4\u8f93 -> \u767d\u80dc
        self.assertTrue(room.game_over)
        self.assertTrue(os.path.isfile(room.record_path))
        text = self._read(room.record_path)
        self.assertIn("RE[W+R]", text)
        self.assertIn("C[", text)

    def test_record_saved_on_two_passes(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        _, ws = self.mgr.join(room.code, "\u4e59", "WHITE")
        self.mgr.pass_turn(room.code, seat.token)
        self.mgr.pass_turn(room.code, ws.token)                # \u53cc\u65b9\u505c\u4e00\u624b -> \u7ec8\u5c40
        self.assertTrue(room.game_over)
        self.assertTrue(os.path.isfile(room.record_path))

    def test_sgf_contains_moves(self):
        room, seat = self.mgr.create(GameType.GOMOKU, size=15)
        _, ws = self.mgr.join(room.code, "\u4e59", "WHITE")
        self.mgr.move(room.code, seat.token, 7, 7)
        self.mgr.move(room.code, ws.token, 8, 8)
        sgf = room_to_sgf(room)
        self.assertIn(";B[hh]", sgf)
        self.assertIn(";W[ii]", sgf)
        self.assertIn("SZ[15]", sgf)

    def test_closed_room_rejected(self):
        from arena.play import PlayError
        room, seat = self.mgr.create(GameType.GO, size=9)
        self.mgr.close(room.code)
        with self.assertRaises(PlayError):
            self.mgr.move(room.code, seat.token, 4, 4)


class RecordHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._flag = venue_server.VENUE_ENABLED
        venue_server.VENUE_ENABLED = False
        cls.dir = tempfile.mkdtemp()
        cls.t = Tournament()
        cls.venue = VenueServer(cls.t, host="127.0.0.1", port=0,
                                advertised_host="127.0.0.1", records_dir=cls.dir,
                                idle_timeout=1800.0)
        cls.venue.build()
        cls.thr = threading.Thread(target=cls.venue.httpd.serve_forever, daemon=True)
        cls.thr.start()
        cls.base = "http://127.0.0.1:%d" % cls.venue.port

    @classmethod
    def tearDownClass(cls):
        cls.venue.shutdown()
        venue_server.VENUE_ENABLED = cls._flag

    def _post(self, path, obj):
        req = urllib.request.Request(self.base + path,
                                     data=json.dumps(obj).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _get(self, path, allow_error=False):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if not allow_error:
                raise
            return e.code, e.read()

    def _make_closed_room(self):
        st, d = self._post("/api/room/create",
                           {"game_type": "go", "size": 9, "color": "BLACK", "name": "\u7532"})
        code, token = d["code"], d["seat"]["token"]
        self._post("/api/room/%s/move" % code, {"token": token, "x": 4, "y": 4})
        self.venue.rooms.close(code, reason="manual")
        return code

    def test_records_list_and_download(self):
        code = self._make_closed_room()
        st, body = self._get("/api/records")
        self.assertEqual(st, 200)
        rows = json.loads(body)["records"]
        self.assertTrue(any(r["code"] == code for r in rows))
        st, raw = self._get("/api/room/%s/record" % code)
        self.assertEqual(st, 200)
        self.assertIn(b"RO[" + code.encode(), raw)
        self.assertIn(b"GM[1]", raw)

    def test_closed_room_view_reports_record(self):
        code = self._make_closed_room()
        st, body = self._get("/api/room/%s" % code)
        self.assertEqual(st, 200)
        data = json.loads(body)
        self.assertTrue(data.get("closed"))
        self.assertIsNotNone(data.get("record_url"))

    def test_unknown_record_returns_404(self):
        st, _ = self._get("/api/room/ZZZZ/record", allow_error=True)
        self.assertEqual(st, 404)

    def test_running_room_view_has_idle_info(self):
        st, d = self._post("/api/room/create",
                           {"game_type": "go", "size": 9, "color": "BLACK", "name": "\u7532"})
        code = d["code"]
        st, body = self._get("/api/room/%s" % code)
        v = json.loads(body)
        self.assertIn("idle_timeout", v)
        self.assertIsNotNone(v.get("idle_remaining"))


    # ---- 回放 / 页面（可视化） ----
    def test_hub_and_records_pages(self):
        for path in ("/", "/records"):
            st, body = self._get(path)
            self.assertEqual(st, 200)
            self.assertIn(b"<html", body.lower())

    def test_replay_api_and_page(self):
        code = self._make_closed_room()
        st, body = self._get("/api/records")
        rows = json.loads(body)["records"]
        name = next(r["name"] for r in rows if r["code"] == code)
        # 逐手快照
        st, body = self._get("/api/records/%s/replay" % name)
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual(d["game_type"], "go")
        self.assertEqual(d["move_count"], 1)
        self.assertEqual(len(d["moves"]), 1)
        self.assertEqual((d["moves"][0]["x"], d["moves"][0]["y"]), (4, 4))
        self.assertEqual(d["final_board"][4][4], 1)
        # 缩略图：不返回逐手
        st, body = self._get("/api/records/%s/replay?frames=0" % name)
        d2 = json.loads(body)
        self.assertEqual(d2["moves"], [])
        self.assertEqual(d2["final_board"][4][4], 1)
        # 回放页面
        st, body = self._get("/replay/%s" % name)
        self.assertEqual(st, 200)
        self.assertIn(b"<html", body.lower())

    def test_record_eval_api(self):
        code = self._make_closed_room()
        st, body = self._get("/api/records")
        rows = json.loads(body)["records"]
        name = next(r["name"] for r in rows if r["code"] == code)
        st, body = self._get("/api/records/%s/eval" % name)
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertIn(d["source"], ("heuristic", "katago"))
        self.assertEqual(d["total"], 1)
        self.assertTrue(d["points"])
        self.assertEqual(d["points"][0]["no"], 0)
        self.assertGreaterEqual(d["points"][-1]["black"], 0.0)
        self.assertLessEqual(d["points"][-1]["black"], 1.0)
        self.assertTrue(d["done"])                 # 内置评估瞬时完成
        st, _ = self._get("/api/records/nope.sgf/eval", allow_error=True)
        self.assertEqual(st, 404)                  # 缺省棋谱 -> 404

    def test_unknown_record_replay_404(self):
        st, _ = self._get("/api/records/nope.sgf/replay", allow_error=True)
        self.assertEqual(st, 404)


class ReplayParseTest(unittest.TestCase):
    def test_parse_sgf_moves_and_meta(self):
        from arena.play.replay import parse_sgf
        sgf = "(;GM[1]SZ[9]PB[\u9ed1]PW[\u767d]RE[W+R]C[a\\]b];B[cc];W[dd];B[];W[])"
        meta, moves = parse_sgf(sgf)
        self.assertEqual(meta.get("SZ"), "9")
        self.assertEqual(meta.get("RE"), "W+R")
        self.assertEqual(meta.get("C"), "a]b")          # 转义正确还原
        self.assertEqual([c for c, _ in moves], [BLACK, WHITE, BLACK, WHITE])
        self.assertEqual(moves[0][1], (2, 2))
        self.assertEqual(moves[1][1], (3, 3))
        self.assertIsNone(moves[2][1])                   # 停一手

    def test_build_replay_reconstructs_board(self):
        from arena.play.replay import build_replay
        d = tempfile.mkdtemp()
        mgr = RoomManager(Tournament(), records_dir=d, auto_sweep=False)
        room, seat = mgr.create(GameType.GO, size=9, host_name="\u7532")
        _, ws = mgr.join(room.code, "\u4e59", "WHITE")
        mgr.move(room.code, seat.token, 2, 2)
        mgr.move(room.code, ws.token, 3, 3)
        mgr.resign(room.code, seat.token)
        name = os.path.basename(room.record_path)
        rep = build_replay(name, d)
        self.assertEqual(rep["move_count"], 2)
        self.assertEqual(rep["final_board"][2][2], 1)    # 黑子
        self.assertEqual(rep["final_board"][3][3], 2)    # 白子
        self.assertEqual(rep["result"], "W+R")
        self.assertIsNone(build_replay("missing.sgf", d))


if __name__ == "__main__":
    unittest.main(verbosity=2)