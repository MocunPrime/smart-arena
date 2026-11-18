"""SSD1306 OLED 驱动：把胜率渲染到外置 OLED 屏幕。

面向 **SSD1306（0.91 寸 / 0.96 寸，128x32 或 128x64，I2C）** 提供一条与运行
平台解耦的渲染链路::

    view(dict)  ->  render_winrate_frame()        # 领域数据 -> 位图
                ->  SSD1306.display(framebuffer)  # 位图 -> 控制字节流
                ->  transport.send(control,data)  # 控制字节流 -> 硬件

``transport`` 只要求实现 ``send(control: int, payload: bytes) -> None``，
因此同一套渲染逻辑可以对接：

* 树莓派 / Linux 本机 I2C —— :class:`I2CTransport`（需 ``smbus2`` 或 ``smbus``）；
* Windows + 单片机桥 —— :class:`SerialOledTransport`
  （见 ``docs/OLED.md`` 与 ``tools/ssd1306_bridge``）；
* 录制 / 空实现 —— :class:`RecordingTransport` / :class:`NullTransport`，
  用于单元测试与“无硬件预览”。

依赖：本模块**只用标准库**即可导入；只有在真正访问硬件时才按需导入
``smbus2`` / ``smbus`` / ``serial``。
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

OLED_WIDTH = 128
OLED_HEIGHT_32 = 32
OLED_HEIGHT_64 = 64


class OLEDError(RuntimeError):
    """OLED 通信 / 初始化失败。"""


# ----------------------------------------------------------------- 5x7 字体
# 每个字符是 7 行 x 5 列的点阵（0/1，行优先）。字体为本项目自绘，仅覆盖 UI
# 所需子集：数字、大写字母与常用符号；未知字符回退为实心方块。
_FONT_ART: Dict[str, str] = {
    " ": "00000/00000/00000/00000/00000/00000/00000",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11111/00010/00100/00010/00001/10001/01110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/11110/00001/00001/10001/01110",
    "6": "00110/01000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00010/01100",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01110/10001/10000/10000/10000/10001/01110",
    "D": "11100/10010/10001/10001/10001/10010/11100",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01110/10001/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "01110/00100/00100/00100/00100/00100/01110",
    "J": "00111/00010/00010/00010/00010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/10101/01010",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "%": "11001/11010/00010/00100/01000/01011/10011",
    ".": "00000/00000/00000/00000/00000/01100/01100",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    "+": "00000/00100/00100/11111/00100/00100/00000",
    "/": "00001/00010/00010/00100/01000/01000/10000",
    "#": "01010/01010/11111/01010/11111/01010/01010",
    ":": "00000/01100/01100/00000/01100/01100/00000",
    "(": "00010/00100/01000/01000/01000/00100/00010",
    ")": "01000/00100/00010/00010/00010/00100/01000",
    "!": "00100/00100/00100/00100/00100/00000/00100",
    "?": "01110/10001/00001/00010/00100/00000/00100",
    "=": "00000/00000/11111/00000/11111/00000/00000",
    "<": "00010/00100/01000/10000/01000/00100/00010",
    ">": "01000/00100/00010/00001/00010/00100/01000",
    "*": "00000/10101/01110/11111/01110/10101/00000",
    ",": "00000/00000/00000/00000/01100/01100/01000",
    "'": "00100/00100/00000/00000/00000/00000/00000",
}
_GLYPH_FALLBACK = "11111/10001/10001/10001/10001/10001/11111"


def _glyph_columns(art: str) -> Tuple[int, ...]:
    """把 7 行 x 5 列的点阵转成 5 个列字节（bit0=顶行）。"""
    rows = art.split("/")
    cols = []
    for c in range(5):
        b = 0
        for r in range(7):
            if rows[r][c] == "1":
                b |= 1 << r
        cols.append(b)
    return tuple(cols)


_FONT_5x7: Dict[str, Tuple[int, ...]] = {ch: _glyph_columns(a) for ch, a in _FONT_ART.items()}
_FONT_FALLBACK_COLS = _glyph_columns(_GLYPH_FALLBACK)


# ----------------------------------------------------------------- 位图缓冲
class Framebuffer:
    """单色位图，采用 SSD1306 页式布局：``buf[page*width + x]``，bit0 为该页顶行。"""

    def __init__(self, width: int = OLED_WIDTH, height: int = OLED_HEIGHT_32):
        if width <= 0 or height <= 0 or width % 8 or height % 8:
            raise ValueError("宽高必须为正且为 8 的倍数")
        self.width = int(width)
        self.height = int(height)
        self.pages = self.height // 8
        self.buf = bytearray(self.width * self.pages)

    def clear(self, on: bool = False) -> None:
        self.buf[:] = bytes([0xFF if on else 0x00]) * len(self.buf)

    def pixel(self, x: int, y: int, on: bool = True) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        idx = (y >> 3) * self.width + x
        bit = 1 << (y & 7)
        if on:
            self.buf[idx] |= bit
        else:
            self.buf[idx] &= (0xFF ^ bit)

    def hline(self, x: int, y: int, w: int, on: bool = True) -> None:
        for i in range(int(w)):
            self.pixel(x + i, y, on)

    def vline(self, x: int, y: int, h: int, on: bool = True) -> None:
        for j in range(int(h)):
            self.pixel(x, y + j, on)

    def rect(self, x: int, y: int, w: int, h: int, on: bool = True, fill: bool = False) -> None:
        x, y, w, h = int(x), int(y), int(w), int(h)
        if w <= 0 or h <= 0:
            return
        if fill:
            for j in range(h):
                self.hline(x, y + j, w, on)
        else:
            self.hline(x, y, w, on)
            self.hline(x, y + h - 1, w, on)
            self.vline(x, y, h, on)
            self.vline(x + w - 1, y, h, on)

    def text(self, x: int, y: int, s, scale: int = 1, on: bool = True,
             spacing: int = 1) -> int:
        """画一行 5x7 文本，返回结束后的 x 坐标。``scale`` 为整数放大倍数。"""
        cx = int(x)
        scale = max(1, int(scale))
        for ch in str(s):
            cols = _FONT_5x7.get(ch) or _FONT_5x7.get(ch.upper()) or _FONT_FALLBACK_COLS
            for ci, col in enumerate(cols):
                for r in range(7):
                    if col & (1 << r):
                        if scale == 1:
                            self.pixel(cx + ci, y + r, on)
                        else:
                            for dx in range(scale):
                                for dy in range(scale):
                                    self.pixel(cx + ci * scale + dx, y + r * scale + dy, on)
            cx += (5 + spacing) * scale
        return cx

    @staticmethod
    def text_width(s, scale: int = 1, spacing: int = 1) -> int:
        n = len(str(s))
        if n == 0:
            return 0
        scale = max(1, int(scale))
        return n * (5 + spacing) * scale - spacing * scale

    def to_bytes(self) -> bytes:
        return bytes(self.buf)

    def to_ascii(self) -> str:
        out = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                on = (self.buf[(y >> 3) * self.width + x] >> (y & 7)) & 1
                row.append("#" if on else ".")
            out.append("".join(row))
        return "\n".join(out)

    def __str__(self) -> str:
        return self.to_ascii()


# ----------------------------------------------------------------- 传输层
class NullTransport:
    """丢弃所有写入（只想跑通逻辑时用）。"""

    def send(self, control: int, payload: bytes) -> None:      # pragma: no cover - 直通
        return None


class RecordingTransport:
    """记录每次 ``send`` 的 (control, payload)，供测试 / 干跑检查。"""

    def __init__(self) -> None:
        self.frames: List[Tuple[int, bytes]] = []

    def send(self, control: int, payload: bytes) -> None:
        self.frames.append((int(control), bytes(payload)))

    @property
    def data_bytes(self) -> bytes:
        """只拼接“数据（0x40）”负载，等价于整屏帧缓冲。"""
        return b"".join(p for c, p in self.frames if c == 0x40)

    @property
    def commands(self) -> List[int]:
        out: List[int] = []
        for c, p in self.frames:
            if c == 0x00:
                out.extend(p)
        return out

    def reset(self) -> None:
        self.frames.clear()


class I2CTransport:
    """本机 I2C 总线（树莓派 / Linux）。需 ``smbus2`` 或 ``smbus``。"""

    def __init__(self, address: int = 0x3C, bus: int = 1):
        self.address = int(address)
        self.bus_no = int(bus)
        self._bus = None

    def _ensure(self):
        if self._bus is not None:
            return self._bus
        try:
            from smbus2 import SMBus
            self._bus = SMBus(self.bus_no)
        except ImportError:
            try:
                import smbus
                self._bus = smbus.SMBus(self.bus_no)
            except ImportError as exc:
                raise OLEDError(
                    "未找到 smbus2 / smbus，无法访问 I2C；请先 pip install smbus2") from exc
        return self._bus

    def send(self, control: int, payload: bytes) -> None:
        bus = self._ensure()
        bus.write_i2c_block_data(self.address, int(control), list(payload))

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None


class SerialOledTransport:
    """Windows / 任意平台 + 单片机桥。

    把 SSD1306 控制字节流打包成帧，经串口发给一块桥接单片机，由它转写到 OLED。
    协议（每帧）::

        0xAA | control(1) | len_lo(1) | len_hi(1) | payload(len)

    ``control`` 为 0x00（命令）或 0x40（数据）。需要 ``pyserial``。
    参考固件见 ``tools/ssd1306_bridge/ssd1306_bridge.ino``。
    """

    MAGIC = 0xAA

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = timeout
        self._ser = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._ser is not None:
            return self._ser
        try:
            import serial
        except ImportError as exc:
            raise OLEDError("未找到 pyserial；请先 pip install pyserial") from exc
        self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        return self._ser

    @classmethod
    def encode_frame(cls, control: int, payload: bytes) -> bytes:
        n = len(payload)
        return bytes([cls.MAGIC, int(control) & 0xFF, n & 0xFF, (n >> 8) & 0xFF]) + bytes(payload)

    def send(self, control: int, payload: bytes) -> None:
        frame = self.encode_frame(control, payload)
        with self._lock:
            ser = self._ensure()
            ser.write(frame)

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None


# ----------------------------------------------------------------- SSD1306
class SSD1306:
    """SSD1306 控制器：把位图转成控制字节流，通过 ``transport`` 下发。"""

    def __init__(self, transport, width: int = OLED_WIDTH, height: int = OLED_HEIGHT_32,
                 address: int = 0x3C, chunk: int = 16):
        self.transport = transport
        self.width = int(width)
        self.height = int(height)
        self.address = int(address)
        self.chunk = max(1, int(chunk))
        self.framebuffer = Framebuffer(self.width, self.height)
        self.initialized = False

    def _cmd(self, *data: int) -> None:
        transport = self.transport
        if transport is None:            # pragma: no cover - 防御
            return
        transport.send(0x00, bytes(data))

    def _data(self, payload: bytes) -> None:
        for i in range(0, len(payload), self.chunk):
            self.transport.send(0x40, payload[i:i + self.chunk])

    def init(self) -> None:
        mux = 0x1F if self.height == 32 else 0x3F
        compins = 0x02 if self.height == 32 else 0x12
        seq = [0xAE, 0xD5, 0x80, 0xA8, mux, 0xD3, 0x00, 0x40,
               0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, compins,
               0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6,
               0x2E, 0xAF]
        for i in range(0, len(seq), 8):
            self._cmd(*seq[i:i + 8])
        self.initialized = True

    def clear(self) -> None:
        self.framebuffer.clear(False)

    def display(self, framebuffer: Optional[Framebuffer] = None,
                init_if_needed: bool = True) -> None:
        fb = framebuffer if framebuffer is not None else self.framebuffer
        if init_if_needed and not self.initialized:
            self.init()
        self._cmd(0x21, 0x00, self.width - 1)          # 列地址 0..width-1
        self._cmd(0x22, 0x00, self.height // 8 - 1)    # 页地址 0..pages-1
        self._data(fb.to_bytes())

    def contrast(self, value: int) -> None:
        self._cmd(0x81, max(0, min(255, int(value))))

    def invert(self, on: bool) -> None:
        self._cmd(0xA7 if on else 0xA6)

    def power(self, on: bool) -> None:
        self._cmd(0xAF if on else 0xAE)


def open_i2c(bus: int = 1, address: int = 0x3C,
             width: int = OLED_WIDTH, height: int = OLED_HEIGHT_32) -> SSD1306:
    """便捷函数：在指定 I2C 总线上打开一块 SSD1306。"""
    return SSD1306(I2CTransport(address=address, bus=bus), width=width, height=height)


# ----------------------------------------------------------------- 胜率渲染
_VERDICT_TAG = {"black_win": "B WIN", "white_win": "W WIN", "draw": "DRAW"}


def _engine_tag(view: dict) -> str:
    src = str(view.get("engine") or view.get("source") or "").lower()
    if "katago" in src:
        return "KATAGO"
    if "heuristic" in src or "local" in src:
        return "LOCAL"
    return src.upper()[:6] or "LOCAL"


def _status_tag(view: dict) -> str:
    tag = _VERDICT_TAG.get(view.get("verdict"))
    if tag:
        return tag
    fp = view.get("first_pass")
    if fp:
        return f"FP {str(fp)[:1].upper()}"
    passes = view.get("pass_log") or []
    if passes:
        return f"PASS {len(passes)}"
    return "PLAYING" if (view.get("move_number") or 0) else "READY"


def _draw_bar(fb: Framebuffer, x: int, y: int, w: int, h: int, frac: float) -> None:
    fb.rect(x, y, w, h, on=True, fill=False)
    inner = w - 2
    fill_w = int(round(inner * max(0.0, min(1.0, frac))))
    for j in range(1, h - 1):
        if fill_w > 0:
            fb.hline(x + 1, y + j, fill_w, True)


def _render_32(fb: Framebuffer, view: dict, black: float) -> Framebuffer:
    w = fb.width
    pct = int(round(black * 100))
    mv = view.get("move_number") or 0
    fb.text(0, 0, f"M{mv}", 1)
    engine = _engine_tag(view)
    fb.text(w - Framebuffer.text_width(engine, 1), 0, engine, 1)
    left = f"B{pct}%"
    right = f"W{100 - pct}%"
    fb.text(2, 9, left, 2)
    fb.text(w - 2 - Framebuffer.text_width(right, 2), 9, right, 2)
    _draw_bar(fb, 0, 26, w, 5, black)
    return fb


def _render_64(fb: Framebuffer, view: dict, black: float) -> Framebuffer:
    w = fb.width
    engine = _engine_tag(view)
    mv = view.get("move_number") or 0
    fb.text(0, 0, engine, 1)
    mtext = f"M{mv}"
    fb.text(w - Framebuffer.text_width(mtext, 1), 0, mtext, 1)
    big = f"{black * 100:.1f}%"
    fb.text(2, 12, big, 3)
    wtxt = f"W{100 - black * 100:.1f}%"
    fb.text(w - Framebuffer.text_width(wtxt, 1), 16, wtxt, 1)
    _draw_bar(fb, 0, 46, w, 10, black)
    fb.text(0, 57, _status_tag(view), 1)
    return fb


def render_winrate_frame(view: dict, width: int = OLED_WIDTH,
                         height: int = OLED_HEIGHT_32) -> Framebuffer:
    """把房间 / 棋桌视图渲染成一块 1bpp 位图。

    期望的 ``view`` 可含：``black_winrate``（黑方胜率 0..1，缺省 0.5）、
    ``move_number``、``engine`` / ``source``、``verdict``、``first_pass``、``pass_log``。
    128x32 显示两方大号胜率 + 底部胜率条；128x64 额外显示大号百分比与终局 / 弃权信息。
    """
    fb = Framebuffer(width, height)
    raw = view.get("black_winrate")
    if raw is None:
        white = view.get("white_winrate")
        black = 1.0 - float(white) if white is not None else 0.5
    else:
        black = float(raw)
    black = max(0.0, min(1.0, black))
    if fb.height <= 32:
        return _render_32(fb, view, black)
    return _render_64(fb, view, black)


def demo_view(black: float = 0.62, move_number: int = 42, engine: str = "katago",
              verdict: str = "ongoing", first_pass: Optional[str] = None) -> dict:
    """生成一条用于预览 / 自检的示例视图。"""
    black = max(0.0, min(1.0, float(black)))
    return {"black_winrate": black, "white_winrate": 1.0 - black,
            "move_number": move_number, "engine": engine, "verdict": verdict,
            "first_pass": first_pass}