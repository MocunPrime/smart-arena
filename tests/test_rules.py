"""多棋种规则引擎的单元测试（标准库 unittest，无需第三方依赖）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.model import Color, MoveResult, Verdict  # noqa: E402
from arena.rules import create_rules  # noqa: E402
from arena.model import GameType  # noqa: E402
from arena.rules.go import GoRules  # noqa: E402
from arena.rules.gomoku import GomokuRules  # noqa: E402
from arena.rules.reversi import ReversiRules  # noqa: E402

BLACK, WHITE = Color.BLACK, Color.WHITE


class GoTest(unittest.TestCase):
    def test_capture_single_stone(self):
        g = GoRules.from_string([
            ".X.",
            "XOX",
            "...",
        ])
        self.assertEqual(g.is_legal(BLACK, 1, 2), MoveResult.OK)
        g.play(BLACK, 1, 2)
        self.assertEqual(g.get(1, 1), Color.EMPTY)      # 白子被提
        self.assertEqual(g.captures[BLACK], 1)

    def test_suicide_forbidden(self):
        g = GoRules.from_string([
            ".X.",
            "X.X",
            ".X.",
        ])
        self.assertEqual(g.is_legal(WHITE, 1, 1), MoveResult.SUICIDE)

    def test_ko_recapture_forbidden(self):
        # 构造打劫局面：黑提白子后，白不可立即回提
        g = GoRules.from_string([
            ".....",
            "..X..",
            ".XOX.",
            ".O.O.",
            "..O..",
        ])
        self.assertEqual(g.play(BLACK, 2, 3), MoveResult.OK)   # 黑提（(2,2) 白子）
        self.assertEqual(g.get(2, 2), Color.EMPTY)
        self.assertEqual(g.is_legal(WHITE, 2, 2), MoveResult.KO)  # 白立即回提非法

    def test_occupied_and_oob(self):
        g = GoRules(size=9)
        g.play(BLACK, 4, 4)
        self.assertEqual(g.is_legal(WHITE, 4, 4), MoveResult.OCCUPIED)
        self.assertEqual(g.is_legal(WHITE, 9, 0), MoveResult.OUT_OF_BOUNDS)

    def test_two_passes_end_and_score(self):
        g = GoRules(size=9)
        self.assertEqual(g.play(BLACK, None, None), MoveResult.OK)
        self.assertFalse(g.game_over)
        self.assertEqual(g.play(WHITE, None, None), MoveResult.OK)
        self.assertTrue(g.game_over)
        score = g.score()
        self.assertIn("diff", score)
        self.assertEqual(score["rule"], "chinese_area")


class GomokuTest(unittest.TestCase):
    def test_five_in_row_wins(self):
        g = GomokuRules.from_string([
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...XXXX........",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
        ])
        self.assertEqual(g.play(BLACK, 7, 7), MoveResult.OK)
        self.assertTrue(g.game_over)
        self.assertEqual(g.verdict(), Verdict.BLACK_WIN)

    def test_overline_forbidden(self):
        g = GomokuRules.from_string([
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...XXXX.X......",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
            "...............",
        ])
        self.assertEqual(g.is_legal(BLACK, 7, 7), MoveResult.FORBIDDEN)
        self.assertIn("长连", g.forbidden_reason(BLACK, 7, 7))

    def test_double_three_forbidden(self):
        rows = [list("...............") for _ in range(15)]
        for (x, y) in [(6, 7), (8, 7), (7, 6), (7, 8)]:
            rows[y][x] = "X"
        g = GomokuRules.from_string(["".join(r) for r in rows])
        self.assertEqual(g.is_legal(BLACK, 7, 7), MoveResult.FORBIDDEN)
        self.assertIn("三三", g.forbidden_reason(BLACK, 7, 7))

    def test_white_edge_is_not_false_five(self):
        # 白子落在棋盘边缘不应被误判为五连
        rows = [list("...............") for _ in range(15)]
        rows[7][0] = "O"
        g = GomokuRules.from_string(["".join(r) for r in rows])
        g.to_play = WHITE
        self.assertEqual(g.play(WHITE, 0, 6), MoveResult.OK)
        self.assertFalse(g.game_over)
        self.assertEqual(g.verdict(), Verdict.ONGOING)

    def test_white_five_wins(self):
        rows = [list("...............") for _ in range(15)]
        for x in range(3, 7):
            rows[7][x] = "O"
        g = GomokuRules.from_string(["".join(r) for r in rows])
        self.assertEqual(g.play(WHITE, 7, 7, enforce_turn=False), MoveResult.OK)
        self.assertEqual(g.verdict(), Verdict.WHITE_WIN)


class ReversiTest(unittest.TestCase):
    def test_initial_legal_moves(self):
        r = ReversiRules()
        legal = set(r.legal_moves(BLACK))
        self.assertEqual(legal, {(2, 3), (3, 2), (4, 5), (5, 4)})

    def test_move_flips(self):
        r = ReversiRules()
        self.assertEqual(r.play(BLACK, 2, 3), MoveResult.OK)
        self.assertEqual(r.get(2, 3), BLACK)
        self.assertEqual(r.get(3, 3), BLACK)   # 翻转
        self.assertEqual(r.to_play, WHITE)

    def test_illegal_when_no_flip(self):
        r = ReversiRules()
        self.assertEqual(r.is_legal(BLACK, 0, 0), MoveResult.ILLEGAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)