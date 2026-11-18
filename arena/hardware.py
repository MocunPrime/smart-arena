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

from .hardware_log import HardwareLog


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

# ---------------------------------------------------------------------- OLED（SSD1306）
import threading as _threading

from .oled import (Framebuffer, I2CTransport, OLEDError, RecordingTransport,
                   SSD1306, SerialOledTransport, render_winrate_frame)


class Ssd1306Display(MemoryDisplay):
    """把胜率渲染到 SSD1306（0.91"/0.96"，128x32 或 128x64，I2C）。

    与 :class:`OledDisplay`（纯文本 / 控制台）不同，本类**真正驱动硬件**：把房间视图
    渲染成 1bpp 位图，再经 ``transport``（本机 I2C / 串口桥 / 录制）下发到屏幕。
    任何硬件异常都会被吞掉并记录到 ``self.error``，绝不打断正在进行的对局。
    """

    def __init__(self, transport=None, width: int = 128, height: int = 32,
                 address: int = 0x3C, auto_init: bool = True,
                 log: Optional[HardwareLog] = None, log_spec: Optional[str] = None):
        super().__init__()
        self.transport = transport if transport is not None else RecordingTransport()
        self.driver = SSD1306(self.transport, width=width, height=height, address=address)
        self._lock = _threading.Lock()
        self._log = log
        self._log_spec = (log_spec or "").strip()
        self._last_error: Optional[str] = None
        self.error: Optional[str] = None
        if self._log and self._log_spec:
            self._log.connection_attempt(self._log_spec)
        if auto_init:
            self._safe(self.driver.init, event="connect")

    def _safe(self, fn, event: str = "send") -> None:
        try:
            with self._lock:
                fn()
        except Exception as exc:            # 硬件缺失 / 通信异常：记录但不抛出
            self.error = str(exc)
            if self._log and self._log_spec:
                if event == "connect":
                    self._log.connection_error(self._log_spec, self.error)
                elif event != "close" and self._last_error != self.error:
                    self._log.send_error(self._log_spec, self.error)
            self._last_error = self.error
        else:
            self.error = None
            if self._log and self._log_spec:
                if event == "connect":
                    self._log.connection_ok(self._log_spec)
                elif event != "close" and self._last_error:
                    self._log.connection_recovered(self._log_spec)
            self._last_error = None

    @property
    def log_path(self) -> str:
        return self._log.path if self._log else ""

    def show_frame(self, view: dict):
        fb = render_winrate_frame(view, self.driver.width, self.driver.height)
        self._safe(lambda: self.driver.display(fb), event="send")
        return fb

    def show(self, view: dict) -> None:
        super().show(view)
        self.show_frame(view)

    def preview(self, view: dict) -> str:
        return render_winrate_frame(view, self.driver.width, self.driver.height).to_ascii()

    def close(self) -> None:
        closer = getattr(self.transport, "close", None)
        if closer:
            self._safe(closer, event="close")
        if self._log and self._log_spec:
            self._log.disconnected(self._log_spec, "closed")


def make_display(spec: Optional[str], width: int = 128, height: int = 32) -> DisplayDevice:
    """按规格字符串创建显示设备（供 CLI / 桌面入口使用）。

    * ``""`` / ``mock`` / ``none``      -> :class:`MemoryDisplay`（仅记录，测试用）
    * ``console``                      -> :class:`ConsoleDisplay`（打印到终端）
    * ``oled`` / ``text``              -> :class:`OledDisplay`（终端文本占位）
    * ``i2c`` / ``i2c:1`` / ``i2c:1:0x3c`` -> SSD1306，本机 I2C（树莓派 / Linux）
    * ``serial:COM5`` / ``serial:/dev/ttyUSB0`` -> SSD1306，经单片机桥（Windows 友好）

    末尾可用 ``@128x64`` 指定分辨率，例如 ``i2c:1:0x3c@128x64``。
    """
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("mock", "none", "null"):
        return MemoryDisplay()
    body, _, geom = spec.partition("@")
    if geom:
        try:
            w_str, h_str = geom.lower().split("x")
            width, height = int(w_str), int(h_str)
        except ValueError:
            raise ValueError(f"无法解析分辨率：{geom}（示例 128x64）")
    low = body.lower()
    if low == "console":
        return ConsoleDisplay()
    if low in ("oled", "text"):
        return OledDisplay()
    if low.startswith("i2c"):
        parts = body.split(":")
        bus = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        addr = int(parts[2], 0) if len(parts) > 2 and parts[2] else 0x3C
        return Ssd1306Display(I2CTransport(address=addr, bus=bus), width=width, height=height,
                                     log=HardwareLog(), log_spec=spec)
    if low.startswith("serial"):
        if ":" not in body:
            raise ValueError("serial 显示需指定串口，例如 serial:COM5")
        port = body.split(":", 1)[1]
        return Ssd1306Display(SerialOledTransport(port), width=width, height=height,
                                     log=HardwareLog(), log_spec=spec)
    raise ValueError(f"未知显示规格：{spec}")


class DisplayPump:
    """把赛事事件流“泵”到显示设备上（**事件驱动**，不额外轮询引擎）。

    订阅 :class:`~arena.tournament.EventBus` 的 ``state`` / ``room_closed`` 事件：事件里
    已经带好了本手胜率（房间里每手只算一次），所以这里不会额外调用 KataGo。可选
    ``room_code`` 把屏幕钉在某一桌；缺省则显示最近活跃的对局。
    """

    def __init__(self, bus, display: DisplayDevice, room_code: Optional[str] = None):
        self.bus = bus
        self.display = display
        self.room_code = (room_code or "").strip().upper() or None
        self.last: Optional[dict] = None

    def _on_event(self, event: dict) -> None:
        if not isinstance(event, dict):
            return
        etype = event.get("type")
        code = str(event.get("code") or "").upper()
        if self.room_code and code != self.room_code:
            return
        if etype == "state":
            view = dict(event.get("payload") or {})
            if code:
                view["code"] = code
            self.last = view
            self._show(view)
        elif etype == "room_closed":
            view = dict(self.last or {})
            view.update({"code": code, "verdict": "draw", "game_over": True,
                         "closed_reason": event.get("reason", "")})
            self._show(view)

    def _show(self, view: dict) -> None:
        try:
            self.display.show(view)
        except Exception:
            pass

    def idle(self) -> None:
        """待机画面：还没有任何对局数据时显示 50% / READY。"""
        self._show({"black_winrate": 0.5, "move_number": 0, "verdict": "ongoing",
                    "engine": ""})

    def start(self) -> "DisplayPump":
        self.idle()
        subscribe = getattr(self.bus, "subscribe", None)
        if subscribe:
            subscribe(self._on_event)
        return self

    def stop(self) -> None:
        unsubscribe = getattr(self.bus, "unsubscribe", None)
        if unsubscribe:
            try:
                unsubscribe(self._on_event)
            except Exception:
                pass

    def show_once(self, view: dict) -> dict:
        """直接显示一次给定视图（CLI 预览 / 手动刷新用）。"""
        self._show(view)
        return view