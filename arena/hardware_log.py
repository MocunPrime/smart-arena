"""硬件连接日志。

该模块只处理外置硬件（当前为 OLED）的连接生命周期，不记录棋局、落子、
胜率变化等业务数据，避免日志随对弈过程无限增长。
"""
from __future__ import annotations

import datetime
import os
import sys
import threading
from typing import Optional


def default_hardware_log_path() -> str:
    """返回硬件日志路径。

    可用环境变量 ``SMART_ARENA_HARDWARE_LOG`` 覆盖；否则源码运行时写到
    仓库根目录的 ``logs/hardware.log``，打包后的 exe 写到 exe 同级的
    ``logs/hardware.log``。
    """
    configured = (os.environ.get("SMART_ARENA_HARDWARE_LOG") or "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "logs", "hardware.log")


def _clean(value: object) -> str:
    """把异常等值压成单行，避免日志注入或折行。"""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


class HardwareLog:
    """轻量、线程安全的硬件连接日志。"""

    def __init__(self, path: Optional[str] = None):
        self.path = os.path.abspath(path or default_hardware_log_path())
        self._lock = threading.Lock()
        self._failed = False

    def _write(self, level: str, event: str, detail: str = "") -> None:
        if self._failed:
            return
        stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
        line = f"{stamp} | {level:<5} | {event} | {_clean(detail)}\n"
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with self._lock:
                with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
        except OSError:
            # 日志失败绝不能影响对弈或硬件显示。
            self._failed = True

    def connection_attempt(self, spec: str) -> None:
        self._write("INFO", "hardware_connect", f"spec={_clean(spec)} status=attempt")

    def connection_ok(self, spec: str) -> None:
        self._write("INFO", "hardware_connect", f"spec={_clean(spec)} status=ok")

    def connection_error(self, spec: str, error: object) -> None:
        self._write("ERROR", "hardware_connect",
                    f"spec={_clean(spec)} status=error error={_clean(error)}")

    def send_error(self, spec: str, error: object) -> None:
        self._write("ERROR", "hardware_send",
                    f"spec={_clean(spec)} status=error error={_clean(error)}")

    def connection_recovered(self, spec: str) -> None:
        self._write("INFO", "hardware_connect",
                    f"spec={_clean(spec)} status=recovered")

    def disconnected(self, spec: str, reason: str = "closed") -> None:
        self._write("INFO", "hardware_disconnect",
                    f"spec={_clean(spec)} status=closed reason={_clean(reason)}")
