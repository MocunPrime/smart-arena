"""领域模型：颜色、棋种、着法、犯规、判定等基础类型。

命名尽量与 Katayzy 的 ``featurecat.lizzie.rules.Stone`` / ``BoardData``
保持一致，方便后续把逻辑移植回 Java 版本。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class Color(enum.IntEnum):
    """棋子颜色。对应 Katayzy 的 Stone 枚举（去掉递归/被提标记）。"""

    EMPTY = 0
    BLACK = 1
    WHITE = 2

    @property
    def opposite(self) -> "Color":
        if self is Color.BLACK:
            return Color.WHITE
        if self is Color.WHITE:
            return Color.BLACK
        return Color.EMPTY

    @property
    def name_cn(self) -> str:
        return {Color.BLACK: "黑", Color.WHITE: "白", Color.EMPTY: "空"}[self]


class GameType(str, enum.Enum):
    GO = "go"
    GOMOKU = "gomoku"
    REVERSI = "reversi"

    @property
    def name_cn(self) -> str:
        return {"go": "围棋", "gomoku": "五子棋", "reversi": "翻转棋"}[self.value]


class MoveResult(str, enum.Enum):
    """一次落子的结果。"""

    OK = "ok"
    ILLEGAL = "illegal"          # 一般违规
    SUICIDE = "suicide"          # 禁入点（自杀）
    KO = "ko"                    # 打劫未找劫材
    OCCUPIED = "occupied"        # 已有子
    FORBIDDEN = "forbidden"      # 五子棋禁手
    OUT_OF_BOUNDS = "out_of_bounds"
    NOT_YOUR_TURN = "not_your_turn"
    GAME_OVER = "game_over"


class FoulType(str, enum.Enum):
    SUICIDE = "suicide"
    KO = "ko"
    FORBIDDEN = "forbidden"          # 五子棋禁手（三三/四四/长连）
    OCCUPIED = "occupied"
    OUT_OF_BOUNDS = "out_of_bounds"
    TIMEOUT = "timeout"
    ILLEGAL_REVERSI = "illegal_reversi"

    @property
    def name_cn(self) -> str:
        return {
            FoulType.SUICIDE: "禁入点（自杀）",
            FoulType.KO: "打劫非法",
            FoulType.FORBIDDEN: "禁手",
            FoulType.OCCUPIED: "落在已有子",
            FoulType.OUT_OF_BOUNDS: "越界",
            FoulType.TIMEOUT: "超时",
            FoulType.ILLEGAL_REVERSI: "非法落子（无法翻子）",
        }[self]


class Verdict(str, enum.Enum):
    ONGOING = "ongoing"
    BLACK_WIN = "black_win"
    WHITE_WIN = "white_win"
    DRAW = "draw"

    @property
    def name_cn(self) -> str:
        return {
            Verdict.ONGOING: "进行中",
            Verdict.BLACK_WIN: "黑胜",
            Verdict.WHITE_WIN: "白胜",
            Verdict.DRAW: "和棋",
        }[self]


@dataclass(frozen=True)
class Move:
    """一步着法。``x``/``y`` 为 None 表示弃权/停一手（pass）。"""

    color: Color
    x: Optional[int]
    y: Optional[int]
    move_no: int
    is_pass: bool = False

    @property
    def coord(self) -> Optional[Tuple[int, int]]:
        if self.x is None or self.y is None:
            return None
        return (self.x, self.y)

    def to_dict(self) -> dict:
        return {
            "color": self.color.name,
            "x": self.x,
            "y": self.y,
            "move_no": self.move_no,
            "is_pass": self.is_pass,
        }


@dataclass
class FoulRecord:
    """犯规记录。对应会议中 "第一次警告，第二次判负" 的需求。"""

    color: Color
    foul_type: FoulType
    move_no: int
    timestamp: float = field(default_factory=time.time)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "color": self.color.name,
            "color_cn": self.color.name_cn,
            "foul_type": self.foul_type.value,
            "foul_type_cn": self.foul_type.name_cn,
            "move_no": self.move_no,
            "note": self.note,
            "time": self.timestamp,
        }


# 结果 -> 具体错误信息的映射
RESULT_TO_FOUL = {
    MoveResult.SUICIDE: FoulType.SUICIDE,
    MoveResult.KO: FoulType.KO,
    MoveResult.OCCUPIED: FoulType.OCCUPIED,
    MoveResult.OUT_OF_BOUNDS: FoulType.OUT_OF_BOUNDS,
    MoveResult.FORBIDDEN: FoulType.FORBIDDEN,
}