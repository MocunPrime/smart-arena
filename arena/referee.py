"""裁判模块。

在 ``RuleSet`` 之上封装公平竞赛与赛事管理规定，落实会议要求：
* 非法着法弹窗 + 音效（由 UI/venue 层实现，本层给出事件）
* 犯规记录：第一次警告，第二次判负
* 记录弃权（谁先放弃）
* 终局小结：终局后汇总犯规、弃权顺序、最后一手、比分
* 计时：总时限 + 每手倒计时（超时按犯规处理）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .model import (
    Color,
    FoulRecord,
    FoulType,
    MoveResult,
    RESULT_TO_FOUL,
    Verdict,
)
from .rules.base import RuleSet

BLACK, WHITE = Color.BLACK, Color.WHITE


@dataclass
class PlayOutcome:
    result: MoveResult
    accepted: bool
    foul: Optional[FoulRecord] = None
    loss_by_foul: bool = False

    def to_dict(self) -> dict:
        return {
            "result": self.result.value,
            "accepted": self.accepted,
            "foul": self.foul.to_dict() if self.foul else None,
            "loss_by_foul": self.loss_by_foul,
        }


@dataclass
class TimeControl:
    """简单计时：total 为每方总时间，per_move 为每手限时。"""

    total: float = 0.0          # 0 表示不限
    per_move: float = 0.0       # 0 表示不限

    def to_dict(self) -> dict:
        return {"total": self.total, "per_move": self.per_move}

    @property
    def is_timed(self) -> bool:
        return self.total > 0 or self.per_move > 0


class Referee:
    def __init__(
        self,
        rules: RuleSet,
        names: Optional[Dict[Color, str]] = None,
        foul_limit: int = 2,
        time_control: Optional[TimeControl] = None,
        events_sink=None,
        time_fn: Optional[Callable[[], float]] = None,
    ):
        self.rules = rules
        self.names = names or {BLACK: "黑方", WHITE: "白方"}
        self.foul_limit = foul_limit
        self.time_control = time_control or TimeControl()
        self.fouls: List[FoulRecord] = []
        self.pass_order: List[Color] = []
        #: 弃权（停一手）明细：谁、在第几手、紧跟在谁的哪一手之后
        self.pass_log: List[dict] = []
        self.resign_color: Optional[Color] = None
        self._final: Optional[Verdict] = None
        self._time_fn = time_fn or time.time
        self.started_at = self._time_fn()
        self._events_sink = events_sink

        self.clock: Dict[Color, float] = {
            BLACK: self.time_control.total,
            WHITE: self.time_control.total,
        }
        self._last_tick = self._time_fn()
        self._turn_started = self._last_tick

    # ------------------------------------------------------------------ 事件
    def _emit(self, kind: str, payload: dict) -> None:
        if self._events_sink:
            try:
                self._events_sink({"type": kind, "table": getattr(self, "table_no", None),
                                   "payload": payload, "ts": time.time()})
            except Exception:
                pass

    # ------------------------------------------------------------------ 计时
    def tick(self) -> float:
        now = self._time_fn()
        elapsed = now - self._last_tick
        self._last_tick = now
        if self.game_over:
            return elapsed
        c = self.rules.to_play
        if self.time_control.total > 0:
            self.clock[c] = max(0.0, self.clock.get(c, 0.0) - elapsed)
        return elapsed

    def move_time_left(self) -> Optional[float]:
        """当前这一手的剩余时间；``per_move <= 0`` 表示不限时（返回 None）。"""
        if self.time_control.per_move <= 0:
            return None
        return max(0.0, self.time_control.per_move - (self._time_fn() - self._turn_started))

    def reset_move_clock(self) -> None:
        """把"每手倒计时"重置到当前时刻（落子 / 换手时调用）。"""
        self._turn_started = self._time_fn()

    def check_timeout(self) -> Optional[PlayOutcome]:
        """检查是否超时：总用时耗尽 = 直接判负；每手超时 = 记一次犯规。"""
        self.tick()
        if self.game_over:
            return None
        c = self.rules.to_play
        if self.time_control.total > 0 and self.clock.get(c, 0.0) <= 0:
            return self.lose_on_time(c, note="总用时耗尽")
        if self.time_control.per_move > 0 and self.move_time_left() <= 0:
            out = self.foul(c, FoulType.TIMEOUT, note="本手超时")
            self.reset_move_clock()
            return out
        return None

    # ------------------------------------------------------------------ 落子
    def play(self, color: Color, x: Optional[int], y: Optional[int],
             enforce_turn: bool = True) -> PlayOutcome:
        self.tick()
        result = self.rules.play(color, x, y, enforce_turn=enforce_turn)
        outcome = self._wrap(color, result, x, y)
        if outcome.accepted:
            self.reset_move_clock()
        return outcome

    def play_pass(self, color: Color) -> PlayOutcome:
        self.tick()
        result = self.rules.play_pass(color)
        if result is MoveResult.OK:
            self.reset_move_clock()
            record = self._pass_record(color)
            self.pass_log.append(record)
            self.pass_order.append(color)
            self._emit("pass", {"color": color.name,
                                "first_pass": self.pass_order[0].name,
                                "record": record})
        return self._wrap(color, result, None, None)

    def _pass_record(self, color: Color) -> dict:
        """记录这次弃权"是在谁的哪一手之后"发生的（供弃权查询）。"""
        moves = self.rules.moves
        pass_move = moves[-1] if moves else None          # play_pass 已把本手追加进 moves
        prev = moves[-2] if len(moves) >= 2 else None
        return {
            "order": len(self.pass_log) + 1,
            "color": color.name,
            "color_cn": color.name_cn,
            "move_no": pass_move.move_no if pass_move else len(moves),
            "after_move_no": prev.move_no if prev else None,
            "after_color": prev.color.name if prev else None,
            "after_color_cn": prev.color.name_cn if prev else None,
        }

    def _wrap(self, color: Color, result: MoveResult,
              x: Optional[int], y: Optional[int]) -> PlayOutcome:
        if result is MoveResult.OK:
            self._emit("move", {"color": color.name, "x": x, "y": y,
                                "move_no": len(self.rules.moves)})
            return PlayOutcome(result=result, accepted=True)
        if result in (MoveResult.NOT_YOUR_TURN, MoveResult.GAME_OVER):
            return PlayOutcome(result=result, accepted=False)
        foul_type = RESULT_TO_FOUL.get(result, FoulType.ILLEGAL_REVERSI)
        note = ""
        if result is MoveResult.FORBIDDEN and hasattr(self.rules, "forbidden_reason"):
            note = self.rules.forbidden_reason(color, x, y)
        return self.foul(color, foul_type, note=note, move_no=len(self.rules.moves))

    # ------------------------------------------------------------------ 犯规
    def foul(self, color: Color, foul_type: FoulType,
             note: str = "", move_no: Optional[int] = None) -> PlayOutcome:
        rec = FoulRecord(color=color, foul_type=foul_type,
                         move_no=(move_no if move_no is not None else len(self.rules.moves)),
                         note=note)
        self.fouls.append(rec)
        count = self.foul_count(color)
        loss = count >= self.foul_limit
        warning = count < self.foul_limit
        self._emit("foul", {"color": color.name, "type": foul_type.value,
                            "count": count, "limited": loss, "note": note})
        if loss:
            self._final = Verdict.WHITE_WIN if color is BLACK else Verdict.BLACK_WIN
            self.rules.game_over = True
            self._emit("verdict", {"verdict": self._final.value, "reason": "foul_limit"})
        return PlayOutcome(result=MoveResult.ILLEGAL, accepted=False,
                           foul=rec, loss_by_foul=loss)

    def lose_on_time(self, color: Color, note: str = "") -> PlayOutcome:
        """时间耗尽：直接判负（同时记一条犯规，便于终局汇总说明）。"""
        rec = FoulRecord(color=color, foul_type=FoulType.TIMEOUT,
                         move_no=len(self.rules.moves), note=note or "时间耗尽")
        self.fouls.append(rec)
        self._final = Verdict.WHITE_WIN if color is BLACK else Verdict.BLACK_WIN
        self.rules.game_over = True
        self._emit("foul", {"color": color.name, "type": FoulType.TIMEOUT.value,
                            "count": self.foul_count(color), "limited": True, "note": rec.note})
        self._emit("verdict", {"verdict": self._final.value, "reason": "timeout",
                               "color": color.name})
        return PlayOutcome(result=MoveResult.ILLEGAL, accepted=False, foul=rec,
                           loss_by_foul=True)

    def foul_count(self, color: Color) -> int:
        return sum(1 for f in self.fouls if f.color is color)

    # ------------------------------------------------------------------ 认输
    def resign(self, color: Color) -> PlayOutcome:
        """认输：对方获胜。

        会议要求终局汇总里能说明"谁先放弃 / 谁认输"，因此把认输方记进
        ``resign_color``，由 :meth:`summary` 一并输出。
        """
        if self.game_over:
            return PlayOutcome(result=MoveResult.GAME_OVER, accepted=False)
        self.resign_color = color
        self._final = Verdict.WHITE_WIN if color is BLACK else Verdict.BLACK_WIN
        self.rules.game_over = True
        self._emit("verdict", {"verdict": self._final.value, "reason": "resign",
                               "resigned": color.name})
        return PlayOutcome(result=MoveResult.OK, accepted=True)

    # ------------------------------------------------------------------ 状态
    def verdict(self) -> Verdict:
        return self._final if self._final is not None else self.rules.verdict()

    @property
    def game_over(self) -> bool:
        return self.rules.game_over or self._final is not None

    def summary(self) -> dict:
        """终局小结（会议：终局后弹窗汇总）。"""
        return {
            "game": self.rules.game_type.value,
            "game_name_cn": self.rules.game_type.name_cn,
            "players": {c.name: self.names.get(c, c.name_cn) for c in (BLACK, WHITE)},
            "verdict": self.verdict().value,
            "verdict_cn": self.verdict().name_cn,
            "move_number": len(self.rules.moves),
            "last_move": self.rules.last_move.to_dict() if self.rules.last_move else None,
            "first_pass": self.pass_order[0].name if self.pass_order else None,
            "resigned": self.resign_color.name if self.resign_color else None,
            "pass_order": [c.name for c in self.pass_order],
            "pass_log": [dict(r) for r in self.pass_log],
            "fouls": [f.to_dict() for f in self.fouls],
            "foul_counts": {BLACK.name: self.foul_count(BLACK),
                            WHITE.name: self.foul_count(WHITE)},
            "score": self.rules.score(),
        }

    def to_public_dict(self) -> dict:
        mtl = self.move_time_left()
        return {
            **self.rules.to_public_dict(),
            "players": {c.name: self.names.get(c, c.name_cn) for c in (BLACK, WHITE)},
            "verdict": self.verdict().value,
            "verdict_cn": self.verdict().name_cn,
            "fouls": [f.to_dict() for f in self.fouls],
            "foul_counts": {BLACK.name: self.foul_count(BLACK),
                            WHITE.name: self.foul_count(WHITE)},
            "first_pass": self.pass_order[0].name if self.pass_order else None,
            "pass_log": [dict(r) for r in self.pass_log],
            "resigned": self.resign_color.name if self.resign_color else None,
            "clock": {c.name: round(self.clock.get(c, 0.0), 1) for c in (BLACK, WHITE)},
            "time_control": self.time_control.to_dict(),
            "move_clock": (round(mtl, 1) if mtl is not None else None),
            "game_over": self.game_over,
        }