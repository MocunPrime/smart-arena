"""系统级测试：裁判、团队投票、赛事、智慧赛场服务、引擎适配。"""
import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.ai import GtpClient, HeuristicEvaluator, make_evaluator  # noqa: E402
from arena.hardware import HardwareHub, MemoryDisplay, MockBoardLink, OledDisplay  # noqa: E402
from arena.model import Color, GameType, Verdict  # noqa: E402
from arena.referee import Referee, TimeControl  # noqa: E402
from arena.rules import create_rules  # noqa: E402
from arena.team import VotingSession, demo_side  # noqa: E402
from arena.tournament import Tournament  # noqa: E402
from arena.venue.server import VenueServer  # noqa: E402

BLACK, WHITE = Color.BLACK, Color.WHITE
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RefereeTest(unittest.TestCase):
    def test_foul_warning_then_loss(self):
        ref = Referee(create_rules(GameType.GO, 9))
        ref.play(BLACK, 4, 4)
        ref.play(WHITE, 3, 3)
        # 黑方连续两次非法（落在已有子）
        o1 = ref.play(BLACK, 4, 4)
        self.assertEqual(ref.foul_count(BLACK), 1)
        self.assertFalse(o1.loss_by_foul)          # 第一次 = 警告
        o2 = ref.play(BLACK, 4, 4)
        self.assertEqual(ref.foul_count(BLACK), 2)
        self.assertTrue(o2.loss_by_foul)           # 第二次 = 判负
        self.assertEqual(ref.verdict(), Verdict.WHITE_WIN)

    def test_pass_order_and_summary(self):
        ref = Referee(create_rules(GameType.GO, 9))
        ref.play_pass(BLACK)
        ref.play_pass(WHITE)
        self.assertTrue(ref.game_over)
        self.assertEqual(ref.pass_order[0], BLACK)
        self.assertEqual(ref.summary()["first_pass"], "BLACK")

    def test_timeout_as_foul(self):
        ref = Referee(create_rules(GameType.GO, 9), time_control=TimeControl(total=0.01))
        ref.clock[BLACK] = -1
        out = ref.check_timeout()
        self.assertIsNotNone(out)
        self.assertEqual(ref.foul_count(BLACK), 1)


class TeamVotingTest(unittest.TestCase):
    def test_weighted_tally_and_captain(self):
        side = demo_side("红队", captain_weight=3.0, guest_weight=2.0)
        s = VotingSession(side, BLACK, 1, timeout_s=60)
        s.cast("红队-前锋A", (3, 3))
        s.cast("红队-前锋B", (3, 3))
        s.cast("红队-队长", (5, 5))
        ranking = s.tally()
        # 队长权重 3.0 > 两名前锋合计 2.0，体现 "队长权重高"
        self.assertEqual(ranking[0]["coord"], (5, 5))
        self.assertAlmostEqual(ranking[0]["weight"], 3.0)
        s.captain_choose((5, 5))
        self.assertEqual(s.resolve()["mode"], "captain")
        self.assertEqual(tuple(s.resolve()["point"]), (5, 5))

    def test_forced_when_expired(self):
        side = demo_side("蓝队", captain_weight=3.0, guest_weight=2.0)
        now = time.time()
        s = VotingSession(side, WHITE, 10, timeout_s=60, now=now)
        s.cast("蓝队-前锋A", (1, 1), weight=1.0)
        s.cast("蓝队-嘉宾", (2, 2), weight=2.0)   # 权重更高
        d = s.resolve(now + 61)                   # 已超时
        self.assertEqual(d["mode"], "forced")
        self.assertEqual(tuple(d["point"]), (2, 2))

    def test_phase_roster(self):
        side = demo_side("红队")
        self.assertIn("前锋", side.phase_name(1))
        self.assertIn("中场", side.phase_name(100))
        self.assertIn("后卫", side.phase_name(300))


class TournamentVenueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = Tournament()
        cls.t.create_table(1, GameType.GO, size=9, label="围棋A")
        cls.t.create_table(2, GameType.GOMOKU, size=15, label="五子棋A")
        cls.t.get(1).black_team = demo_side("红队")
        cls.t.get(1).white_team = demo_side("蓝队")
        cls.venue = VenueServer(cls.t, host="127.0.0.1", port=0, advertised_host="127.0.0.1")
        cls.venue.build()
        import threading
        cls.thr = threading.Thread(target=cls.venue.httpd.serve_forever, daemon=True)
        cls.thr.start()
        cls.base = f"http://127.0.0.1:{cls.venue.port}"

    @classmethod
    def tearDownClass(cls):
        cls.venue.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.read()

    def _post(self, path, obj):
        data = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_api_tables(self):
        st, body = self._get("/api/tables")
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(body)["tables"]), 2)

    def test_api_table_view(self):
        st, body = self._get("/api/table/1")
        self.assertEqual(st, 200)
        v = json.loads(body)
        self.assertEqual(v["table"], 1)
        self.assertIn("black_winrate", v)

    def test_post_play_updates_board(self):
        st, out = self._post("/api/play", {"table": 2, "color": "BLACK", "x": 7, "y": 7})
        self.assertEqual(st, 200)
        self.assertTrue(out["accepted"])
        st, body = self._get("/api/table/2")
        v = json.loads(body)
        self.assertEqual(v["board"][7][7], 1)
        self.assertEqual(v["move_number"], 1)

    def test_index_has_qr(self):
        st, body = self._get("/")
        self.assertEqual(st, 200)
        self.assertTrue(body.decode("utf-8").startswith("<!doctype html"))
        # 二维码应被渲染为 data URI
        self.assertIn(b"data:image/png;base64,", body)

    def test_qr_endpoints(self):
        st, png = self._get("/qr.png")
        self.assertEqual(st, 200)
        self.assertTrue(png.startswith(b"\x89PNG"))
        st, svg = self._get("/qr.svg")
        self.assertIn(b"<svg", svg)

    def test_table_page_has_curve_and_vote(self):
        st, body = self._get("/table/1")
        self.assertEqual(st, 200)
        html = body.decode("utf-8")
        self.assertIn('id="curve"', html)
        self.assertIn('id="votepanel"', html)
        st, js = self._get("/static/table.js")
        self.assertIn(b"drawCurve", js)
        self.assertIn(b"renderVote", js)

    def test_vote_flow(self):
        st, body = self._get("/api/table/1")
        v = json.loads(body)
        color = v["to_play"]
        team = v["black_team"] if color == "BLACK" else v["white_team"]
        self.assertIsNotNone(team, "需要为本桌挂载团队名册")
        names = [m["name"] for m in team["members"]]
        board, size = v["board"], v["size"]
        empty = next(((x, y) for y in range(size) for x in range(size)
                      if board[y][x] == 0), (0, 0))
        st, r = self._post("/api/table/1/vote/open", {"color": color, "timeout_s": 60})
        self.assertEqual(st, 200)
        self.assertTrue(r["ok"])
        self._post("/api/table/1/vote/cast",
                   {"member": names[0], "x": empty[0], "y": empty[1]})
        self._post("/api/table/1/vote/cast",
                   {"member": names[1], "x": empty[0], "y": empty[1]})
        st, r = self._post("/api/table/1/vote/captain", {"x": empty[0], "y": empty[1]})
        self.assertTrue(r["ok"])
        st, r = self._post("/api/table/1/vote/resolve", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["decision"]["mode"], "captain")
        self.assertEqual(tuple(r["decision"]["point"]), empty)
        st, body = self._get("/api/table/1")
        v2 = json.loads(body)
        self.assertEqual(v2["board"][empty[1]][empty[0]], 1 if color == "BLACK" else 2)
        self.assertIsNone(v2["vote"])

    def test_winrate_history(self):
        t = Tournament()
        tb = t.create_table(9, GameType.GO, size=9)
        t.play(9, BLACK, 4, 4)
        t.play(9, WHITE, 2, 2)
        h = tb.view()["history"]
        self.assertEqual(len(h), 2)
        self.assertIn("black_winrate", h[0])


class EngineTest(unittest.TestCase):
    def test_heuristic_winrate_range(self):
        ev = HeuristicEvaluator()
        res = ev.win_rate(create_rules(GameType.REVERSI, 8))
        self.assertAlmostEqual(res.black_winrate + res.white_winrate, 1.0, places=6)

    def test_gtp_client_with_mock_engine(self):
        script = os.path.join(ROOT, "tools", "mock_gtp_engine.py")
        client = GtpClient([sys.executable, script])
        try:
            client.start()
            self.assertEqual(client.command("name"), "MockGTP")
            client.command("boardsize 9")
            client.command("clear_board")
            self.assertEqual(client.command("genmove black"), "D4")
        finally:
            client.close()

    def test_katago_falls_back_without_engine(self):
        ev = make_evaluator(None)     # 无引擎路径
        self.assertIsInstance(ev, HeuristicEvaluator)


class HardwareTest(unittest.TestCase):
    def test_oled_and_link(self):
        ref = Referee(create_rules(GameType.GO, 9), names={BLACK: "黑", WHITE: "白"})
        ref.play(BLACK, 4, 4)
        hub = HardwareHub(ref, HeuristicEvaluator(), display=OledDisplay(), link=MockBoardLink())
        v = hub.refresh()
        self.assertIn("black_winrate", v)
        self.assertTrue(hub.display.frames)
        self.assertEqual(len(hub.link.sent), 1)
        self.assertIn("黑", hub.display.render_lines(v)[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)