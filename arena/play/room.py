"""对弈房间：座位、对局码、人机对战。

一张棋桌（:class:`arena.tournament.Table`）被包装成一个"房间"：

* ``code``      4 位对局码（去掉了 I/O/0/1 等易混字符），局域网内口头或扫码分享
* ``seats``     黑方 / 白方座位，每个座位有一枚不可猜测的 ``token`` 作为身份凭证
* ``mode``      ``pvp`` 人人对战 / ``pve`` 人机对战

设计上刻意不与 :mod:`arena.venue.server` 耦合：房间只认识
``Tournament``，因此同一张桌既能开"对弈页"，也能开"家长观看页"。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..model import Color, GameType
from ..tournament import Table, Tournament
from .ai_player import HeuristicPlayer

BLACK, WHITE = Color.BLACK, Color.WHITE

#: 去掉 I / O / 0 / 1，避免口头报对局码时听错
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 4
MAX_ROOMS = 500


class PlayError(Exception):
    """对弈操作错误：座位已满、非本人操作、非法落点等。"""


def make_code(taken) -> str:
    """生成一个未被占用的对局码。"""
    for _ in range(500):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if code not in taken:
            return code
    raise PlayError("对局码已用尽，请关闭部分房间后重试")


def make_token() -> str:
    """座位凭证：只发给落座的那位棋手，用于校验操作权限。"""
    return secrets.token_urlsafe(12)


def parse_color(value) -> Optional[Color]:
    """把 ``BLACK`` / ``black`` / ``黑`` 统一解析为 :class:`Color`。"""
    if isinstance(value, Color):
        return value
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in ("BLACK", "B", "黑", "黑方", "执黑", "先手"):
        return BLACK
    if text in ("WHITE", "W", "白", "白方", "执白", "后手"):
        return WHITE
    return None


@dataclass
class Seat:
    """一个座位（一位棋手或一个 AI）。"""

    color: Color
    name: str
    token: str
    is_ai: bool = False
    is_host: bool = False
    joined_at: float = field(default_factory=time.time)

    def to_dict(self, with_token: bool = False) -> dict:
        data = {
            "color": self.color.name,
            "color_cn": self.color.name_cn,
            "name": self.name,
            "is_ai": self.is_ai,
            "is_host": self.is_host,
        }
        if with_token:
            data["token"] = self.token
        return data


@dataclass
class Room:
    """一个对弈房间 = 一张棋桌 + 两个座位 + 一枚对局码。"""

    code: str
    table: Table
    mode: str = "pvp"                     # pvp 人人 / pve 人机
    host_token: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    closed: bool = False
    seats: Dict[Color, Optional[Seat]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.seats = {BLACK: self.seats.get(BLACK), WHITE: self.seats.get(WHITE)}
        self._sync_names()

    # ------------------------------------------------------------------ 基本属性
    @property
    def no(self) -> int:
        """对应的桌号（对弈页与观看页共用）。"""
        return self.table.no

    @property
    def referee(self):
        return self.table.referee

    @property
    def game_over(self) -> bool:
        return self.referee.game_over

    def seat(self, color: Color) -> Optional[Seat]:
        return self.seats.get(color)

    def free_colors(self) -> List[Color]:
        return [c for c in (BLACK, WHITE) if self.seats.get(c) is None]

    @property
    def is_full(self) -> bool:
        return not self.free_colors()

    @property
    def status(self) -> str:
        if self.game_over:
            return "finished"
        if not self.is_full:
            return "waiting"
        return "playing" if self.referee.rules.moves else "ready"

    def seat_by_token(self, token: Optional[str]) -> Optional[Seat]:
        if not token:
            return None
        for seat in self.seats.values():
            if seat is not None and not seat.is_ai and seat.token == token:
                return seat
        return None

    def color_by_token(self, token: Optional[str]) -> Optional[Color]:
        seat = self.seat_by_token(token)
        return seat.color if seat else None

    # ------------------------------------------------------------------ 座位
    def join(self, color: Optional[Color], name: str = "") -> Seat:
        """落座；``color=None`` 表示自动选一个空位（黑先）。"""
        if self.game_over:
            raise PlayError("本局已结束，请新建对局")
        if self.is_full:
            raise PlayError("两个座位都已坐满，请换一桌或新建对局")
        if color is None:
            color = self.free_colors()[0]
        if color not in (BLACK, WHITE):
            raise PlayError("未知的执子颜色")
        if self.seats.get(color) is not None:
            raise PlayError(f"{color.name_cn}方座位已被占用")
        seat = Seat(color=color, name=(name or f"{color.name_cn}方").strip()[:16],
                    token=make_token(), is_host=self.host_token is None)
        self.seats[color] = seat
        if seat.is_host:
            self.host_token = seat.token
        self._sync_names()
        return seat

    def add_ai(self, color: Color, name: str = "AI·启发式") -> Seat:
        """在指定颜色上放一个 AI 对手。"""
        if self.seats.get(color) is not None:
            raise PlayError(f"{color.name_cn}方座位已被占用")
        seat = Seat(color=color, name=name, token="ai:" + secrets.token_hex(4), is_ai=True)
        self.seats[color] = seat
        self._sync_names()
        return seat

    def _sync_names(self) -> None:
        """把座位昵称同步给裁判，观赛页/终局汇总显示真实姓名。"""
        for color in (BLACK, WHITE):
            seat = self.seats.get(color)
            self.referee.names[color] = seat.name if seat else f"{color.name_cn}方"

    # ------------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "table": self.no,
            "mode": self.mode,
            "mode_cn": "人机对战" if self.mode == "pve" else "玩家对战",
            "status": self.status,
            "full": self.is_full,
            "closed": self.closed,
            "created_at": self.created_at,
            "move_number": len(self.referee.rules.moves),
            "free_colors": [c.name for c in self.free_colors()],
            "seats": {c.name: (self.seats[c].to_dict() if self.seats.get(c) else None)
                      for c in (BLACK, WHITE)},
        }

    def brief(self) -> dict:
        """大厅列表用的紧凑视图（含棋种、手数、胜率）。"""
        return {**self.table.brief(), **self.to_dict()}


class RoomManager:
    """对局房间管理：创建 / 加入 / 落子 / 停一手 / 认输。"""

    def __init__(self, tournament: Tournament, ai_player=None):
        self.tournament = tournament
        self.rooms: Dict[str, Room] = {}
        self._lock = threading.RLock()
        self._ai = ai_player or HeuristicPlayer()

    # ------------------------------------------------------------------ 查询
    def get(self, code: Optional[str]) -> Optional[Room]:
        if not code:
            return None
        return self.rooms.get(str(code).strip().upper())

    def require(self, code: Optional[str]) -> Room:
        room = self.get(code)
        if room is None or room.closed:
            raise PlayError("对局不存在或已关闭")
        return room

    def room_of_table(self, no: Optional[int]) -> Optional[Room]:
        for room in self.rooms.values():
            if room.no == no and not room.closed:
                return room
        return None

    def snapshot(self) -> dict:
        rooms = [r for r in self.rooms.values() if not r.closed]
        rooms.sort(key=lambda r: r.created_at, reverse=True)
        return {"rooms": [r.brief() for r in rooms]}

    def view(self, room: Room, token: Optional[str] = None) -> dict:
        """对弈页视图 = 棋桌公开状态 + 房间座位 + "我是谁"。"""
        base = self.tournament.table_view(room.no) or {}
        seat = room.seat_by_token(token)
        to_play = room.referee.rules.to_play
        return {
            **base,
            "code": room.code,
            "mode": room.mode,
            "mode_cn": room.to_dict()["mode_cn"],
            "room_status": room.status,
            "seats": room.to_dict()["seats"],
            "free_colors": [c.name for c in room.free_colors()],
            "joinable": bool(room.free_colors()) and not room.game_over,
            "viewer": {
                "seated": seat is not None,
                "color": seat.color.name if seat else None,
                "color_cn": seat.color.name_cn if seat else None,
                "name": seat.name if seat else None,
            },
            "can_move": bool(seat and not seat.is_ai and not room.game_over
                             and to_play is seat.color),
            "seat_tokens": None,        # 永不外泄
        }

    # ------------------------------------------------------------------ 创建 / 加入
    def _next_table_no(self) -> int:
        with self._lock:
            return (max(self.tournament.tables) + 1) if self.tournament.tables else 1

    def create(self, game_type: GameType, size: Optional[int] = None, mode: str = "pvp",
               host_name: str = "玩家", host_color: Color = BLACK,
               ai_name: str = "AI·启发式", label: str = "", **rule_kwargs
               ) -> Tuple[Room, Seat]:
        """新建房间：房主落座；人机模式下 AI 自动坐上另一侧。"""
        if mode not in ("pvp", "pve"):
            raise PlayError("未知对战模式")
        with self._lock:
            if len([r for r in self.rooms.values() if not r.closed]) >= MAX_ROOMS:
                raise PlayError("房间数量已达上限")
            code = make_code(self.rooms)
            no = self._next_table_no()
            table = self.tournament.create_table(
                no, game_type, size=size, black="黑方", white="白方",
                label=label or f"对局 {code}")
            room = Room(code=code, table=table, mode=mode)
            self.rooms[code] = room
        seat = room.join(host_color, host_name)
        if mode == "pve":
            room.add_ai(host_color.opposite, ai_name)
        self._publish(room)
        if mode == "pve":
            self.maybe_ai_move(room)        # AI 执黑时先行
        return room, seat

    def join(self, code: str, name: str = "", color=None) -> Tuple[Room, Seat]:
        room = self.require(code)
        with self._lock:
            seat = room.join(parse_color(color), name)
        self._publish(room)
        return room, seat

    def close(self, code: str) -> None:
        room = self.get(code)
        if room:
            room.closed = True
            self.tournament.remove_table(room.no)

    # ------------------------------------------------------------------ 对弈操作
    def _seat_or_fail(self, room: Room, token: Optional[str]) -> Seat:
        seat = room.seat_by_token(token)
        if seat is None:
            raise PlayError("你不在这个房间里：请先落座或换个浏览器重新加入")
        return seat

    def move(self, code: str, token: str, x: int, y: int) -> dict:
        room = self.require(code)
        seat = self._seat_or_fail(room, token)
        if room.game_over:
            raise PlayError("本局已结束")
        rules = room.referee.rules
        if not (0 <= int(x) < rules.size and 0 <= int(y) < rules.size):
            raise PlayError("落点越界")
        if rules.get(int(x), int(y)) is not Color.EMPTY:
            raise PlayError("该点已有棋子")
        if rules.to_play is not seat.color:
            raise PlayError("还没有轮到你落子")
        outcome = room.referee.play(seat.color, int(x), int(y))
        return self._after(room, outcome)

    def pass_turn(self, code: str, token: str) -> dict:
        room = self.require(code)
        seat = self._seat_or_fail(room, token)
        if room.game_over:
            raise PlayError("本局已结束")
        if room.referee.rules.to_play is not seat.color:
            raise PlayError("还没有轮到你")
        outcome = room.referee.play_pass(seat.color)
        return self._after(room, outcome)

    def resign(self, code: str, token: str) -> dict:
        room = self.require(code)
        seat = self._seat_or_fail(room, token)
        if room.game_over:
            raise PlayError("本局已结束")
        outcome = room.referee.resign(seat.color)
        return self._after(room, outcome)

    # ------------------------------------------------------------------ 人机
    def maybe_ai_move(self, room: Room) -> Optional[dict]:
        """若轮到 AI 且棋局未终，则让 AI 走一手。"""
        if room.game_over or room.mode != "pve":
            return None
        seat = room.seats.get(room.referee.rules.to_play)
        if seat is None or not seat.is_ai:
            return None
        point = self._ai.choose(room.referee.rules, seat.color)
        if point is None:
            outcome = room.referee.play_pass(seat.color)
        else:
            outcome = room.referee.play(seat.color, point[0], point[1])
            if not outcome.accepted:
                outcome = room.referee.play_pass(seat.color)
        if outcome.accepted:
            room.table.record_winrate()
        self._publish(room)
        return {"ai": True, "color": seat.color.name,
                "point": list(point) if point else None,
                "outcome": outcome.to_dict()}

    # ------------------------------------------------------------------ 内部
    def _after(self, room: Room, outcome) -> dict:
        if outcome.accepted:
            room.table.record_winrate()
        self._publish(room)
        payload = {
            "ok": outcome.accepted,
            "outcome": outcome.to_dict(),
            "room": room.to_dict(),
            "game_over": room.game_over,
            "summary": room.referee.summary() if room.game_over else None,
            "view": self.tournament.table_view(room.no),
        }
        ai = self.maybe_ai_move(room)
        if ai is not None:
            payload["ai_move"] = ai
            payload["summary"] = room.referee.summary() if room.game_over else None
            payload["view"] = self.tournament.table_view(room.no)
        return payload

    def _publish(self, room: Room) -> None:
        self.tournament.bus.publish({
            "type": "state", "table": room.no, "code": room.code,
            "payload": self.tournament.table_view(room.no), "ts": time.time(),
        })