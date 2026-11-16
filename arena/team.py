"""团队赛制与投票模块（会议中的 "足球制" 玩法）。

要点：
* 分阶段上场：开局（前锋）→ 中盘（中场）→ 收官（后卫）
* 加权投票：队长、嘉宾权重更高，且可随时调整
* 限时投票：到期未决策 -> 提醒队长 -> 仍不决策则按权重最高的点强制落子
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import Color
from .referee import Referee

Coord = Tuple[int, int]

ROLE_FORWARD = "forward"
ROLE_MIDFIELD = "midfield"
ROLE_DEFENDER = "defender"
ROLE_MEMBER = "member"

ROLE_CN = {
    ROLE_FORWARD: "前锋",
    ROLE_MIDFIELD: "中场",
    ROLE_DEFENDER: "后卫",
    ROLE_MEMBER: "队员",
}


@dataclass
class Member:
    name: str
    role: str = ROLE_MEMBER
    weight: float = 1.0
    is_captain: bool = False
    is_guest: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "role_cn": ROLE_CN.get(self.role, self.role),
                "weight": self.weight, "is_captain": self.is_captain, "is_guest": self.is_guest}


@dataclass
class PhaseRule:
    name: str
    until_move: int          # 本阶段负责到的最大手数（含）
    active: List[str]        # 本阶段上场队员姓名


@dataclass
class TeamSide:
    name: str
    members: List[Member]
    phases: List[PhaseRule] = field(default_factory=list)

    def member(self, name: str) -> Member:
        for m in self.members:
            if m.name == name:
                return m
        raise KeyError(name)

    def captain(self) -> Optional[Member]:
        for m in self.members:
            if m.is_captain:
                return m
        return None

    def active_members(self, move_no: int) -> List[Member]:
        if not self.phases:
            return list(self.members)
        for phase in sorted(self.phases, key=lambda p: p.until_move):
            if move_no <= phase.until_move:
                return [self.member(n) for n in phase.active if any(m.name == n for m in self.members)]
        return [self.member(n) for n in self.phases[-1].active if any(m.name == n for m in self.members)]

    def phase_name(self, move_no: int) -> str:
        if not self.phases:
            return "全程"
        for phase in sorted(self.phases, key=lambda p: p.until_move):
            if move_no <= phase.until_move:
                return phase.name
        return self.phases[-1].name

    def set_weight(self, name: str, weight: float) -> None:
        self.member(name).weight = float(weight)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "members": [m.to_dict() for m in self.members],
            "phases": [{"name": p.name, "until_move": p.until_move, "active": p.active}
                       for p in self.phases],
        }


@dataclass
class Vote:
    member: str
    coord: Coord
    weight: float


class VotingSession:
    """一次限时投票。"""

    def __init__(self, side: TeamSide, color: Color, move_no: int,
                 timeout_s: float = 60.0, remind_at_s: float = 30.0,
                 candidates: Optional[List[Coord]] = None,
                 now: Optional[float] = None):
        self.side = side
        self.color = color
        self.move_no = move_no
        self.timeout_s = timeout_s
        self.remind_at_s = remind_at_s
        self.candidates = candidates or []
        self.votes: List[Vote] = []
        self.captain_pick: Optional[Coord] = None
        self.captain_pick_by: Optional[str] = None
        self.started_at = now if now is not None else time.time()
        self.reminded = False
        self.resolved = False

    # ------------------------------------------------------------------ 投票
    def cast(self, member_name: str, coord: Coord, weight: Optional[float] = None) -> None:
        m = self.side.member(member_name)
        if self.candidates and coord not in self.candidates:
            raise ValueError(f"落点 {coord} 不在候选范围内")
        if weight is None:
            weight = m.weight
        self.votes.append(Vote(member_name, coord, weight))

    def captain_choose(self, coord: Coord, by: Optional[str] = None) -> None:
        cap = self.side.captain()
        self.captain_pick = coord
        self.captain_pick_by = by or (cap.name if cap else None)

    # ------------------------------------------------------------------ 统计
    def tally(self) -> List[dict]:
        acc: Dict[Coord, dict] = {}
        for v in self.votes:
            d = acc.setdefault(v.coord, {"coord": v.coord, "weight": 0.0, "count": 0,
                                         "voters": []})
            d["weight"] += v.weight
            d["count"] += 1
            d["voters"].append(v.member)
        ranking = sorted(acc.values(), key=lambda d: (-d["weight"], -d["count"], d["coord"]))
        for i, d in enumerate(ranking, 1):
            d["rank"] = i
        return ranking

    def forced_point(self) -> Optional[Coord]:
        ranking = self.tally()
        return ranking[0]["coord"] if ranking else None

    def elapsed(self, now: Optional[float] = None) -> float:
        return (now if now is not None else time.time()) - self.started_at

    def remaining(self, now: Optional[float] = None) -> float:
        return max(0.0, self.timeout_s - self.elapsed(now))

    def should_remind(self, now: Optional[float] = None) -> bool:
        return (not self.reminded) and self.remaining(now) <= self.remind_at_s

    def is_expired(self, now: Optional[float] = None) -> bool:
        return self.remaining(now) <= 0.0

    # ------------------------------------------------------------------ 决策
    def resolve(self, now: Optional[float] = None) -> dict:
        """返回最终落点与决策方式。

        mode: captain（队长决定）/ forced（超时强制）/ pending（尚未决策）
        """
        ranking = self.tally()
        if self.captain_pick is not None:
            self.resolved = True
            return {"point": list(self.captain_pick), "mode": "captain",
                    "by": self.captain_pick_by, "ranking": ranking, "remaining": 0.0}
        if self.is_expired(now):
            pt = self.forced_point()
            self.resolved = True
            return {"point": list(pt) if pt else None, "mode": "forced",
                    "by": None, "ranking": ranking, "remaining": 0.0}
        return {"point": None, "mode": "pending", "by": None,
                "ranking": ranking, "remaining": self.remaining(now)}

    def to_dict(self, now: Optional[float] = None) -> dict:
        return {
            "side": self.side.name,
            "color": self.color.name,
            "move_no": self.move_no,
            "timeout_s": self.timeout_s,
            "remaining": round(self.remaining(now), 1),
            "reminded": self.reminded,
            "captain_pick": list(self.captain_pick) if self.captain_pick else None,
            "ranking": self.tally(),
            "votes": [{"member": v.member, "coord": list(v.coord), "weight": v.weight}
                      for v in self.votes],
        }


# ---------------------------------------------------------------------- 演示用默认名册
def demo_side(name: str, captain_weight: float = 3.0, guest_weight: float = 2.0) -> TeamSide:
    members = [
        Member(f"{name}-队长", ROLE_FORWARD, weight=captain_weight, is_captain=True),
        Member(f"{name}-前锋A", ROLE_FORWARD, weight=1.0),
        Member(f"{name}-前锋B", ROLE_FORWARD, weight=1.0),
        Member(f"{name}-中场A", ROLE_MIDFIELD, weight=1.0),
        Member(f"{name}-中场B", ROLE_MIDFIELD, weight=1.0),
        Member(f"{name}-嘉宾", ROLE_MIDFIELD, weight=guest_weight, is_guest=True),
        Member(f"{name}-后卫A", ROLE_DEFENDER, weight=1.0),
        Member(f"{name}-后卫B", ROLE_DEFENDER, weight=1.0),
    ]
    phases = [
        PhaseRule("开局(前锋)", 40, [f"{name}-队长", f"{name}-前锋A", f"{name}-前锋B"]),
        PhaseRule("中盘(中场)", 160, [f"{name}-中场A", f"{name}-中场B", f"{name}-嘉宾"]),
        PhaseRule("收官(后卫)", 9999, [f"{name}-后卫A", f"{name}-后卫B"]),
    ]
    return TeamSide(name, members, phases)