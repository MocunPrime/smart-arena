"""二维码生成（基于纯 Python 的 segno，无外部二进制依赖）。"""
from __future__ import annotations

import base64
import io
from typing import Optional

try:
    import segno
except Exception:      # pragma: no cover
    segno = None


def _make(data: str):
    if segno is None:
        raise RuntimeError("未安装 segno，请先 pip install segno")
    return segno.make(data, error="m")


def qr_svg(data: str, scale: int = 6, border: int = 2) -> Optional[str]:
    if segno is None:
        return None
    buf = io.BytesIO()
    _make(data).save(buf, kind="svg", scale=scale, border=border)
    return buf.getvalue().decode("utf-8")


def qr_png_data_uri(data: str, scale: int = 8, border: int = 2) -> Optional[str]:
    if segno is None:
        return None
    buf = io.BytesIO()
    _make(data).save(buf, kind="png", scale=scale, border=border)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def qr_ascii(data: str) -> str:
    if segno is None:
        return "[segno 未安装]"
    q = _make(data)
    return q.terminal(compact=True)