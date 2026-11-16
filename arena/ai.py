"""AI 引擎适配。

* ``GtpClient``：跨平台 GTP 子进程通信（后台读线程 + 队列）
* ``KataGoEvaluator``：优先调用 KataGo 的 ``kata-analyze`` 取胜率，
  引擎缺失或异常时自动降级为 ``HeuristicEvaluator``
* ``HeuristicEvaluator``：纯逻辑启发式，保证无引擎时系统仍可运行
"""
from __future__ import annotations

import math
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .model import Color, GameType
from .rules.base import RuleSet

BLACK, WHITE = Color.BLACK, Color.WHITE
GTP_LETTERS = "ABCDEFGHJKLMNOPQRST"   # 跳过 I


def coord_to_gtp(x: int, y: int, size: int) -> str:
    return f"{GTP_LETTERS[x]}{size - y}"


def gtp_to_coord(s: str, size: int):
    s = s.strip().upper()
    if s in ("PASS", ""):
        return None
    col = GTP_LETTERS.index(s[0])
    row = int(s[1:])
    return col, size - row


@dataclass
class EvalResult:
    black_winrate: float
    white_winrate: float
    score_lead: float = 0.0
    source: str = "heuristic"

    def to_dict(self) -> dict:
        return {"black_winrate": self.black_winrate, "white_winrate": self.white_winrate,
                "score_lead": self.score_lead, "source": self.source}


# ---------------------------------------------------------------------- GTP 客户端
class GtpClient:
    def __init__(self, cmd: List[str], cwd: Optional[str] = None):
        self.cmd = cmd
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self._q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.command("name")

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self._q.put(line.rstrip("\n"))
        self._q.put(None)

    def _readline(self, timeout: float) -> Optional[str]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def command(self, cmd: str, timeout: float = 30.0) -> str:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()
        # 跳过上一响应残留的空行，定位以 = 或 ? 开头的响应行
        lead = None
        while True:
            ln = self._readline(timeout)
            if ln is None:
                raise TimeoutError(f"GTP 超时: {cmd}")
            if ln.strip() == "":
                continue
            lead = ln
            break
        if lead.startswith("?"):
            raise RuntimeError(f"GTP 错误: {lead}")
        inline = lead[1:].strip()
        if inline:
            return inline                    # 正文与 = 同行；结尾空行留给下次跳过
        body = []                            # 正文在后续行，读到空行结束
        while True:
            ln = self._readline(timeout)
            if ln is None:
                break
            if ln.strip() == "":
                break
            body.append(ln.strip())
        return "\n".join(body)

    def raw_send(self, cmd: str) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def collect(self, seconds: float) -> List[str]:
        lines, end = [], time.time() + seconds
        while time.time() < end:
            ln = self._readline(min(0.2, max(0.01, end - time.time())))
            if ln is None:
                continue
            if ln.startswith("="):
                break
            lines.append(ln)
        return lines

    def close(self) -> None:
        proc = self.proc
        if not proc:
            return
        try:
            proc.stdin.write("quit\n")
            proc.stdin.flush()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            self.proc = None


# ---------------------------------------------------------------------- 启发式
class HeuristicEvaluator:
    """无外部引擎时的回退评估，用于演示与测试。"""

    name = "heuristic"

    def win_rate(self, rules: RuleSet) -> EvalResult:
        gt = rules.game_type
        if gt is GameType.GO:
            diff = rules.score().get("diff", 0.0)
            wr = 1.0 / (1.0 + math.exp(-diff / 12.0))
            return EvalResult(wr, 1 - wr, score_lead=diff, source="heuristic")
        if gt is GameType.REVERSI:
            sc = rules.score()
            b, w = sc.get("black_stones", 0), sc.get("white_stones", 0)
            wr = 0.5 + 0.5 * (b - w) / max(1, (b + w))
            return EvalResult(wr, 1 - wr, float(b - w), source="heuristic")
        # 五子棋：用棋子数做弱估计
        pieces = rules.count_pieces()
        tot = max(1, pieces[BLACK] + pieces[WHITE])
        wr = 0.5 + 0.4 * (pieces[BLACK] - pieces[WHITE]) / tot
        return EvalResult(wr, 1 - wr, float(pieces[BLACK] - pieces[WHITE]), source="heuristic")

    def suggest(self, rules: RuleSet, color: Color, n: int = 5) -> List[dict]:
        moves = rules.legal_moves(color)
        if not moves:
            return []
        size = rules.size
        center = (size - 1) / 2.0

        def score(m):
            d = abs(m[0] - center) + abs(m[1] - center)
            return d
        moves.sort(key=score)
        out = []
        for i, (x, y) in enumerate(moves[:n]):
            out.append({"x": x, "y": y, "order": i,
                        "winrate": round(0.6 - 0.05 * i, 3), "source": "heuristic"})
        return out

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------- KataGo
class KataGoEvaluator:
    def __init__(self, engine_path: Optional[str] = None, config_path: Optional[str] = None,
                 model_path: Optional[str] = None):
        self.fallback = HeuristicEvaluator()
        self.client: Optional[GtpClient] = None
        self.available = False
        self.name = "katago"
        if engine_path:
            cmd = [engine_path, "gtp"]
            if config_path:
                cmd += ["-config", config_path]
            if model_path:
                cmd += ["-model", model_path]
            try:
                self.client = GtpClient(cmd)
                self.client.start()
                self.available = True
            except Exception:
                self.client = None
                self.available = False

    def _sync(self, rules: RuleSet) -> None:
        assert self.client
        self.client.command(f"boardsize {rules.size}")
        if rules.game_type is GameType.GO:
            self.client.command(f"komi {rules.komi}")
        self.client.command("clear_board")
        for mv in rules.moves:
            if mv.is_pass:
                self.client.command(f"play {mv.color.name.lower()} pass")
            else:
                self.client.command(
                    f"play {mv.color.name.lower()} {coord_to_gtp(mv.x, mv.y, rules.size)}")

    def win_rate(self, rules: RuleSet) -> EvalResult:
        if not self.available or not self.client:
            return self.fallback.win_rate(rules)
        try:
            self._sync(rules)
            self.client.raw_send("kata-analyze interval 80 maxmoves 1")
            lines = self.client.collect(1.2)
            self.client.raw_send("")       # 中断分析
            wr = self._parse_winrate(lines, rules.to_play)
            if wr is None:
                return self.fallback.win_rate(rules)
            b = wr if rules.to_play is BLACK else 1 - wr
            return EvalResult(b, 1 - b, source="katago")
        except Exception:
            self.available = False
            return self.fallback.win_rate(rules)

    @staticmethod
    def _parse_winrate(lines: List[str], to_play: Color) -> Optional[float]:
        wr = None
        for ln in lines:
            if "winrate" in ln:
                for tok in ln.split():
                    if tok.startswith("winrate"):
                        # kata-analyze 的 winrate 是当前行棋方视角
                        try:
                            wr = float(tok.split()[0].split("=")[1]) if "=" in tok else None
                        except Exception:
                            wr = None
        return wr

    def suggest(self, rules: RuleSet, color: Color, n: int = 5) -> List[dict]:
        return self.fallback.suggest(rules, color, n)

    def close(self) -> None:
        if self.client:
            self.client.close()


def make_evaluator(engine_path: Optional[str] = None, config_path: Optional[str] = None,
                   model_path: Optional[str] = None):
    if engine_path:
        return KataGoEvaluator(engine_path, config_path, model_path)
    return HeuristicEvaluator()