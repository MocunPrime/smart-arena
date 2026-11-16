"""智慧赛场：局域网观看服务（家长扫码 → 按桌号看棋）。"""
from __future__ import annotations

from .server import VenueServer, build_server

__all__ = ["VenueServer", "build_server"]