"""硬件接入层：OLED/信号板显示 + 实体棋盘链路。

对应会议中的三种方案：
1. 树莓派本地算力          -> 直接在本机运行 evaluator
2. 电脑算力 + 蓝牙/串口     -> ``SerialBoardLink`` + ``OledDisplay``
3. WiFi 棋盘 / 主机        -> ``SocketBoardLink``（TCP JSON Lines）

无硬件时使用 Mock 实现，保证演示与测试可运行。
"""
from __future__ import annotations

import json
import socket
from typing import Dict, List, Optional


# ---------------------------------------------------------------------- 显示设备
class DisplayDevice:
    def show(self, view: dict) -> None:      # pragma: no cover - 接口
        raise NotImplementedError


class MemoryDisplay(DisplayDevice):
    """把最近一次画面缓存下来，便于测试与回放。"""

    def __init__(self):
        self.last: Optional[dict] = None
        self.frames: List[dict] = []

    def show(self, view: dict) -> None:
        self.last = view
        self.frames.append(view)


class ConsoleDisplay(DisplayDevice):
    def show(self, view: dict) -> None:
        b = view.get("black_winrate", 0.5)
        print(f"[胜率] 黑 {b*100:5.1f}% | 白 {(1-b)*100:5.1f}%  "
              f"第{view.get('move_number','?')}手 {view.get('verdict_cn','')}")


class OledDisplay(MemoryDisplay):
    """128x64 OLED 文本页面：适合树莓派/单片机显示胜率、手数、胜负。"""

    WIDTH, HEIGHT = 128, 64

    def render_lines(self, view: dict) -> List[str]:
        b = view.get("black_winrate", 0.5) or 0.5
        bar = int(round(b * 16))
        return [
            f"KataGo {view.get('source', '')[:8]}",
            f"黑 {b*100:4.1f}% 白 {(1-b)*100:4.1f}%",
            "[" + "#" * bar + "." * (16 - bar) + "]",
            f"手数 {view.get('move_number', 0)} {view.get('verdict_cn', '')}",
        ]

    def show(self, view: dict) -> None:
        super().show(view)
        if view.get("verbose"):
            for ln in self.render_lines(view):
                print("OLED|", ln)


# ---------------------------------------------------------------------- 棋盘链路
class BoardLink:
    def push(self, view: dict) -> None:      # pragma: no cover - 接口
        raise NotImplementedError

    def poll(self) -> Optional[dict]:        # pragma: no cover - 接口
        return None

    def close(self) -> None:
        pass


class MockBoardLink(BoardLink):
    def __init__(self, script: Optional[List[dict]] = None):
        self.sent: List[dict] = []
        self._inbox = list(script or [])

    def push(self, view: dict) -> None:
        self.sent.append(view)

    def poll(self) -> Optional[dict]:
        return self._inbox.pop(0) if self._inbox else None


class SocketBoardLink(BoardLink):
    """WiFi 棋盘：TCP JSON Lines 协议。

    协议（每行一个 JSON）：
        -> {"type":"state", "board":[[...]], "to_play":"BLACK", "winrate":0.62}
        <- {"type":"move", "x":3, "y":3} 或 {"type":"move", "pass":true}
    """

    def __init__(self, host: str, port: int = 9000, timeout: float = 2.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: Optional[socket.socket] = None
        self._buf = b""

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def push(self, view: dict) -> None:
        if not self.sock:
            self.connect()
        payload = json.dumps({"type": "state", "board": view.get("board"),
                              "to_play": view.get("to_play"),
                              "winrate": view.get("black_winrate"),
                              "move_number": view.get("move_number")}, ensure_ascii=False)
        assert self.sock
        self.sock.sendall((payload + "\n").encode("utf-8"))

    def poll(self) -> Optional[dict]:
        if not self.sock:
            return None
        try:
            data = self.sock.recv(4096)
        except (socket.timeout, OSError):
            return None
        if not data:
            return None
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if line.strip():
                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if msg.get("type") == "move":
                    return msg
        return None

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None


class SerialBoardLink(BoardLink):
    """蓝牙 SPP / 串口棋盘。需安装 pyserial 后使用。

    协议与 ``SocketBoardLink`` 相同（JSON Lines），仅底层传输不同。
    """

    def __init__(self, port: str, baudrate: int = 115200):
        self.port, self.baudrate = port, baudrate
        self.ser = None

    def _ensure(self):
        if self.ser is None:
            import serial  # 延迟导入，避免无依赖时导入失败
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.5)

    def push(self, view: dict) -> None:
        self._ensure()
        payload = json.dumps({"type": "state", "board": view.get("board"),
                              "to_play": view.get("to_play"),
                              "winrate": view.get("black_winrate")}, ensure_ascii=False)
        self.ser.write((payload + "\n").encode("utf-8"))

    def poll(self) -> Optional[dict]:
        self._ensure()
        raw = self.ser.readline()
        if not raw:
            return None
        try:
            msg = json.loads(raw.decode("utf-8").strip())
        except Exception:
            return None
        return msg if msg.get("type") == "move" else None

    def close(self) -> None:
        if self.ser:
            self.ser.close()
            self.ser = None


class HardwareHub:
    """把裁判 + 评估器 + 显示 + 棋盘链路串起来。"""

    def __init__(self, referee, evaluator, display: Optional[DisplayDevice] = None,
                 link: Optional[BoardLink] = None):
        self.referee = referee
        self.evaluator = evaluator
        self.display = display or MemoryDisplay()
        self.link = link

    def view(self) -> dict:
        pub = self.referee.to_public_dict()
        ev = self.evaluator.win_rate(self.referee.rules)
        evd = ev.to_dict()
        return {**pub, "black_winrate": evd["black_winrate"],
                "white_winrate": evd["white_winrate"],
                "score_lead": evd["score_lead"], "source": evd["source"]}

    def refresh(self) -> dict:
        v = self.view()
        self.display.show(v)
        if self.link:
            try:
                self.link.push(v)
            except Exception:
                pass
        return v