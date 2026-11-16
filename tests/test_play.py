"""线上对弈测试：对局码 / 房间 / 走子 / 认输 / 人机 / HTTP 接口。"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arena.venue.server as venue_server  # noqa: E402
from arena.model import Color, GameType, Verdict  # noqa: E402
from arena.play import PlayError, RoomManager, make_code, parse_color  # noqa: E402
from arena.play.room import ALPHABET  # noqa: E402
from arena.tournament import Tournament  # noqa: E402
from arena.venue.server import VenueServer  # noqa: E402

BLACK, WHITE = Color.BLACK, Color.WHITE


class CodeTest(unittest.TestCase):
    def test_make_code_format_and_dedupe(self):
        taken = {"AAAA"}
        for _ in range(200):
            code = make_code(taken)
            self.assertEqual(len(code), 4)
            self.assertTrue(set(code) <= set(ALPHABET))
            for bad in ("I", "O", "0", "1"):
                self.assertNotIn(bad, code)
            self.assertNotIn(code, taken)
            taken.add(code)

    def test_parse_color(self):
        self.assertIs(parse_color("black"), BLACK)
        self.assertIs(parse_color("B"), BLACK)
        self.assertIs(parse_color("白"), WHITE)
        self.assertIs(parse_color("执黑"), BLACK)
        self.assertIsNone(parse_color("紫"))


class RoomTest(unittest.TestCase):
    def setUp(self):
        self.t = Tournament()
        self.mgr = RoomManager(self.t)

    def test_create_join_and_full(self):
        room, seat = self.mgr.create(GameType.GO, size=9, host_name="甲")
        self.assertIs(seat.color, BLACK)
        self.assertFalse(room.is_full)
        self.assertEqual(room.status, "waiting")
        room2, seat2 = self.mgr.join(room.code, "乙", "WHITE")
        self.assertIs(seat2.color, WHITE)
        self.assertTrue(room.is_full)
        with self.assertRaises(PlayError):
            self.mgr.join(room.code, "丙")

    def test_join_duplicate_color(self):
        room, _ = self.mgr.create(GameType.GO, size=9, host_color=BLACK)
        with self.assertRaises(PlayError):
            self.mgr.join(room.code, "乙", "BLACK")

    def test_view_never_leaks_token(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        v = self.mgr.view(room, seat.token)
        self.assertNotIn(seat.token, json.dumps(v))
        self.assertIsNone(v["seat_tokens"])
        self.assertTrue(v["viewer"]["seated"])
        self.assertTrue(v["can_move"])            # 黑先，房主执黑
        self.assertFalse(self.mgr.view(room, None)["viewer"]["seated"])

    def test_illegal_moves(self):
        room, seat = self.mgr.create(GameType.GOMOKU, size=15)
        with self.assertRaises(PlayError):
            self.mgr.move(room.code, seat.token, 99, 99)        # 越界
        with self.assertRaises(PlayError):
            self.mgr.move(room.code, "not-a-token", 3, 3)       # 未落座
        self.mgr.move(room.code, seat.token, 7, 7)
        self.assertIs(room.referee.rules.get(7, 7), BLACK)
        with self.assertRaises(PlayError):                      # 同点重复
            self.mgr.move(room.code, seat.token, 7, 7)

    def test_go_occupied_point_and_wrong_turn(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        _, ws = self.mgr.join(room.code, "乙", "WHITE")
        self.mgr.move(room.code, seat.token, 4, 4)
        with self.assertRaises(PlayError):                      # 白方轮到，黑方再走
            self.mgr.move(room.code, seat.token, 2, 2)
        with self.assertRaises(PlayError):                      # 已有子
            self.mgr.move(room.code, ws.token, 4, 4)

    def test_pass_and_summary(self):
        room, seat = self.mgr.create(GameType.GO, size=9, mode="pvp")
        _, ws = self.mgr.join(room.code, "乙", "WHITE")
        self.mgr.pass_turn(room.code, seat.token)
        self.mgr.pass_turn(room.code, ws.token)                 # 白也停一手 -> 终局
        self.assertTrue(room.game_over)
        self.assertEqual(room.referee.summary()["first_pass"], "BLACK")

    def test_resign(self):
        room, seat = self.mgr.create(GameType.GO, size=9)
        res = self.mgr.resign(room.code, seat.token)
        self.assertTrue(room.game_over)
        self.assertEqual(room.referee.summary()["resigned"], "BLACK")
        self.assertIs(room.referee.verdict(), Verdict.WHITE_WIN)
        self.assertTrue(res["game_over"])
        self.assertIsNotNone(res["summary"])
        with self.assertRaises(PlayError):                      # 已终局不能再走
            self.mgr.move(room.code, seat.token, 2, 2)

    def test_pve_ai_replies(self):
        room, seat = self.mgr.create(GameType.GOMOKU, size=15, mode="pve",
                                     host_color=BLACK, host_name="人")
        self.assertTrue(room.seats[WHITE].is_ai)
        self.mgr.move(room.code, seat.token, 7, 7)
        self.assertGreaterEqual(len(room.referee.rules.moves), 2)  # AI 已应对
        self.assertIs(room.referee.rules.get(7, 7), BLACK)

    def test_pve_ai_moves_first_when_host_white(self):
        room, seat = self.mgr.create(GameType.GOMOKU, size=15, mode="pve",
                                     host_color=WHITE)
        self.assertTrue(room.seats[BLACK].is_ai)
        self.assertGreaterEqual(len(room.referee.rules.moves), 1)

    def test_reversi_pve_ai_legal(self):
        room, seat = self.mgr.create(GameType.REVERSI, size=8, mode="pve",
                                     host_color=BLACK)
        # 黑方走一手合法着法（由 AI 计算器给出一个合法点）
        legal = room.referee.rules.legal_moves(BLACK)
        self.assertTrue(legal)
        x, y = legal[0]
        self.mgr.move(room.code, seat.token, x, y)
        self.assertGreaterEqual(len(room.referee.rules.moves), 2)


class PlayHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._flag = venue_server.VENUE_ENABLED
        venue_server.VENUE_ENABLED = False           # 本阶段智慧赛场默认停用
        cls.t = Tournament()
        cls.venue = VenueServer(cls.t, host="127.0.0.1", port=0,
                                advertised_host="127.0.0.1")
        cls.venue.build()
        cls.thr = threading.Thread(target=cls.venue.httpd.serve_forever, daemon=True)
        cls.thr.start()
        cls.base = f"http://127.0.0.1:{cls.venue.port}"

    @classmethod
    def tearDownClass(cls):
        cls.venue.shutdown()
        venue_server.VENUE_ENABLED = cls._flag

    def _get(self, path, allow_error=False):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if not allow_error:
                raise
            return e.code, e.read()

    def _post(self, path, obj, allow_error=False):
        data = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if not allow_error:
                raise
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_lobby_and_game_page(self):
        st, body = self._get("/play")
        self.assertEqual(st, 200)
        self.assertTrue(body.decode("utf-8").startswith("<!doctype html"))
        st, body = self._get("/room/ABCD")
        self.assertEqual(st, 200)
        self.assertIn(b"game.js", body)

    def test_static_game_js_served(self):
        st, js = self._get("/static/game.js")
        self.assertEqual(st, 200)
        self.assertIn(b"drawBoard", js)
        self.assertIn(b"/move", js)

    def test_rooms_list_and_full_flow(self):
        st, body = self._get("/api/rooms")
        self.assertEqual(st, 200)
        self.assertIn("rooms", json.loads(body))
        st, d = self._post("/api/room/create",
                           {"game_type": "gomoku", "size": 15, "mode": "pvp",
                            "color": "BLACK", "name": "甲"})
        self.assertEqual(st, 201)
        code, token = d["code"], d["seat"]["token"]
        self.assertEqual(len(code), 4)
        st, d2 = self._post(f"/api/room/{code}/join", {"name": "乙", "color": "WHITE"})
        self.assertTrue(d2["ok"])
        tok2 = d2["seat"]["token"]
        st, m = self._post(f"/api/room/{code}/move", {"token": token, "x": 7, "y": 7})
        self.assertTrue(m["ok"])
        self.assertTrue(m["outcome"]["accepted"])
        self.assertEqual(m["view"]["board"][7][7], 1)
        st, m2 = self._post(f"/api/room/{code}/move", {"token": tok2, "x": 7, "y": 8})
        self.assertTrue(m2["outcome"]["accepted"])
        st, body = self._get(f"/api/room/{code}")
        self.assertNotIn(token, body.decode("utf-8"))
        self.assertNotIn(tok2, body.decode("utf-8"))

    def test_move_errors_return_400(self):
        st, d = self._post("/api/room/create",
                           {"game_type": "go", "size": 9, "color": "BLACK", "name": "甲"})
        code, token = d["code"], d["seat"]["token"]
        st, err = self._post(f"/api/room/{code}/move",
                             {"token": token, "x": 50, "y": 50}, allow_error=True)
        self.assertEqual(st, 400)
        self.assertIn("error", err)

    def test_venue_disabled_by_default(self):
        st, _ = self._get("/api/tables", allow_error=True)
        self.assertEqual(st, 503)
        st, _ = self._get("/api/table/1", allow_error=True)
        self.assertEqual(st, 503)
        st, _ = self._get("/table/1", allow_error=True)
        self.assertEqual(st, 503)
        st, _ = self._get("/api/rooms")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)