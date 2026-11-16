"""翻转棋（黑白棋 / Reversi / Othello）规则。

* 合法落子必须能翻转至少一枚对方棋子
* 无子可下时可停一手（pass）
* 双方均无子可下（或连续两次 pass）终局，按子数判胜负
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import Color, GameType, MoveResult, Verdict
from .base import Coord, RuleSet

EMPTY = Color.EMPTY
BLACK = Color.BLACK
WHITE = Color.WHITE

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1))


class ReversiRules(RuleSet):
    game_type = GameType.REVERSI

    def __init__(self, size: int = 8):
        super().__init__(size, komi=0.0)
        self.consecutive_passes = 0
        self._setup_initial()

    def _setup_initial(self) -> None:
        c = self.size // 2
        self.set(c - 1, c - 1, WHITE)
        self.set(c, c, WHITE)
        self.set(c - 1, c, BLACK)
        self.set(c, c - 1, BLACK)
        self.to_play = BLACK

    # ------------------------------------------------------------------ 翻转计算
    def _flips(self, color: Color, x: int, y: int) -> List[Coord]:
        if not self.in_bounds(x, y) or self.get(x, y) is not EMPTY:
            return []
        opp = color.opposite
        result: List[Coord] = []
        for dx, dy in DIRS:
            path = []
            nx, ny = x + dx, y + dy
            while self.in_bounds(nx, ny) and self.get(nx, ny) is opp:
                path.append((nx, ny))
                nx += dx
                ny += dy
            if path and self.in_bounds(nx, ny) and self.get(nx, ny) is color:
                result.extend(path)
        return result

    # ------------------------------------------------------------------ 合法性
    def is_legal(self, color: Color, x: int, y: int) -> MoveResult:
        if self.game_over:
            return MoveResult.GAME_OVER
        if not self.in_bounds(x, y):
            return MoveResult.OUT_OF_BOUNDS
        if self.get(x, y) is not EMPTY:
            return MoveResult.OCCUPIED
        if not self._flips(color, x, y):
            return MoveResult.ILLEGAL
        return MoveResult.OK

    def is_legal_pass(self, color: Color) -> MoveResult:
        return MoveResult.OK

    # ------------------------------------------------------------------ 落子
    def _apply(self, color: Color, x: int, y: int) -> None:
        flips = self._flips(color, x, y)   # 必须先算翻转，落子后该点已非空
        self.set(x, y, color)
        for fx, fy in flips:
            self.set(fx, fy, color)
        self.captures[color] = self.captures.get(color, 0) + len(flips)
        self.consecutive_passes = 0

    def _apply_pass(self, color: Color) -> None:
        self.consecutive_passes += 1

    # ------------------------------------------------------------------ 判定
    def has_move(self, color: Color) -> bool:
        return any(self.is_legal(color, x, y) is MoveResult.OK for x, y in self.cells())

    def _update_verdict(self) -> None:
        board_full = all(self.get(x, y) is not EMPTY for x, y in self.cells())
        no_black = not self.has_move(BLACK)
        no_white = not self.has_move(WHITE)
        if self.consecutive_passes >= 2 or (no_black and no_white):
            self.game_over = True
            b, w = self.count_pieces()[BLACK], self.count_pieces()[WHITE]
            if b > w:
                self._verdict = Verdict.BLACK_WIN
            elif w > b:
                self._verdict = Verdict.WHITE_WIN
            else:
                self._verdict = Verdict.DRAW
        elif board_full:
            self.game_over = True
            self._verdict = Verdict.DRAW
        else:
            self._verdict = Verdict.ONGOING

    def score(self) -> dict:
        pieces = self.count_pieces()
        return {
            "black_stones": pieces[BLACK],
            "white_stones": pieces[WHITE],
            "empty": self.size * self.size - pieces[BLACK] - pieces[WHITE],
        }

    def extra_public(self) -> dict:
        return {"consecutive_passes": self.consecutive_passes}

    @classmethod
    def from_string(cls, rows: List[str]) -> "ReversiRules":
        size = len(rows)
        g = cls(size=size)
        mapping = {".": EMPTY, "X": BLACK, "x": BLACK, "O": WHITE, "o": WHITE}
        for y in range(size):
            for x in range(size):
                g.set(x, y, EMPTY)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row.strip()):
                if ch == " ":
                    continue
                g.set(x, y, mapping[ch])
        g.to_play = BLACK
        return g