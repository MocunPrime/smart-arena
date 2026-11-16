"""棋种规则公共基类。

每种棋（围棋/五子棋/翻转棋）实现一个 ``RuleSet`` 子类，
对外暴露统一接口，供裁判（referee）与智慧赛场（venue）复用。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from ..model import Color, GameType, Move, MoveResult, Verdict

Coord = Tuple[int, int]


class RuleSet:
    """所有棋种规则的抽象基类。"""

    game_type: GameType = None  # 子类给出

    def __init__(self, size: int, komi: float = 0.0):
        self.size = int(size)
        self.komi = float(komi)
        self.board: List[List[Color]] = [
            [Color.EMPTY] * self.size for _ in range(self.size)
        ]
        self.moves: List[Move] = []
        self.to_play: Color = Color.BLACK
        self.game_over: bool = False
        self._verdict: Verdict = Verdict.ONGOING
        self.captures: Dict[Color, int] = {Color.BLACK: 0, Color.WHITE: 0}
        self.last_move: Optional[Move] = None

    # ------------------------------------------------------------------ 基础工具
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def get(self, x: int, y: int) -> Color:
        return self.board[y][x]

    def set(self, x: int, y: int, color: Color) -> None:
        self.board[y][x] = color

    def cells(self) -> Iterable[Coord]:
        for y in range(self.size):
            for x in range(self.size):
                yield x, y

    def neighbors(self, x: int, y: int) -> Iterable[Coord]:
        if x > 0:
            yield x - 1, y
        if x < self.size - 1:
            yield x + 1, y
        if y > 0:
            yield x, y - 1
        if y < self.size - 1:
            yield x, y + 1

    def group_and_liberties(self, x: int, y: int):
        """洪泛求同色棋串及气数（围棋用，五子棋/翻转棋也可复用连通块）。"""
        color = self.get(x, y)
        if color is Color.EMPTY:
            return set(), set()
        stones, seen, stack, liberties = set(), {(x, y)}, [(x, y)], set()
        while stack:
            cx, cy = stack.pop()
            stones.add((cx, cy))
            for nx, ny in self.neighbors(cx, cy):
                v = self.get(nx, ny)
                if v is Color.EMPTY:
                    liberties.add((nx, ny))
                elif v is color and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return stones, liberties

    def count_pieces(self) -> Dict[Color, int]:
        result = {Color.BLACK: 0, Color.WHITE: 0}
        for x, y in self.cells():
            c = self.get(x, y)
            if c is not Color.EMPTY:
                result[c] += 1
        return result

    # ------------------------------------------------------------------ 对外接口
    def play(self, color: Color, x: Optional[int], y: Optional[int],
             enforce_turn: bool = True) -> MoveResult:
        if self.game_over:
            return MoveResult.GAME_OVER
        if enforce_turn and color is not self.to_play:
            return MoveResult.NOT_YOUR_TURN
        if x is None or y is None:
            return self.play_pass(color, enforce_turn=False)
        result = self.is_legal(color, x, y)
        if result is MoveResult.OK:
            self._apply(color, x, y)
            self._after_move(color, x, y, is_pass=False)
        return result

    def play_pass(self, color: Color, enforce_turn: bool = True) -> MoveResult:
        if self.game_over:
            return MoveResult.GAME_OVER
        if enforce_turn and color is not self.to_play:
            return MoveResult.NOT_YOUR_TURN
        result = self.is_legal_pass(color)
        if result is MoveResult.OK:
            self._apply_pass(color)
            self._after_move(color, None, None, is_pass=True)
        return result

    def is_legal(self, color: Color, x: int, y: int) -> MoveResult:
        raise NotImplementedError

    def is_legal_pass(self, color: Color) -> MoveResult:
        return MoveResult.OK

    def legal_moves(self, color: Color) -> List[Coord]:
        return [(x, y) for x, y in self.cells()
                if self.is_legal(color, x, y) is MoveResult.OK]

    def verdict(self) -> Verdict:
        return self._verdict

    # ------------------------------------------------------------------ 子类钩子
    def _apply(self, color: Color, x: int, y: int) -> None:
        raise NotImplementedError

    def _apply_pass(self, color: Color) -> None:
        pass

    def _after_move(self, color: Color, x, y, is_pass: bool) -> None:
        move = Move(color, x, y, len(self.moves) + 1, is_pass=is_pass)
        self.moves.append(move)
        self.last_move = move
        self.to_play = color.opposite
        self._update_verdict()

    def _update_verdict(self) -> None:
        self._verdict = Verdict.ONGOING

    # ------------------------------------------------------------------ 序列化
    def score(self) -> dict:
        return {}

    def extra_public(self) -> dict:
        return {}

    def to_public_dict(self) -> dict:
        board_ints = [
            [int(Color.EMPTY)] * self.size for _ in range(self.size)
        ]
        for x, y in self.cells():
            board_ints[y][x] = int(self.get(x, y))
        return {
            "game_type": self.game_type.value,
            "game_name_cn": self.game_type.name_cn,
            "size": self.size,
            "board": board_ints,
            "to_play": self.to_play.name,
            "move_number": len(self.moves),
            "last_move": self.last_move.to_dict() if self.last_move else None,
            "captures": {
                "BLACK": self.captures.get(Color.BLACK, 0),
                "WHITE": self.captures.get(Color.WHITE, 0),
            },
            "verdict": self._verdict.value,
            "verdict_cn": self._verdict.name_cn,
            "game_over": self.game_over,
            "score": self.score(),
            "extra": self.extra_public(),
        }