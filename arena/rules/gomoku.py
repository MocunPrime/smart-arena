"""五子棋规则（含黑棋禁手）。

会议提到 "五子棋很复杂，有禁手"，本模块实现：
* 连五判胜（黑棋须为恰好五连；白棋五连及以上均胜）
* 黑棋三类禁手：长连（>=6）、四四、三三
* 白棋无禁手

禁手判定采用 "局部窗口 + 一步成五/成开阔四" 的可解释模型，
便于论文中说明；如需严格连珠（Renju）判例，可在此扩展。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import Color, GameType, MoveResult, Verdict
from .base import Coord, RuleSet

EMPTY = Color.EMPTY
BLACK = Color.BLACK
WHITE = Color.WHITE

DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def _max_run(s: str, ch: str = "X") -> int:
    best = cur = 0
    for c in s:
        if c == ch:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _winning_points(s: str) -> List[int]:
    """空格中一步成 "五"（恰好成五连）的落点。"""
    pts = []
    for i, c in enumerate(s):
        if c != ".":
            continue
        t = s[:i] + "X" + s[i + 1:]
        if _max_run(t) == 5:
            pts.append(i)
    return pts


def _is_four(s: str) -> bool:
    return len(_winning_points(s)) >= 1


def _is_open_four(s: str) -> bool:
    return len(_winning_points(s)) >= 2


def _is_open_three(s: str) -> bool:
    if _is_four(s):
        return False
    for i, c in enumerate(s):
        if c != ".":
            continue
        t = s[:i] + "X" + s[i + 1:]
        if _is_open_four(t):
            return True
    return False


class GomokuRules(RuleSet):
    game_type = GameType.GOMOKU

    def __init__(self, size: int = 15, forbidden: bool = True):
        super().__init__(size, komi=0.0)
        self.forbidden = forbidden

    # ------------------------------------------------------------------ 方向窗口
    def _line_str(self, x: int, y: int, dx: int, dy: int, radius: int = 5) -> str:
        chars = []
        for k in range(-radius, radius + 1):
            nx, ny = x + dx * k, y + dy * k
            if not self.in_bounds(nx, ny):
                chars.append("#")            # 棋盘外用独立哨兵，避免与白子混淆
            else:
                c = self.get(nx, ny)
                chars.append("X" if c is BLACK else "O" if c is WHITE else ".")
        return "".join(chars)

    def _run_through(self, x: int, y: int, color: Color) -> int:
        ch = "X" if color is BLACK else "O"
        best = 0
        for dx, dy in DIRS:
            s = self._line_str(x, y, dx, dy)
            mid = len(s) // 2
            # 以落点为中心向两侧数同色
            cnt = 1
            i = mid - 1
            while i >= 0 and s[i] == ch:
                cnt += 1
                i -= 1
            i = mid + 1
            while i < len(s) and s[i] == ch:
                cnt += 1
                i += 1
            best = max(best, cnt)
        return best

    # ------------------------------------------------------------------ 禁手
    def _black_forbidden(self, x: int, y: int) -> Tuple[bool, str]:
        lines = [self._line_str(x, y, dx, dy) for dx, dy in DIRS]
        # 长连
        for s in lines:
            if _max_run(s) >= 6:
                return True, "长连禁手（六子及以上）"
        # 已成五 -> 不是禁手（直接获胜）
        for s in lines:
            if _max_run(s) == 5:
                return False, ""
        # 四四 / 三三
        fours = sum(1 for s in lines if _is_four(s))
        threes = sum(1 for s in lines if _is_open_three(s))
        if fours >= 2:
            return True, "四四禁手"
        if threes >= 2:
            return True, "三三禁手"
        return False, ""

    # ------------------------------------------------------------------ 合法性
    def is_legal(self, color: Color, x: int, y: int) -> MoveResult:
        if self.game_over:
            return MoveResult.GAME_OVER
        if not self.in_bounds(x, y):
            return MoveResult.OUT_OF_BOUNDS
        if self.get(x, y) is not EMPTY:
            return MoveResult.OCCUPIED
        if self.forbidden and color is BLACK:
            self.set(x, y, BLACK)
            bad, _why = self._black_forbidden(x, y)
            self.set(x, y, EMPTY)
            if bad:
                return MoveResult.FORBIDDEN
        return MoveResult.OK

    def forbidden_reason(self, color: Color, x: int, y: int) -> str:
        if color is not BLACK or not self.forbidden:
            return ""
        self.set(x, y, BLACK)
        _bad, why = self._black_forbidden(x, y)
        self.set(x, y, EMPTY)
        return why

    # ------------------------------------------------------------------ 落子/判定
    def _apply(self, color: Color, x: int, y: int) -> None:
        self.set(x, y, color)

    def _update_verdict(self) -> None:
        lm = self.last_move
        if lm is None or lm.is_pass:
            self._verdict = Verdict.ONGOING
            return
        run = self._run_through(lm.x, lm.y, lm.color)
        if lm.color is WHITE and run >= 5:
            self.game_over = True
            self._verdict = Verdict.WHITE_WIN
        elif lm.color is BLACK and run == 5:
            self.game_over = True
            self._verdict = Verdict.BLACK_WIN
        else:
            self._verdict = Verdict.ONGOING

    def score(self) -> dict:
        pieces = self.count_pieces()
        return {"black_stones": pieces[BLACK], "white_stones": pieces[WHITE]}

    def extra_public(self) -> dict:
        return {"forbidden": self.forbidden}

    @classmethod
    def from_string(cls, rows: List[str], forbidden: bool = True) -> "GomokuRules":
        size = len(rows)
        g = cls(size=size, forbidden=forbidden)
        mapping = {".": EMPTY, "X": BLACK, "x": BLACK, "O": WHITE, "o": WHITE}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row.strip()):
                if ch == " ":
                    continue
                g.set(x, y, mapping[ch])
        return g