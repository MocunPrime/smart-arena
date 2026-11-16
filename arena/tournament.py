"""赛事与多桌（智慧赛场）管理。

* ``EventBus``：裁判/赛事事件总线（供 venue 的 SSE 推送）
* ``Table``：一张棋桌（桌号/棋种/裁判/胜率/团队）
* ``Tournament``：多桌管理，支撑 "十几盘同时下、家长按桌号观看"
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .ai import HeuristicEvaluator, make_evaluator
from .model import Color, GameType
from .referee import Referee, TimeControl
from .rules import create_rules
from .team import TeamSide, VotingSession

BLACK, WHITE = Color.BLACK, Color.WHITE


class EventBus:
    def __init__(self):
        self._subs: List[Callable[[dict], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._subs.append(fn)

    def unsubscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass


@dataclass
class Table:
    no: int
    referee: Referee
    evaluator: object
    black_team: Optional[TeamSide] = None
    white_team: Optional[TeamSide] = None
    label: str = ""
    vote: Optional[VotingSession] = None
    created_at: float = field(default_factory=time.time)
    history: List[dict] = field(default_factory=list)

    # -------------------------------------------------------------- 团队
    def team(self, color: Color) -> Optional[TeamSide]:
        return self.black_team if color is BLACK else self.white_team

    def begin_vote(self, color: Color, timeout_s: float = 60.0,
                   remind_at_s: float = 30.0, candidates=None) -> Optional[VotingSession]:
        side = self.team(color)
        if side is None:
            return None
        self.vote = VotingSession(side, color, len(self.referee.rules.moves) + 1,
                                  timeout_s=timeout_s, remind_at_s=remind_at_s,
                                  candidates=candidates)
        return self.vote

    def apply_vote(self):
        """结算投票并按结果落子；返回 (outcome, decision)。"""
        if self.vote is None:
            return None, None
        decision = self.vote.resolve()
        if decision["point"] is None:
            return None, decision
        x, y = decision["point"]
        outcome = self.referee.play(self.vote.color, x, y)
        self.vote = None
        return outcome, decision

    def record_winrate(self) -> None:
        """记录本手后的胜率，供前端绘制胜率曲线。"""
        ev = self.winrate()
        self.history.append({
            "move_number": len(self.referee.rules.moves),
            "black_winrate": ev["black_winrate"],
            "to_play": self.referee.rules.to_play.name,
        })
        if len(self.history) > 500:
            del self.history[:-500]

    # -------------------------------------------------------------- 视图
    def winrate(self) -> dict:
        ev = self.evaluator.win_rate(self.referee.rules)
        return ev.to_dict()

    def view(self) -> dict:
        pub = self.referee.to_public_dict()
        ev = self.winrate()
        players = pub.get("players", {})
        return {
            **pub,
            "table": self.no,
            "label": self.label,
            "black_winrate": ev["black_winrate"],
            "white_winrate": ev["white_winrate"],
            "score_lead": ev["score_lead"],
            "engine": ev["source"],
            "player_black": players.get("BLACK", "黑方"),
            "player_white": players.get("WHITE", "白方"),
            "status": self.status(),
            "vote": self.vote.to_dict() if self.vote else None,
            "black_team": self.black_team.to_dict() if self.black_team else None,
            "white_team": self.white_team.to_dict() if self.white_team else None,
            "history": self.history,
        }

    def brief(self) -> dict:
        pub = self.referee.to_public_dict()
        ev = self.winrate()
        return {
            "table": self.no,
            "label": self.label,
            "game_type": pub["game_type"],
            "game_name_cn": pub["game_name_cn"],
            "move_number": pub["move_number"],
            "to_play": pub["to_play"],
            "verdict": pub["verdict"],
            "verdict_cn": pub["verdict_cn"],
            "black_winrate": ev["black_winrate"],
            "status": self.status(),
            "player_black": pub.get("players", {}).get("BLACK", "黑方"),
            "player_white": pub.get("players", {}).get("WHITE", "白方"),
        }

    def status(self) -> str:
        if self.referee.game_over:
            return "finished"
        return "playing" if self.referee.rules.moves else "waiting"


class Tournament:
    def __init__(self, bus: Optional[EventBus] = None, default_time: Optional[TimeControl] = None):
        self.bus = bus or EventBus()
        self.tables: Dict[int, Table] = {}
        self.default_time = default_time or TimeControl(total=0, per_move=0)
        self._lock = threading.Lock()

    def create_table(self, no: int, game_type: GameType, size: Optional[int] = None,
                     black: str = "黑方", white: str = "白方",
                     black_team: Optional[TeamSide] = None,
                     white_team: Optional[TeamSide] = None,
                     label: str = "", evaluator=None, **rule_kwargs) -> Table:
        rules = create_rules(game_type, size, **rule_kwargs)
        ev = evaluator or make_evaluator()
        ref = Referee(rules, names={BLACK: black, WHITE: white},
                      time_control=self.default_time, events_sink=self.bus.publish)
        ref.table_no = no
        table = Table(no=no, referee=ref, evaluator=ev, black_team=black_team,
                      white_team=white_team, label=label or f"{no}号桌")
        with self._lock:
            self.tables[no] = table
        self.bus.publish({"type": "table_created", "table": no,
                          "payload": table.brief(), "ts": time.time()})
        return table

    def get(self, no: int) -> Optional[Table]:
        return self.tables.get(no)

    def remove_table(self, no: int) -> None:
        with self._lock:
            self.tables.pop(no, None)
        self.bus.publish({"type": "table_removed", "table": no, "payload": {}, "ts": time.time()})

    def snapshot(self) -> dict:
        return {"tables": [t.brief() for t in sorted(self.tables.values(), key=lambda x: x.no)]}

    def table_view(self, no: int) -> Optional[dict]:
        t = self.get(no)
        return t.view() if t else None

    # -------------------------------------------------------------- 落子包装
    def play(self, no: int, color: Color, x, y) -> Optional[dict]:
        t = self.get(no)
        if not t:
            return None
        outcome = t.referee.play(color, x, y)
        if outcome.accepted:
            t.record_winrate()
        self.bus.publish({"type": "state", "table": no,
                          "payload": t.view(), "ts": time.time()})
        return outcome.to_dict()