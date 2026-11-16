"""对弈房间：座位、对局码、人机对战。

一张棋桌（:class:`arena.tournament.Table`）被包装成一个"房间"：

* ``code``      4 位对局码（去掉了 I/O/0/1 等易混字符），局域网内口头或扫码分享
* ``seats``     黑方 / 白方座位，每个座位有一枚不可猜测的 ``token`` 作为身份凭证
* ``mode``      ``pvp`` 人人对战 / ``pve`` 人机对战

设计上刻意不与 :mod:`arena.venue.server` 耦合：房间只认识
``Tournament``，因此同一张桌既能开"对弈页"，也能开"家长观看页"。
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..model import Color, GameType
from ..referee import TimeControl
from ..tournament import Table, Tournament
from .ai_player import HeuristicPlayer
from .record import (
    default_records_dir,
    find_record_for_code,
    list_records,
    resolve_record_path,
    save_room_record,
)

BLACK, WHITE = Color.BLACK, Color.WHITE

#: 去掉 I / O / 0 / 1，避免口头报对局码时听错
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 4
MAX_ROOMS = 500
DEFAULT_IDLE_TIMEOUT = 1800.0          # 默认 30 分钟无操作自动关闭
DEFAULT_SWEEP_INTERVAL = 30.0           # 后台巡检间隔
DEFAULT_TICK_INTERVAL = 1.0             # 计时巡检间隔（检查每手/总用时超时）

#: 房间关闭原因 -> 面向棋手的中文提示
CLOSE_REASON_TEXT = {
    "manual": "房间已由棋手关闭",
    "inactivity": "房间因长时间无人操作已自动关闭",
    "game_over": "对局已结束",
}


def close_reason_text(reason) -> str:
    """把关闭原因翻译成中文提示。"""
    return CLOSE_REASON_TEXT.get(str(reason or ""), "房间已关闭")


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
    last_activity: float = field(default_factory=time.monotonic)
    closed_at: Optional[float] = None
    closed_reason: str = ""
    record_path: str = ""
    record_saved_at: Optional[float] = None
    record_error: str = ""
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
            "closed_at": self.closed_at,
            "closed_reason": self.closed_reason,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "record_saved": bool(self.record_path and os.path.isfile(self.record_path)),
            "record_saved_at": self.record_saved_at,
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

    def __init__(self, tournament: Tournament, ai_player=None,
                 idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
                 records_dir: Optional[str] = None,
                 auto_sweep: bool = True,
                 sweep_interval: float = DEFAULT_SWEEP_INTERVAL,
                 time_control: Optional[TimeControl] = None,
                 tick_interval: float = DEFAULT_TICK_INTERVAL,
                 clock=time.monotonic):
        self.tournament = tournament
        self.rooms: Dict[str, Room] = {}
        self._lock = threading.RLock()
        self._ai = ai_player or HeuristicPlayer()
        self.idle_timeout = max(0.0, float(idle_timeout or 0.0))
        self.records_dir = os.path.abspath(records_dir or default_records_dir())
        self._clock = clock
        self.time_control = time_control
        self._sweep_interval = max(1.0, float(sweep_interval or DEFAULT_SWEEP_INTERVAL))
        self._tick_interval = max(0.2, float(tick_interval or DEFAULT_TICK_INTERVAL))
        self._stop = threading.Event()
        self._reaper: Optional[threading.Thread] = None
        self._ticker: Optional[threading.Thread] = None
        if auto_sweep and self.idle_timeout > 0:
            self._reaper = threading.Thread(
                target=self._reaper_loop, daemon=True, name="smart-arena-reaper")
            self._reaper.start()
        if auto_sweep:
            self._ticker = threading.Thread(
                target=self._ticker_loop, daemon=True, name="smart-arena-clock")
            self._ticker.start()

    def touch(self, room: Room) -> None:
        """记录一次有效活动，用于房间空闲超时判断。"""
        room.last_activity = self._clock()

    def idle_remaining(self, room: Room) -> Optional[float]:
        if self.idle_timeout <= 0:
            return None
        return max(0.0, self.idle_timeout - (self._clock() - room.last_activity))

    def shutdown(self) -> None:
        self._stop.set()
        for th in (self._reaper, self._ticker):
            if th and th.is_alive():
                th.join(timeout=1.0)

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
        return {"rooms": [r.brief() for r in rooms],
                "idle_timeout": self.idle_timeout}

    def records(self, limit: int = 100) -> dict:
        return {"records": list_records(self.records_dir, limit=limit)}

    def resolve_record(self, name: str) -> str:
        return resolve_record_path(name, self.records_dir)

    def record_file_path(self, code: str) -> str:
        room = self.get(code)
        if room and room.record_path and os.path.isfile(room.record_path):
            return room.record_path
        row = find_record_for_code(code, self.records_dir)
        if row:
            return resolve_record_path(row.get("name", ""), self.records_dir)
        return ""

    def sweep_idle(self, now: Optional[float] = None) -> list:
        """关闭所有超过 idle_timeout 未活动的房间，返回被关闭的房间码。"""
        if self.idle_timeout <= 0:
            return []
        now = self._clock() if now is None else float(now)
        with self._lock:
            expired = [r for r in list(self.rooms.values())
                       if not r.closed and (now - r.last_activity) >= self.idle_timeout]
        for room in expired:
            self._close_room(room, reason="inactivity", at=now)
        return [r.code for r in expired]

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
            "idle_timeout": self.idle_timeout,
            "idle_remaining": self.idle_remaining(room),
            "closed_reason": room.closed_reason,
            "record_url": (f"/api/room/{room.code}/record"
                           if room.record_path and os.path.isfile(room.record_path) else None),
        }

    # ------------------------------------------------------------------ 创建 / 加入
    def _next_table_no(self) -> int:
        with self._lock:
            return (max(self.tournament.tables) + 1) if self.tournament.tables else 1

    def create(self, game_type: GameType, size: Optional[int] = None, mode: str = "pvp",
               host_name: str = "玩家", host_color: Color = BLACK,
               ai_name: str = "AI·启发式", label: str = "",
               time_control: Optional[TimeControl] = None, **rule_kwargs
               ) -> Tuple[Room, Seat]:
        """新建房间：房主落座；人机模式下 AI 自动坐上另一侧。"""
        if mode not in ("pvp", "pve"):
            raise PlayError("未知对战模式")
        with self._lock:
            if len([r for r in self.rooms.values() if not r.closed]) >= MAX_ROOMS:
                raise PlayError("房间数量已达上限")
            code = make_code(self.rooms)
            no = self._next_table_no()
            eff_time = time_control if time_control is not None else self.time_control
            if eff_time is None:
                eff_time = self.tournament.default_time
            table = self.tournament.create_table(
                no, game_type, size=size, black="黑方", white="白方",
                label=label or f"对局 {code}", time_control=eff_time)
            room = Room(code=code, table=table, mode=mode)
            self.touch(room)
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
        self.touch(room)
        self._publish(room)
        return room, seat

    def close(self, code: str, reason: str = "manual") -> bool:
        room = self.get(code)
        if room:
            return self._close_room(room, reason=reason)
        return False

    # ------------------------------------------------------------------ 对弈操作
    def _seat_or_fail(self, room: Room, token: Optional[str]) -> Seat:
        seat = room.seat_by_token(token)
        if seat is None:
            raise PlayError("你不在这个房间里：请先落座或换个浏览器重新加入")
        return seat

    def move(self, code: str, token: str, x: int, y: int) -> dict:
        room = self.require(code)
        seat = self._seat_or_fail(room, token)
        self.touch(room)
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
        self.touch(room)
        if room.game_over:
            raise PlayError("本局已结束")
        if room.referee.rules.to_play is not seat.color:
            raise PlayError("还没有轮到你")
        outcome = room.referee.play_pass(seat.color)
        return self._after(room, outcome)

    def resign(self, code: str, token: str) -> dict:
        room = self.require(code)
        seat = self._seat_or_fail(room, token)
        self.touch(room)
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
            self.touch(room)
            room.table.record_winrate()
        if room.game_over:
            self._save_record(room, reason="game_over")
        self._publish(room)
        return {"ai": True, "color": seat.color.name,
                "point": list(point) if point else None,
                "outcome": outcome.to_dict()}

    # ------------------------------------------------------------------ 内部
    def _after(self, room: Room, outcome) -> dict:
        if outcome.accepted:
            self.touch(room)
            room.table.record_winrate()
        if room.game_over:
            self._save_record(room, reason="game_over")
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

    # ------------------------------------------------------------------ 保存 / 关闭
    def _save_record(self, room: Room, reason: str = "",
                     now: Optional[float] = None) -> str:
        """把棋局写成 SGF 棋谱并返回路径（幂等：已保存过则直接复用）。"""
        try:
            return save_room_record(room, records_dir=self.records_dir,
                                    reason=reason, now=now) or ""
        except Exception as exc:                      # pragma: no cover - 兜底
            room.record_error = str(exc)
            return ""

    def _publish_closed(self, room: Room) -> None:
        """广播 room_closed 事件：前端据此提示“房间已关闭 + 下载棋谱”。"""
        record_url = (f"/api/room/{room.code}/record"
                      if room.record_path and os.path.isfile(room.record_path) else None)
        self.tournament.bus.publish({
            "type": "room_closed", "table": room.no, "code": room.code,
            "payload": {
                "code": room.code,
                "reason": room.closed_reason,
                "message": close_reason_text(room.closed_reason),
                "closed_at": room.closed_at,
                "record_saved": bool(record_url),
                "record_url": record_url,
            },
            "ts": time.time(),
        })

    def _close_room(self, room: Room, reason: str = "manual",
                    at: Optional[float] = None) -> bool:
        """关闭房间：保存棋谱、广播事件、移除棋桌。已关闭则返回 False。"""
        with self._lock:
            if room.closed:
                return False
            room.closed = True
            room.closed_reason = reason or "manual"
            room.closed_at = float(at) if at is not None else time.time()
        self._save_record(room, reason=room.closed_reason)
        self._publish_closed(room)
        with self._lock:
            self.tournament.remove_table(room.no)
        return True

    def _reaper_loop(self) -> None:
        """后台巡检线程：定时关闭空闲超时的房间。"""
        while not self._stop.wait(self._sweep_interval):
            try:
                self.sweep_idle()
            except Exception:                          # pragma: no cover - 兜底
                pass

    def _ticker_loop(self) -> None:
        """后台计时线程：定时检查每手/总用时，超时按犯规或判负处理。"""
        while not self._stop.wait(self._tick_interval):
            try:
                self.tick_rooms()
            except Exception:                          # pragma: no cover - 兜底
                pass

    def tick_rooms(self, now: Optional[float] = None) -> list:
        """对所有进行中的房间做一次计时检查。

        返回 ``[(对局码, PlayOutcome), ...]``：

        * 总用时耗尽 -> 直接判负（记一条犯规，终局汇总可解释原因）
        * 每手倒计时耗尽 -> 记一次犯规（累计两次由裁判判负）
        """
        results = []
        with self._lock:
            rooms = [r for r in self.rooms.values() if not r.closed]
        for room in rooms:
            if room.game_over:
                continue
            try:
                outcome = room.referee.check_timeout()
            except Exception:                      # pragma: no cover - 兜底
                continue
            if outcome is None:
                continue
            results.append((room.code, outcome))
            try:
                room.table.record_winrate()
            except Exception:
                pass
            if room.game_over:
                self._save_record(room, reason="game_over")
            self._publish(room)
        return results
