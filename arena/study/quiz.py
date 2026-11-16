"""死活题改卷：做题会话与判定。

判定规则（会议纪要）：人类每落一手，由（引擎 / 参考解答模型）给出这一步
的"胜率"；**连续若干手胜率都在阈值（默认 0.90）以上**，即判为做对。

无真实引擎时使用"参考解答模型"：踩在标准答案续着上记 ~0.95，走错记 ~0.30。
接入 KataGo 后可改用引擎胜率（见 ``docs/OPEN-ISSUES.md``）。
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..model import Color, MoveResult
from ..rules.go import GoRules
from .problems import _solver_move_count, get_problem, list_problems

BLACK, WHITE = Color.BLACK, Color.WHITE
COLOR_CHAR = {"B": BLACK, "W": WHITE}


class QuizError(Exception):
    """做题操作错误：题号不存在、坐标非法、已结束等。"""


def parse_problem(raw: dict) -> dict:
    """校验并规范化一道题（供内置题库与外部导入共用）。"""
    if not isinstance(raw, dict):
        raise QuizError("题目格式错误：应为对象")
    for key in ("id", "board", "solver", "target"):
        if key not in raw:
            raise QuizError(f"题目缺少字段：{key}")
    size = int(raw.get("size") or len(raw["board"]))
    board = [str(row) for row in raw["board"]]
    if len(board) != size or any(len(row) != size for row in board):
        raise QuizError("棋盘尺寸与 size 不一致")
    if set("".join(board)) - set("XO."):
        raise QuizError("棋盘只允许 X / O / . 三种字符")
    solver = str(raw["solver"]).upper()
    if solver not in ("BLACK", "B", "WHITE", "W"):
        raise QuizError("solver 只能是 BLACK / WHITE")
    solver = "BLACK" if solver.startswith("B") else "WHITE"
    tx, ty = raw["target"]
    if not (0 <= int(tx) < size and 0 <= int(ty) < size):
        raise QuizError("target 越界")
    lines = []
    for line in raw.get("lines", []):
        norm = []
        for ply in line:
            color, x, y = ply
            c = str(color).upper()
            if c not in ("B", "W", "BLACK", "WHITE"):
                raise QuizError("解答线颜色只能是 B / W")
            norm.append([("B" if c.startswith("B") else "W"), int(x), int(y)])
        if norm:
            lines.append(norm)
    if not lines:
        raise QuizError("题目至少需要一条参考解答线")
    prob = {
        "id": str(raw["id"]),
        "name": str(raw.get("name") or raw["id"]),
        "difficulty": str(raw.get("difficulty") or "未分级"),
        "size": size,
        "board": board,
        "solver": solver,
        "target": [int(tx), int(ty)],
        "goal": str(raw.get("goal") or "capture"),
        "hint": str(raw.get("hint") or ""),
        "lines": lines,
    }
    return prob


class _Trie:
    """参考解答的字典树：把多条黑白解答线合并成一棵可逐手匹配的树。"""

    __slots__ = ("children",)

    def __init__(self) -> None:
        self.children: Dict[Tuple[str, int, int], "_Trie"] = {}


def _build_trie(lines: List[list]) -> _Trie:
    root = _Trie()
    for line in lines:
        node = root
        for color, x, y in line:
            node = node.children.setdefault((color, x, y), _Trie())
    return root


@dataclass
class QuizSession:
    """一次做题会话。"""

    problem: dict
    threshold: float = 0.90
    streak_needed: int = 0        # 0 = 自动取本题正解的关键手数
    sid: str = field(default_factory=lambda: secrets.token_urlsafe(9))

    #: 渐进的做题线路（用于前端进程条）
    streak: int = 0
    wrong_count: int = 0
    solved: bool = False
    finished: bool = False
    message: str = ""
    last_winrate: Optional[float] = None
    history: List[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.problem = parse_problem(self.problem)
        if not self.streak_needed:
            self.streak_needed = _solver_move_count(self.problem)
        self._solver = BLACK if self.problem["solver"] == "BLACK" else WHITE
        self._target = tuple(self.problem["target"])
        self.reset()

    # ------------------------------------------------------------------ 基本
    @property
    def solver_color(self) -> Color:
        return self._solver

    @property
    def to_play(self) -> Color:
        return self._rules.to_play

    @property
    def captured(self) -> bool:
        return self._rules.get(self._target[0], self._target[1]) is Color.EMPTY

    def reset(self) -> None:
        self._rules = GoRules(size=self.problem["size"], komi=0.0)
        mp = {"X": BLACK, "O": WHITE, ".": Color.EMPTY}
        for y, row in enumerate(self.problem["board"]):
            for x, ch in enumerate(row):
                self._rules.set(x, y, mp[ch])
        self._rules.positions = [self._rules._snapshot()]
        self._rules.to_play = self._solver
        self._root = _build_trie(self.problem["lines"])
        self._node = self._root
        self.streak = 0
        self.wrong_count = 0
        self.solved = False
        self.finished = False
        self.message = "请落子：找出提掉被围白棋（黑棋）的手筋。"
        self.last_winrate = None
        self.history = []

    # ------------------------------------------------------------------ 落子
    def play(self, x: int, y: int) -> dict:
        if self.finished or self.solved:
            raise QuizError("本题已结束，请重置后重做")
        if self._rules.to_play is not self._solver:
            # 正常流程下不会出现（对手着法由系统自动应）；保险起见自动应一手
            self._auto_reply()
        if not self._rules.in_bounds(int(x), int(y)):
            raise QuizError("落点越界")
        if self._rules.is_legal(self._solver, int(x), int(y)) is not MoveResult.OK:
            return self._wrong(x, y, note="这一点不能落子")
        key = ("B" if self._solver is BLACK else "W", int(x), int(y))
        child = self._node.children.get(key)
        if child is None:
            return self._wrong(x, y)
        return self._correct(x, y, child)

    def _correct(self, x: int, y: int, child: _Trie) -> dict:
        self._rules.play(self._solver, int(x), int(y))
        self._node = child
        self.streak += 1
        self.last_winrate = round(min(0.99, 0.92 + 0.02 * self.streak), 2)
        self.history.append({"side": "human", "color": self._solver.name,
                             "x": int(x), "y": int(y), "winrate": self.last_winrate,
                             "correct": True})
        self.message = f"好手！胜率 {self.last_winrate:.0%}，已连续走对 {self.streak} 手。"
        self._auto_reply()
        if self.captured:
            self.finished = True
            if self.streak >= self.streak_needed:
                self.solved = True
                self.message = (f"做对了！连续 {self.streak} 手胜率都在 "
                                f"{self.threshold:.0%} 以上，白棋被提。")
            else:
                self.message = "白棋已提，但仍需按正解走完关键手。"
        return self.to_dict()

    def _wrong(self, x: int, y: int, note: str = "") -> dict:
        self.wrong_count += 1
        self.streak = 0
        self.last_winrate = 0.30
        self.history.append({"side": "human", "color": self._solver.name,
                             "x": int(x), "y": int(y), "winrate": 0.30,
                             "correct": False})
        self.message = (note or "这一步胜率只有约 30%，不是要点，再想想。")
        self.message += "（连续做对计数已清零）"
        return self.to_dict()

    def _auto_reply(self) -> None:
        """按参考解答自动替对手应一手（记进历史，不计入人类连对）。"""
        if self._rules.to_play is self._solver:
            return
        opp_char = "W" if self._solver is BLACK else "B"
        nxt = None
        for (color, x, y), node in self._node.children.items():
            if color == opp_char:
                nxt = ((color, x, y), node)
                break
        if nxt is None:
            return
        (color, x, y), node = nxt
        if self._rules.is_legal(self._rules.to_play, x, y) is not MoveResult.OK:
            return
        self._rules.play(self._rules.to_play, x, y)
        self._node = node
        self.history.append({"side": "engine", "color": self._rules.board[y][x].name,
                             "x": int(x), "y": int(y), "winrate": None, "correct": True})

    # ------------------------------------------------------------------ 视图
    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "id": self.problem["id"],
            "name": self.problem["name"],
            "difficulty": self.problem["difficulty"],
            "size": self.problem["size"],
            "board": self._board_ints(),
            "to_play": self._rules.to_play.name,
            "solver": self._solver.name,
            "target": list(self._target),
            "board_rows": list(self.problem["board"]),
            "hint": self.problem["hint"],
            "last_move": self._rules.last_move.to_dict() if self._rules.last_move else None,
            "streak": self.streak,
            "streak_needed": self.streak_needed,
            "wrong_count": self.wrong_count,
            "threshold": self.threshold,
            "solved": self.solved,
            "finished": self.finished,
            "last_winrate": self.last_winrate,
            "message": self.message,
            "history": list(self.history),
            "winrate_source": "参考解答模型",
        }

    def _board_ints(self) -> List[List[int]]:
        return [[int(self._rules.get(x, y)) for x in range(self._rules.size)]
                for y in range(self._rules.size)]


class StudyManager:
    """做题会话管理（供 HTTP 层使用）。"""

    def __init__(self, max_sessions: int = 200, evaluator=None):
        self._sessions: Dict[str, QuizSession] = {}
        self._lock = threading.Lock()
        self._max = max_sessions
        self._evaluator = evaluator

    def list_problems(self) -> dict:
        return {"problems": list_problems()}

    def start(self, pid: str, streak_needed: Optional[int] = None,
              threshold: float = 0.90) -> QuizSession:
        prob = get_problem(pid)
        if prob is None:
            raise QuizError("没有这道题")
        with self._lock:
            if len(self._sessions) >= self._max:
                # 丢掉最早的一半，避免内存无上限增长
                for key in list(self._sessions)[: self._max // 2]:
                    self._sessions.pop(key, None)
            session = QuizSession(problem=prob, threshold=threshold,
                                  streak_needed=streak_needed or 0)
            self._sessions[session.sid] = session
        return session

    def get(self, sid: str) -> QuizSession:
        session = self._sessions.get(sid)
        if session is None:
            raise QuizError("做题会话不存在或已过期，请重新选题")
        return session

    def move(self, sid: str, x: int, y: int) -> dict:
        return self.get(sid).play(int(x), int(y))

    def reset(self, sid: str) -> dict:
        session = self.get(sid)
        session.reset()
        return session.to_dict()