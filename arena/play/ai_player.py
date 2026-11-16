"""无外部引擎时的对弈 AI（启发式）。

目标不是"很强"，而是让软件在**没有 KataGo、没有外网**的环境下也能下起来：

* 五子棋：棋型打分（成五 / 活四 / 冲四 / 活三 / 眠三 / 活二…），
  同时评估"自己下这里"和"对手下这里"，攻守兼顾；
* 翻转棋：位置价值表（角 > 边 > X 位）+ 可翻子数；
* 围棋：靠近己方棋块、贴身接触对方、避开中腹过密与自己的眼位。

若接入 KataGo（``arena.ai.KataGoEvaluator``），把 :class:`HeuristicPlayer`
换成 GTP 引擎即可，:class:`arena.play.room.RoomManager` 不感知差异。
"""
from __future__ import annotations

import random
from typing import Optional, Tuple

from ..model import Color, GameType
from ..rules.base import RuleSet

BLACK, WHITE = Color.BLACK, Color.WHITE
Coord = Tuple[int, int]

DIRS4 = ((1, 0), (0, 1), (1, 1), (1, -1))
CROSS = ((1, 0), (-1, 0), (0, 1), (0, -1))

#: (连子数, 开放端数) -> 分值；开放端 0 表示被堵死、价值很低
GOMOKU_PATTERN = {
    (5, 2): 5_000_000, (5, 1): 5_000_000, (5, 0): 5_000_000,
    (4, 2): 500_000,        # 活四：必胜
    (4, 1): 60_000,         # 冲四
    (3, 2): 40_000,         # 活三
    (3, 1): 3_000,          # 眠三
    (2, 2): 2_000,          # 活二
    (2, 1): 150,
    (1, 2): 40,
    (1, 1): 8,
}


# --------------------------------------------------------------------- 五子棋
def _line_shape(rules: RuleSet, x: int, y: int, dx: int, dy: int, color: Color):
    """把 (x,y) 视作已落 color，返回该方向的 (连子数, 开放端数)。"""
    size = rules.size
    run, open_ends = 1, 0
    for sign in (1, -1):
        step = 1
        while True:
            nx, ny = x + dx * step * sign, y + dy * step * sign
            if not (0 <= nx < size and 0 <= ny < size):
                break
            value = rules.get(nx, ny)
            if value is color:
                run += 1
                step += 1
                continue
            if value is Color.EMPTY:
                open_ends += 1
            break
    return run, open_ends


def _gomoku_point_score(rules: RuleSet, x: int, y: int, color: Color) -> float:
    """假定 color 落在 (x,y)，四方向的棋型总分。"""
    total = 0.0
    for dx, dy in DIRS4:
        run, opens = _line_shape(rules, x, y, dx, dy, color)
        total += GOMOKU_PATTERN.get((min(run, 5), opens), 0)
    return total


# --------------------------------------------------------------------- 翻转棋
def _reversi_weight(size: int, x: int, y: int) -> float:
    """位置价值：角最高，贴角位（X 位 / C 位）为负。"""
    on_edge_x = x in (0, size - 1)
    on_edge_y = y in (0, size - 1)
    if on_edge_x and on_edge_y:
        return 120.0
    near = (x in (0, 1, size - 2, size - 1)) and (y in (0, 1, size - 2, size - 1))
    if near and (on_edge_x or on_edge_y):
        return -35.0
    if on_edge_x or on_edge_y:
        return 12.0
    return 0.0


def _reversi_flips(rules: RuleSet, x: int, y: int, color: Color) -> int:
    flips = getattr(rules, "_flips", None)
    if flips is None:
        return 0
    try:
        return len(flips(color, x, y))
    except Exception:
        return 0


# --------------------------------------------------------------------- 围棋
def _is_own_eye(rules: RuleSet, x: int, y: int, color: Color) -> bool:
    """四邻全为同色 —— 近似判为"自己的眼"，AI 不去填。"""
    for dx, dy in CROSS:
        nx, ny = x + dx, y + dy
        if not rules.in_bounds(nx, ny) or rules.get(nx, ny) is not color:
            return False
    return True


def _go_point_score(rules: RuleSet, x: int, y: int, color: Color) -> float:
    size = rules.size
    center = (size - 1) / 2.0
    score = 0.0
    contacts = 0
    for dx, dy in CROSS:
        nx, ny = x + dx, y + dy
        if not rules.in_bounds(nx, ny):
            continue
        value = rules.get(nx, ny)
        if value is color:
            score += 9.0            # 与己方连成一片
            contacts += 1
        elif value is color.opposite:
            score += 5.0            # 贴身接触：既进攻也防守
            contacts += 1
        else:
            score += 1.0            # 有气
    if contacts == 0 and len(rules.moves) > size:
        score -= 25.0               # 中后盘脱先乱跑，扣分
    distance = abs(x - center) + abs(y - center)
    score -= 0.8 * distance
    if x in (0, size - 1) or y in (0, size - 1):
        score -= 3.0 if len(rules.moves) < size else 0.0
    return score


class HeuristicPlayer:
    """按棋种走启发式最佳点的"陪练 AI"。"""

    name = "heuristic"
    label = "AI·启发式"

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------ 接口
    def choose(self, rules: RuleSet, color: Color) -> Optional[Coord]:
        """返回一手 (x, y)；无子可下时返回 None（由调用方停一手）。"""
        if rules.game_over:
            return None
        moves = rules.legal_moves(color)
        if not moves:
            return None
        game_type = rules.game_type
        if game_type is GameType.GOMOKU:
            return self._choose_gomoku(rules, color, moves)
        if game_type is GameType.REVERSI:
            return self._choose_reversi(rules, color, moves)
        return self._choose_go(rules, color, moves)

    def close(self) -> None:            # 与 KataGoEvaluator 保持同一接口
        pass

    # ------------------------------------------------------------------ 各棋种
    def _choose_gomoku(self, rules, color, moves) -> Coord:
        opponent = color.opposite
        best, best_score = moves[0], None
        for x, y in moves:
            score = self._hypothetical(rules, x, y, color, _gomoku_point_score)
            block = self._hypothetical(rules, x, y, opponent, _gomoku_point_score)
            total = score + block * 0.85
            if score >= GOMOKU_PATTERN[(5, 2)]:
                total += 10_000_000          # 自己能成五，直接下
            elif block >= GOMOKU_PATTERN[(5, 2)]:
                total += 6_000_000           # 对手能成五，必须堵
            total += self._rng.random()      # 同分随机，避免每局一模一样
            if best_score is None or total > best_score:
                best, best_score = (x, y), total
        return best

    def _choose_reversi(self, rules, color, moves) -> Coord:
        best, best_score = moves[0], None
        for x, y in moves:
            flips = _reversi_flips(rules, x, y, color)
            score = _reversi_weight(rules.size, x, y) + 0.6 * flips
            score += self._rng.random()
            if best_score is None or score > best_score:
                best, best_score = (x, y), score
        return best

    def _choose_go(self, rules, color, moves) -> Optional[Coord]:
        candidates = [m for m in moves if not _is_own_eye(rules, m[0], m[1], color)]
        if not candidates:
            candidates = moves
        best, best_score = candidates[0], None
        for x, y in candidates:
            score = _go_point_score(rules, x, y, color) + self._rng.random()
            if best_score is None or score > best_score:
                best, best_score = (x, y), score
        return best

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _hypothetical(rules, x, y, color, fn) -> float:
        """临时把 (x,y) 当成 color 再评估，评估完立即还原。"""
        saved = rules.get(x, y)
        rules.set(x, y, color)
        try:
            return fn(rules, x, y, color)
        finally:
            rules.set(x, y, saved)