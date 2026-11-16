"""内置死活题题库。

每题给出：棋盘（字符画行，``X`` 黑 / ``O`` 白 / ``.`` 空）、需要被杀的
白棋目标点、执黑行棋方，以及**参考解答线**（黑白交替的坐标数组）。

坐标约定：``[x, y]``，``x`` 从左到右（0 开始），``y`` 从上到下（0 开始），
与 :meth:`arena.rules.go.GoRules.from_string` 一致。

参考解答线均由本项目的局部死活求解器验证过：按线行棋，最后目标白棋被提。
题库为不同难度的经典**杀棋/提子**常型（紧气提子、扑、倒扑、征子追杀等），
属公共围棋理论，由本项目整理，未使用任何受版权保护的习题集。
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

#: 难度分级（由易到难），供前端分组展示
DIFFICULTIES: List[str] = ["入门", "初级", "中级", "高级"]

#: 内置题库。每题的 ``lines`` 是一到多条参考解答线（黑白交替）。
BUILTIN_PROBLEMS: List[dict] = [
    {
        "id": "tsumego-e001",
        "name": "紧气提子",
        "difficulty": "入门",
        "size": 5,
        "board": [
            "XXXXX",
            "XOOXX",
            "XX.XX",
            "XXXXX",
            "XXXXX",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 2, 2]],
        ],
        "hint": "白棋两子只剩一口气，黑棋直接紧气即可提子。",
    },
    {
        "id": "tsumego-p002",
        "name": "扑后紧气",
        "difficulty": "初级",
        "size": 5,
        "board": [
            "XXX..",
            "XOO..",
            "XO...",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 2, 2], ["W", 2, 3], ["B", 3, 1]],
        ],
        "hint": "先在白棋气紧处扑一手，白棋提子后自己反而更紧，黑再收气。",
    },
    {
        "id": "tsumego-i003",
        "name": "角上收气",
        "difficulty": "初级",
        "size": 5,
        "board": [
            "XX...",
            "XOO..",
            "X.OX.",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 2, 3], ["W", 1, 2], ["B", 2, 0], ["W", 3, 0], ["B", 3, 1]],
        ],
        "hint": "先把白棋往下压，再从上方收气，注意别让白棋做出眼位。",
    },
    {
        "id": "tsumego-i004",
        "name": "追杀白棋",
        "difficulty": "中级",
        "size": 5,
        "board": [
            "XX...",
            "XOO..",
            "XO.X.",
            "XXX..",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 2, 0], ["W", 2, 2], ["B", 3, 0], ["W", 3, 1],
             ["B", 3, 3], ["W", 4, 0], ["B", 4, 1]],
        ],
        "hint": "白棋想往右边逃，黑棋一手一手贴住，始终不让白棋长出足够的气。",
    },
    {
        "id": "tsumego-i005",
        "name": "三手杀",
        "difficulty": "中级",
        "size": 5,
        "board": [
            "XXXX.",
            "XOOO.",
            "XO...",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 3, 2], ["W", 2, 2], ["B", 2, 3], ["W", 3, 3], ["B", 4, 1]],
        ],
        "hint": "第一手点在要害，白棋挡住后黑棋从下边收气。",
    },
    {
        "id": "tsumego-i006",
        "name": "滚打包收",
        "difficulty": "中级",
        "size": 5,
        "board": [
            "XXX..",
            "XOOO.",
            "XO...",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 3, 2], ["W", 2, 2], ["B", 2, 3], ["W", 3, 0],
             ["B", 3, 3], ["W", 4, 0], ["B", 4, 1]],
        ],
        "hint": "边打边收，把白棋往边上滚，最后收气提子。",
    },
    {
        "id": "tsumego-a007",
        "name": "长气对杀",
        "difficulty": "高级",
        "size": 5,
        "board": [
            "XXX..",
            "XOO..",
            "XO.X.",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 2, 2], ["W", 2, 3], ["B", 3, 0], ["W", 3, 1], ["B", 4, 0],
             ["W", 4, 1], ["B", 3, 3], ["W", 4, 2], ["B", 4, 3]],
        ],
        "hint": "第一手先扑在要害，白棋长气后黑棋要一直贴住、算清征子方向。",
    },
    {
        "id": "tsumego-a008",
        "name": "边线征子",
        "difficulty": "高级",
        "size": 5,
        "board": [
            "XXX..",
            "XO...",
            "XOO..",
            "XX...",
            ".....",
        ],
        "solver": "BLACK",
        "target": [1, 1],
        "goal": "capture",
        "lines": [
            [["B", 3, 2], ["W", 1, 4], ["B", 2, 1], ["W", 2, 3], ["B", 3, 3],
             ["W", 2, 4], ["B", 0, 4], ["W", 3, 1], ["B", 3, 4]],
        ],
        "hint": "白棋贴边逃，黑棋沿着边线一气一气地征，最后一手收气。",
    },
]

PROBLEM_BY_ID: Dict[str, dict] = {p["id"]: p for p in BUILTIN_PROBLEMS}


def list_problems() -> List[dict]:
    """列出全部题目（去掉解答，供前端展示）。"""
    out = []
    for p in BUILTIN_PROBLEMS:
        out.append({
            "id": p["id"],
            "name": p["name"],
            "difficulty": p["difficulty"],
            "size": p["size"],
            "solver": p["solver"],
            "goal": p.get("goal", "capture"),
            "target": list(p["target"]),
            "mo_count": _solver_move_count(p),
            "board": [row for row in p["board"]],
        })
    return out


def get_problem(pid: str) -> Optional[dict]:
    """按 id 取题（返回深拷贝，避免调用方改动内置数据）。"""
    p = PROBLEM_BY_ID.get(pid)
    return copy.deepcopy(p) if p else None


def _solver_move_count(p: dict) -> int:
    """参考解答里行棋方的着数（= 需要连续做对的手数，至少 1）。"""
    best = None
    for line in p["lines"]:
        n = sum(1 for color, _x, _y in line if color == p["solver"][0])
        best = n if best is None else min(best, n)
    return best or 1