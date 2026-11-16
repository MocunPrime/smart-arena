"""围棋规则（中国规则/数子法）。

覆盖会议要点：
* 禁入点（自杀）、打劫（简单劫）、停一手（pass）
* 终局数子（area scoring）与胜负判定
* 记录最后一手、连续弃权，供裁判模块生成终局小结
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import Color, GameType, MoveResult, Verdict
from .base import Coord, RuleSet

EMPTY = Color.EMPTY
BLACK = Color.BLACK
WHITE = Color.WHITE


class GoRules(RuleSet):
    game_type = GameType.GO

    def __init__(self, size: int = 19, komi: float = 7.5):
        super().__init__(size, komi=komi)
        # 记录历史局面（含初始局面）用于打劫判定
        self.positions: List[Tuple[Tuple[int, ...], ...]] = [self._snapshot()]
        self.consecutive_passes = 0
        self.pass_order: List[Color] = []

    # ------------------------------------------------------------------ 快照
    def _snapshot(self) -> Tuple[Tuple[int, ...], ...]:
        return tuple(tuple(int(c) for c in row) for row in self.board)

    # ------------------------------------------------------------------ 合法性
    def is_legal(self, color: Color, x: int, y: int) -> MoveResult:
        if self.game_over:
            return MoveResult.GAME_OVER
        if not self.in_bounds(x, y):
            return MoveResult.OUT_OF_BOUNDS
        if self.get(x, y) is not EMPTY:
            return MoveResult.OCCUPIED

        sim = self._simulate(color, x, y)
        if sim is None:
            return MoveResult.SUICIDE
        new_board, _captured = sim

        # 简单劫：落子后局面不得与 "两步之前" 的局面相同
        if len(self.positions) >= 2 and new_board == self.positions[-2]:
            return MoveResult.KO
        return MoveResult.OK

    def _simulate(self, color: Color, x: int, y: int):
        """在副本上落子并提子，返回 (新局面, 提子数)；自杀返回 None。"""
        board = [row[:] for row in self.board]
        board[y][x] = color
        captured = 0
        # 先提对方无气棋串
        ex, ey = x, y
        checked = set()
        for nx, ny in ((ex - 1, ey), (ex + 1, ey), (ex, ey - 1), (ex, ey + 1)):
            if not (0 <= nx < self.size and 0 <= ny < self.size):
                continue
            if board[ny][nx] is not color.opposite or (nx, ny) in checked:
                continue
            group, libs = self._flood(board, nx, ny)
            checked |= group
            if not libs:
                captured += len(group)
                for gx, gy in group:
                    board[gy][gx] = EMPTY
        # 再判断自身是否有气
        group, libs = self._flood(board, x, y)
        if not libs:
            return None
        return tuple(tuple(int(c) for c in row) for row in board), captured

    def _flood(self, board, x: int, y: int):
        color = board[y][x]
        stones, seen, stack, libs = set(), {(x, y)}, [(x, y)], set()
        while stack:
            cx, cy = stack.pop()
            stones.add((cx, cy))
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if not (0 <= nx < self.size and 0 <= ny < self.size):
                    continue
                v = board[ny][nx]
                if v is EMPTY:
                    libs.add((nx, ny))
                elif v is color and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return stones, libs

    # ------------------------------------------------------------------ 落子
    def _apply(self, color: Color, x: int, y: int) -> None:
        self.set(x, y, color)
        _, captured = 0, 0
        checked = set()
        removed = 0
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not self.in_bounds(nx, ny):
                continue
            if self.get(nx, ny) is not color.opposite or (nx, ny) in checked:
                continue
            group, libs = self.group_and_liberties(nx, ny)
            checked |= group
            if not libs:
                removed += len(group)
                for gx, gy in group:
                    self.set(gx, gy, EMPTY)
        if removed:
            self.captures[color] = self.captures.get(color, 0) + removed
        self.consecutive_passes = 0
        self.positions.append(self._snapshot())

    def _apply_pass(self, color: Color) -> None:
        self.consecutive_passes += 1
        self.pass_order.append(color)
        self.positions.append(self._snapshot())

    def _update_verdict(self) -> None:
        if self.consecutive_passes >= 2:
            self.game_over = True
            self._verdict = self._compute_verdict()
        else:
            self._verdict = Verdict.ONGOING

    # ------------------------------------------------------------------ 数子
    def score(self) -> dict:
        black_area, white_area = self._area()
        white_total = white_area + self.komi
        diff = black_area - white_total
        return {
            "rule": "chinese_area",
            "black_area": black_area,
            "white_area": white_area,
            "komi": self.komi,
            "white_total": white_total,
            "diff": diff,
        }

    def _area(self):
        black_t = white_t = 0
        visited = set()
        for x, y in self.cells():
            if self.get(x, y) is not EMPTY or (x, y) in visited:
                continue
            region, seen, stack, border = set(), {(x, y)}, [(x, y)], set()
            while stack:
                cx, cy = stack.pop()
                region.add((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not self.in_bounds(nx, ny):
                        continue
                    v = self.get(nx, ny)
                    if v is EMPTY and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
                    elif v is not EMPTY:
                        border.add(v)
            visited |= region
            if border == {BLACK}:
                black_t += len(region)
            elif border == {WHITE}:
                white_t += len(region)
        b_stones, w_stones = self.count_pieces()[BLACK], self.count_pieces()[WHITE]
        return b_stones + black_t, w_stones + white_t

    def _compute_verdict(self) -> Verdict:
        diff = self.score()["diff"]
        if abs(diff) < 1e-9:
            return Verdict.DRAW
        return Verdict.BLACK_WIN if diff > 0 else Verdict.WHITE_WIN

    # ------------------------------------------------------------------ 序列化
    def extra_public(self) -> dict:
        return {
            "consecutive_passes": self.consecutive_passes,
            "first_pass": self.pass_order[0].name if self.pass_order else None,
        }

    # ------------------------------------------------------------------ 调试/测试
    @classmethod
    def from_string(cls, rows: List[str], komi: float = 7.5) -> "GoRules":
        """用字符画棋盘构造（. 空 X 黑 O 白），方便单测。"""
        size = len(rows)
        g = cls(size=size, komi=komi)
        mapping = {".": EMPTY, "X": BLACK, "O": WHITE, "x": BLACK, "o": WHITE}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row.strip()):
                if ch in (" ",):
                    continue
                g.set(x, y, mapping[ch])
        g.positions = [g._snapshot()]
        return g