"""线上对弈（Online Play）。

把 ``tournament`` 里的一张棋桌封装成"局域网内可加入的房间"：

* 4 位对局码，手机/电脑输入即可加入
* 黑 / 白落座，支持人人对战与人机对战
* 走子 / 停一手(pass) / 认输 / 终局汇总
* 复用 :class:`arena.referee.Referee` 的犯规判定与"两次判负"

对弈页与智慧赛场观看页读取同一张 :class:`arena.tournament.Table`，
因此家长扫码看到的，就是棋手正在下的那一盘（实时同步）。
"""
from .record import (
    default_records_dir,
    find_record_for_code,
    list_records,
    resolve_record_path,
    room_to_sgf,
    save_room_record,
)
from .room import (
    PlayError,
    close_reason_text,
    Room,
    RoomManager,
    Seat,
    make_code,
    make_token,
    parse_color,
)

__all__ = [
    "Room",
    "RoomManager",
    "Seat",
    "PlayError",
    "make_code",
    "make_token",
    "parse_color",
    "close_reason_text",
    "default_records_dir",
    "find_record_for_code",
    "list_records",
    "resolve_record_path",
    "room_to_sgf",
    "save_room_record",
]