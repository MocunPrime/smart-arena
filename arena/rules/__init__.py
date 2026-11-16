"""棋种规则注册表：按棋种创建对应规则对象。"""
from __future__ import annotations

from typing import Dict, Optional, Type

from ..model import GameType
from .base import RuleSet
from .go import GoRules
from .gomoku import GomokuRules
from .reversi import ReversiRules

REGISTRY: Dict[GameType, Type[RuleSet]] = {
    GameType.GO: GoRules,
    GameType.GOMOKU: GomokuRules,
    GameType.REVERSI: ReversiRules,
}

DEFAULT_SIZE = {GameType.GO: 19, GameType.GOMOKU: 15, GameType.REVERSI: 8}


def create_rules(game_type: GameType, size: Optional[int] = None, **kwargs) -> RuleSet:
    cls = REGISTRY[game_type]
    if size is None:
        size = DEFAULT_SIZE[game_type]
    if game_type is GameType.GO and "komi" not in kwargs:
        kwargs["komi"] = 7.5
    return cls(size=size, **kwargs)


__all__ = ["RuleSet", "GoRules", "GomokuRules", "ReversiRules",
           "REGISTRY", "DEFAULT_SIZE", "create_rules"]