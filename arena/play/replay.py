"""棋谱回放：解析 SGF 棋谱并用规则引擎重建每一手的局面。

用于「棋谱回放」页面：把已保存的 SGF 逐手还原成棋盘快照，正确重现
围棋的提子、五子棋的落子、翻转棋的翻面等，供前端按手播放 / 拖动进度。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from ..model import Color, GameType
from ..rules import DEFAULT_SIZE, create_rules
from .record import resolve_record_path

Color = Color  # 便于类型注解阅读

_GM_TO_TYPE: Dict[str, GameType] = {
    "1": GameType.GO,
    "2": GameType.REVERSI,
    "4": GameType.GOMOKU,
}
_BACK = {GameType.GO: "1", GameType.REVERSI: "2", GameType.GOMOKU: "4"}

Coord = Optional[Tuple[int, int]]


def _as_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_nodes(text: str) -> List[Dict[str, List[str]]]:
    """把 SGF 文本解析成节点列表（每个节点是 ``{键: [值...]}``）。

    只处理主分支（不含变着），对离线生成的棋谱足够；同时能正确处理被转义
    的 ``\\]`` / ``\\\\``，因此属性值里的分号或方括号不会打断解析。
    """
    nodes: List[Dict[str, List[str]]] = []
    current: Optional[Dict[str, List[str]]] = None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == ";":
            current = {}
            nodes.append(current)
            i += 1
            continue
        if ch in "()":
            i += 1
            continue
        if ch.isalpha() or ch == ".":
            j = i
            while j < n and (text[j].isalpha() or text[j] == "."):
                j += 1
            key = text[i:j]
            i = j
            values: List[str] = []
            while i < n and text[i] == "[":
                i += 1
                buf: List[str] = []
                while i < n:
                    c = text[i]
                    if c == "\\" and i + 1 < n:
                        buf.append(text[i + 1])
                        i += 2
                        continue
                    if c == "]":
                        i += 1
                        break
                    buf.append(c)
                    i += 1
                values.append("".join(buf))
            if current is None:
                current = {}
                nodes.append(current)
            current.setdefault(key, []).extend(values)
            continue
        i += 1
    return nodes


def _decode_coord(value: str) -> Coord:
    s = (value or "").strip()
    if len(s) < 2:
        return None
    x = ord(s[0]) - ord("a")
    y = ord(s[1]) - ord("a")
    if x < 0 or y < 0:
        return None
    return (x, y)


def parse_sgf(text: str) -> Tuple[Dict[str, str], List[Tuple[Color, Coord]]]:
    """解析 SGF，返回 ``(顶层属性, 落子序列)``。

    ``落子序列`` 中每项为 ``(Color, (x, y) 或 None)``，``None`` 表示停一手。
    """
    nodes = _parse_nodes(text or "")
    root = nodes[0] if nodes else {}
    meta = {k: (v[0] if v else "") for k, v in root.items()}
    moves: List[Tuple[Color, Coord]] = []
    for node in nodes:
        if "B" in node and node["B"]:
            moves.append((Color.BLACK, _decode_coord(node["B"][0])))
        elif "W" in node and node["W"]:
            moves.append((Color.WHITE, _decode_coord(node["W"][0])))
    return meta, moves


def game_type_from_sgf(meta: Dict[str, str]) -> GameType:
    return _GM_TO_TYPE.get(str(meta.get("GM", "")).strip(), GameType.GO)


def build_replay(name: str, records_dir: Optional[str] = None,
                 include_frames: bool = True) -> Optional[dict]:
    """按棋谱文件名重建对局，返回前端可直接渲染的数据；文件不存在返回 None。

    ``include_frames`` 为 False 时只返回终局棋盘（用于列表页缩略图，体积更小）。
    """
    path = resolve_record_path(name, records_dir)
    if not path:
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    meta, moves = parse_sgf(text)
    game_type = game_type_from_sgf(meta)
    size = _as_int(meta.get("SZ"), 0) or DEFAULT_SIZE.get(game_type, 19)
    rules = create_rules(game_type, size=size)

    frames: List[dict] = []
    for index, (color, coord) in enumerate(moves, 1):
        if coord is None:
            rules.play_pass(color, enforce_turn=False)
        else:
            rules.play(color, coord[0], coord[1], enforce_turn=False)
        if include_frames:
            public = rules.to_public_dict()
            frames.append({
                "no": index,
                "color": color.name,
                "x": coord[0] if coord else None,
                "y": coord[1] if coord else None,
                "pass": coord is None,
                "board": public["board"],
                "captures": public["captures"],
            })

    final = rules.to_public_dict()
    return {
        "name": name,
        "record_url": "/api/records/" + quote(name),
        "game_type": game_type.value,
        "game_name_cn": game_type.name_cn,
        "size": size,
        "black": meta.get("PB") or "黑方",
        "white": meta.get("PW") or "白方",
        "result": meta.get("RE", ""),
        "date": meta.get("DT", ""),
        "code": meta.get("RO", ""),
        "komi": meta.get("KM", ""),
        "comment": meta.get("C", ""),
        "move_count": len(moves),
        "initial_board": [[0] * size for _ in range(size)],
        "final_board": final["board"],
        "captures": final["captures"],
        "moves": frames,
    }


__all__ = ["parse_sgf", "build_replay", "game_type_from_sgf"]
