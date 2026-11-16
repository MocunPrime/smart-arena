"""棋谱保存：把一局对局写成标准 SGF 文件。

无论棋局是正常终局、认输、两次犯规判负，还是在房间关闭/空闲超时关闭时，
都可以调用 :func:`save_room_record` 保存一份棋谱。SGF 文件采用 UTF-8，
文件名中带房间码和时间，避免覆盖。
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

_SAVE_LOCK = threading.Lock()

_GAME_ID = {"go": "1", "gomoku": "4", "reversi": "2"}


def default_records_dir() -> str:
    """返回默认棋谱目录。

    源码运行时放在仓库根目录的 ``records``；打包后的 exe 放在 exe 同级的
    ``records``。也可以通过 ``SMART_ARENA_RECORDS_DIR`` 覆盖。
    """
    override = os.environ.get("SMART_ARENA_RECORDS_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "records")


def _sgf_escape(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _sgf_coord(x: Optional[int], y: Optional[int]) -> str:
    if x is None or y is None:
        return ""
    try:
        return chr(ord("a") + int(x)) + chr(ord("a") + int(y))
    except (TypeError, ValueError):
        return ""


def _result_text(room) -> str:
    if not room.game_over:
        return "Void"
    verdict = room.referee.verdict().value
    if verdict == "black_win":
        return "B+R" if room.referee.resign_color is not None else "B+"
    if verdict == "white_win":
        return "W+R" if room.referee.resign_color is not None else "W+"
    if verdict == "draw":
        return "0"
    return "Void"


def _close_note(room, reason: str) -> str:
    pieces = []
    if reason:
        pieces.append("关闭原因=" + str(reason))
    if getattr(room, "closed_reason", ""):
        pieces.append("房间状态=" + str(room.closed_reason))
    summary = room.referee.summary()
    if summary.get("first_pass"):
        pieces.append("第一个弃权方=" + str(summary["first_pass"]))
    if summary.get("resigned"):
        pieces.append("认输方=" + str(summary["resigned"]))
    if summary.get("fouls"):
        pieces.append("犯规次数=" + str(len(summary["fouls"])))
    if getattr(room, "record_error", ""):
        pieces.append("保存提示=" + str(room.record_error))
    return "；".join(pieces)


def room_to_sgf(room, reason: str = "", now: Optional[float] = None) -> str:
    """生成一局棋的 SGF 文本（不落盘）。"""
    now = float(time.time() if now is None else now)
    rules = room.referee.rules
    summary = room.referee.summary()
    players = summary.get("players", {})
    gt = rules.game_type.value
    props = [
        ("GM", _GAME_ID.get(gt, "1")),
        ("FF", "4"),
        ("CA", "UTF-8"),
        ("AP", "SmartArena"),
        ("GN", "SmartArena " + room.code),
        ("RO", room.code),
        ("EV", "局域网线上对弈"),
        ("DT", datetime.fromtimestamp(now).strftime("%Y-%m-%d")),
        ("SZ", str(rules.size)),
        ("PB", players.get("BLACK", "黑方")),
        ("PW", players.get("WHITE", "白方")),
        ("RE", _result_text(room)),
        ("C", _close_note(room, reason)),
    ]
    if gt == "go":
        props.extend([("KM", str(rules.komi)), ("RU", "Chinese Area")])
    else:
        props.append(("KM", "0"))
    root = "".join(f"{k}[{_sgf_escape(v)}]" for k, v in props)
    nodes = []
    color_key = {"BLACK": "B", "WHITE": "W"}
    for move in rules.moves:
        key = color_key.get(move.color.name, "B")
        nodes.append(f";{key}[{_sgf_coord(move.x, move.y)}]")
    return "(;" + root + "".join(nodes) + ")\n"


def save_room_record(room, records_dir: Optional[str] = None,
                     reason: str = "", now: Optional[float] = None) -> str:
    """保存一局棋的 SGF 棋谱，返回文件路径；失败时返回空字符串。

    该函数是幂等的：如果 ``room.record_path`` 已经指向存在的文件，不会重复保存。
    """
    old_path = getattr(room, "record_path", "") or ""
    if old_path and os.path.isfile(old_path):
        return old_path
    now = float(time.time() if now is None else now)
    directory = os.path.abspath(records_dir or default_records_dir())
    code = re.sub(r"[^A-Za-z0-9_-]", "", str(getattr(room, "code", "room"))) or "room"
    stamp = datetime.fromtimestamp(now)
    filename = f"{stamp:%Y%m%d-%H%M%S}-{stamp.microsecond:06d}_{code}.sgf"
    path = os.path.join(directory, filename)
    try:
        os.makedirs(directory, exist_ok=True)
        text = room_to_sgf(room, reason=reason, now=now)
        with _SAVE_LOCK:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        room.record_path = path
        room.record_saved_at = now
        room.record_error = None
        return path
    except Exception as exc:                     # pragma: no cover - 磁盘异常
        try:
            room.record_error = str(exc)
        except Exception:
            pass
        return ""


def _unescape(text: str) -> str:
    return text.replace("\\]", "]").replace("\\\\", "\\")


def _first_prop(text: str, key: str) -> str:
    match = re.search(r"(?:^|[;\s\]])" + re.escape(key) + r"\[((?:\\.|[^\]])*)\]", text)
    return _unescape(match.group(1)) if match else ""


def list_records(records_dir: Optional[str] = None, limit: int = 100) -> list:
    """列出棋谱目录中的 SGF 文件（不含解答/执子凭证等敏感信息）。"""
    directory = os.path.abspath(records_dir or default_records_dir())
    if not os.path.isdir(directory):
        return []
    rows = []
    try:
        names = [n for n in os.listdir(directory) if n.lower().endswith(".sgf")]
    except OSError:
        return []
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(4096)
        except OSError:
            continue
        gt = _first_prop(text, "GM")
        game_type = {"1": "go", "2": "reversi", "4": "gomoku"}.get(gt, "unknown")
        rows.append({
            "name": name,
            "size": st.st_size,
            "modified": st.st_mtime,
            "game_type": game_type,
            "code": _first_prop(text, "RO"),
            "date": _first_prop(text, "DT"),
            "result": _first_prop(text, "RE"),
            "black": _first_prop(text, "PB"),
            "white": _first_prop(text, "PW"),
            "size_label": _first_prop(text, "SZ"),
            "download_url": "/api/records/" + quote(name),
        })
    rows.sort(key=lambda r: r.get("modified", 0), reverse=True)
    return rows[:max(0, int(limit))]


def resolve_record_path(name: str, records_dir: Optional[str] = None) -> str:
    """安全解析棋谱文件名；拒绝路径穿越。"""
    safe = os.path.basename(str(name or ""))
    if safe != str(name or "") or not safe.lower().endswith(".sgf"):
        return ""
    directory = os.path.abspath(records_dir or default_records_dir())
    path = os.path.abspath(os.path.join(directory, safe))
    if os.path.dirname(path) != directory:
        return ""
    return path if os.path.isfile(path) else ""


def find_record_for_code(code: str, records_dir: Optional[str] = None) -> dict:
    """在已保存棋谱中按房间码找最近一份，供服务重启后下载。"""
    wanted = str(code or "").upper()
    for row in list_records(records_dir, limit=10000):
        if str(row.get("code", "")).upper() == wanted:
            return row
    return {}
