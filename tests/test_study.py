"""死活题改卷测试：题库 / 会话判定 / 连续做对 / 弃权记录 / HTTP 接口。"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.model import Color, GameType, MoveResult  # noqa: E402
from arena.play import RoomManager  # noqa: E402
from arena.study import (BUILTIN_PROBLEMS, QuizError, QuizSession,  # noqa: E402
                         StudyManager, get_problem, list_problems, parse_problem)
from arena.tournament import Tournament  # noqa: E402
from arena.venue.server import VenueServer  # noqa: E402

BLACK, WHITE = Color.BLACK, Color.WHITE


class ProblemBankTest(unittest.TestCase):
    def test_problem_count_and_difficulties(self):
        probs = list_problems()
        self.assertGreaterEqual(len(probs), 6)
        diffs = {p["difficulty"] for p in probs}
        for want in ("入门", "初级", "中级", "高级"):
            self.assertIn(want, diffs)
        for p in probs:                       # 列表不泄露解答
            self.assertNotIn("lines", p)
            self.assertGreaterEqual(p["mo_count"], 1)

    def test_get_problem_is_deep_copy(self):
        pid = BUILTIN_PROBLEMS[0]["id"]
        a = get_problem(pid)
        a["board"][0] = "OOOOO"
        b = get_problem(pid)
        self.assertEqual(b["board"][0], BUILTIN_PROBLEMS[0]["board"][0])

    def test_parse_problem_validation(self):
        with self.assertRaises(QuizError):     # 无解答线
            parse_problem({"id": "x", "board": ["..", ".."], "solver": "BLACK",
                           "target": [0, 0], "lines": []})
        with self.assertRaises(QuizError):     # 非法字符
            parse_problem({"id": "x", "board": ["ZZ"], "solver": "BLACK",
                           "target": [0, 0], "lines": [[["B", 0, 0]]]})
        with self.assertRaises(QuizError):     # target 越界
            parse_problem({"id": "x", "board": ["..", ".."], "solver": "BLACK",
                           "target": [5, 5], "lines": [[["B", 0, 0]]]})


class QuizSessionTest(unittest.TestCase):
    def test_all_builtin_problems_solvable(self):
        for raw in BUILTIN_PROBLEMS:
            prob = get_problem(raw["id"])
            s = QuizSession(problem=prob)
            last = None
            for color, x, y in prob["lines"][0]:
                if color == prob["solver"][0]:
                    last = s.play(x, y)
            self.assertTrue(last["solved"], raw["id"])
            self.assertGreaterEqual(last["streak"], last["streak_needed"])

    def test_winrate_at_or_above_threshold(self):
        prob = get_problem(BUILTIN_PROBLEMS[0]["id"])
        s = QuizSession(problem=prob)
        first = prob["lines"][0][0]
        d = s.play(first[1], first[2])
        self.assertGreaterEqual(d["last_winrate"], d["threshold"])

    def test_wrong_move_resets_streak(self):
        prob = get_problem("tsumego-p002")
        s = QuizSession(problem=prob)                     # streak_needed = 2
        first = prob["lines"][0][0]
        s.play(first[1], first[2])
        self.assertEqual(s.streak, 1)
        wrong = None
        for y in range(prob["size"]):
            for x in range(prob["size"]):
                if (x, y) == (first[1], first[2]):
                    continue
                if s._rules.is_legal(s.solver_color, x, y) is not MoveResult.OK:
                    continue
                if ("B", x, y) not in s._node.children:
                    wrong = (x, y)
                    break
            if wrong:
                break
        self.assertIsNotNone(wrong, "应能找到一个非正解的合法着点")
        d = s.play(wrong[0], wrong[1])
        self.assertEqual(d["streak"], 0)
        self.assertFalse(d["solved"])
        self.assertGreaterEqual(d["wrong_count"], 1)
        self.assertEqual(d["last_winrate"], 0.30)

    def test_play_after_finished_raises(self):
        prob = get_problem(BUILTIN_PROBLEMS[0]["id"])
        s = QuizSession(problem=prob)
        first = prob["lines"][0][0]
        s.play(first[1], first[2])
        self.assertTrue(s.solved)
        with self.assertRaises(QuizError):
            s.play(first[1], first[2])


class StudyManagerTest(unittest.TestCase):
    def test_start_move_reset(self):
        mgr = StudyManager()
        s = mgr.start(BUILTIN_PROBLEMS[0]["id"])
        first = BUILTIN_PROBLEMS[0]["lines"][0][0]
        d = mgr.move(s.sid, first[1], first[2])
        self.assertTrue(d["solved"])
        r = mgr.reset(s.sid)
        self.assertFalse(r["solved"])
        self.assertEqual(r["history"], [])
        self.assertEqual(r["streak"], 0)

    def test_unknown_problem(self):
        mgr = StudyManager()
        with self.assertRaises(QuizError):
            mgr.start("does-not-exist")

    def test_get_missing_session(self):
        mgr = StudyManager()
        with self.assertRaises(QuizError):
            mgr.get("nope")


class PassLogTest(unittest.TestCase):
    def test_pass_log_records_and_first_pass(self):
        t = Tournament()
        mgr = RoomManager(t)
        room, seat = mgr.create(GameType.GO, size=9, mode="pvp")
        _, ws = mgr.join(room.code, "乙", "WHITE")
        mgr.move(room.code, seat.token, 4, 4)          # 黑第 1 手
        mgr.move(room.code, ws.token, 3, 3)            # 白第 2 手
        mgr.pass_turn(room.code, seat.token)           # 黑弃权（在白第 2 手之后）
        mgr.pass_turn(room.code, ws.token)             # 白也弃权 -> 终局
        v = mgr.view(room, seat.token)
        self.assertIn("pass_log", v)
        self.assertEqual(v["first_pass"], "BLACK")
        log = v["pass_log"]
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0]["color"], "BLACK")
        self.assertEqual(log[0]["after_move_no"], 2)
        self.assertEqual(log[0]["after_color"], "WHITE")
        self.assertEqual(log[0]["after_color_cn"], "白")
        self.assertEqual(log[1]["color"], "WHITE")
        self.assertEqual(log[1]["after_move_no"], 3)
        self.assertEqual(log[1]["after_color"], "BLACK")

    def test_first_pass_is_first_ever(self):
        t = Tournament()
        mgr = RoomManager(t)
        room, seat = mgr.create(GameType.GO, size=9, mode="pvp")
        _, ws = mgr.join(room.code, "乙", "WHITE")
        mgr.move(room.code, seat.token, 4, 4)          # 黑第 1 手
        mgr.pass_turn(room.code, ws.token)             # 白先弃权（在黑第 1 手之后）
        v = mgr.view(room, seat.token)
        self.assertEqual(v["first_pass"], "WHITE")
        self.assertEqual(v["pass_log"][0]["after_move_no"], 1)


class StudyHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

    def test_study_page_and_problems(self):
        st, body = self._get("/study")
        self.assertEqual(st, 200)
        self.assertIn(b"study.js", body)
        st, body = self._get("/api/study/problems")
        self.assertEqual(st, 200)
        probs = json.loads(body)["problems"]
        self.assertTrue(probs)
        self.assertNotIn("lines", probs[0])

    def test_study_flow(self):
        st, body = self._get("/api/study/problems")
        pid = json.loads(body)["problems"][0]["id"]
        st, d = self._post("/api/study/start", {"id": pid})
        self.assertEqual(st, 201)
        sid = d["sid"]
        self.assertIn("streak", d)
        prob = get_problem(pid)
        first = prob["lines"][0][0]
        st, mv = self._post(f"/api/study/{sid}/move",
                            {"x": first[1], "y": first[2]})
        self.assertEqual(st, 200)
        self.assertIn("last_winrate", mv)
        st, rs = self._post(f"/api/study/{sid}/reset", {})
        self.assertEqual(rs["streak"], 0)
        st, body = self._get(f"/api/study/{sid}")
        self.assertEqual(st, 200)
        view = json.loads(body)
        self.assertEqual(view["id"], pid)
        self.assertFalse(view["solved"])

    def test_study_errors(self):
        st, err = self._post("/api/study/nope/move", {"x": 0, "y": 0},
                             allow_error=True)
        self.assertEqual(st, 400)
        self.assertIn("error", err)
        st, err = self._post("/api/study/start", {"id": "missing"},
                             allow_error=True)
        self.assertEqual(st, 400)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
