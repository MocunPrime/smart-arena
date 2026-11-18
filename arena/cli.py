"""命令行入口：启动智慧赛场服务 / 运行演示 / 自检。"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time

from .ai import HeuristicEvaluator, make_default_evaluator, make_evaluator
from .hardware import DisplayPump, make_display
from .model import Color, GameType
from .referee import TimeControl
from .team import demo_side
from .tournament import Tournament
from .venue.server import VenueServer, local_ip
from .venue.qr import qr_ascii


def build_demo_tournament(n_tables: int = 3, engine: str = None,
                          time_control: TimeControl = None,
                          evaluator=None) -> Tournament:
    ev = evaluator or (make_evaluator(engine) if engine else HeuristicEvaluator())
    t = Tournament(default_time=time_control or TimeControl(total=0, per_move=0))
    specs = [
        (1, GameType.GO, 19, "围棋 A组"),
        (2, GameType.GOMOKU, 15, "五子棋 A组"),
        (3, GameType.REVERSI, 8, "翻转棋 A组"),
        (4, GameType.GO, 9, "围棋 B组"),
        (5, GameType.GOMOKU, 15, "五子棋 B组"),
    ]
    for no, gt, size, label in specs[:max(1, n_tables)]:
        t.create_table(no, gt, size=size, label=label,
                       black=f"黑方{no}", white=f"白方{no}", evaluator=ev)
    return t


def _autoplay(t: Tournament, interval: float = 1.2):
    ev = HeuristicEvaluator()

    def loop():
        rng = random.Random(20261117)
        while True:
            for table in list(t.tables.values()):
                if table.referee.game_over:
                    continue
                rules = table.referee.rules
                color = rules.to_play
                moves = rules.legal_moves(color)
                if not moves:
                    table.referee.play_pass(color)
                    continue
                # 优先靠近已有子的点位，观感更自然
                occupied = [(x, y) for x, y in rules.cells() if rules.get(x, y) is not Color.EMPTY]
                if occupied:
                    cx = sum(p[0] for p in occupied) / len(occupied)
                    cy = sum(p[1] for p in occupied) / len(occupied)
                    moves.sort(key=lambda m: (m[0] - cx) ** 2 + (m[1] - cy) ** 2)
                    x, y = moves[rng.randrange(0, min(3, len(moves)))]
                elif len(rules.moves) == 0:
                    c = (rules.size - 1) // 2
                    x, y = (c, c) if (c, c) in moves else moves[0]
                else:
                    x, y = moves[rng.randrange(len(moves))]
                t.play(table.no, color, x, y)
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()


def cmd_serve(args) -> int:
    # 本阶段主打"线上对弈"：默认不预置演示棋桌；需要观赛演示时传 --tables N。
    time_control = TimeControl(
        total=max(0.0, float(getattr(args, "time_total", 0) or 0)),
        per_move=max(0.0, float(getattr(args, "time_per_move", 0) or 0)))
    # 胜率/改卷引擎：显式 --engine 优先，否则自动使用**内置** KataGo，缺失即回退启发式
    evaluator = make_evaluator(args.engine) if args.engine else make_default_evaluator()
    tournament = (build_demo_tournament(args.tables, time_control=time_control,
                                        evaluator=evaluator)
                  if args.tables else Tournament(default_time=time_control))
    if args.teams:
        _attach_teams(tournament)
    idle_minutes = getattr(args, "idle_timeout", None)
    idle_seconds = None if idle_minutes is None else max(0.0, float(idle_minutes)) * 60.0
    venue = VenueServer(tournament, host=args.host, port=args.port,
                        advertised_host=args.advertised_host,
                        idle_timeout=idle_seconds,
                        records_dir=getattr(args, "records_dir", None),
                        engine_path=getattr(args, "engine", None),
                        evaluator=evaluator,
                        time_control=time_control)
    display = None
    display_pump = None
    display_note = "未启用"
    display_log = ""
    display_spec = getattr(args, "display", "") or ""
    if display_spec:
        try:
            display = make_display(display_spec)
            display_pump = DisplayPump(
                venue.bus, display, getattr(args, "display_room", None)).start()
            display_note = display_spec
            display_log = getattr(display, "log_path", "")
            err = getattr(display, "error", None)
            if err:
                display_note += f"（未就绪：{err}）"
        except Exception as exc:
            display = None
            display_pump = None
            display_note = f"未启用（{exc}）"
    if args.autoplay:
        _autoplay(tournament, args.interval)
    lobby = venue.base_url + "play"
    print("=" * 54)
    print("  线上对弈已启动")
    print("  对弈大厅   :", lobby)
    print("  本机地址   :", f"http://127.0.0.1:{args.port}/play")
    print("  外置显示   :", display_note)
    if display_log:
        print("  硬件日志   :", display_log)
    print("  胜率引擎   :", "KataGo（内置）"
          if getattr(evaluator, "name", "") == "katago"
          else "内置启发式（未随包提供 KataGo）")
    if tournament.tables:
        print("  演示棋桌   :", len(tournament.tables), "（智慧赛场见 ISSUE-004）")
    if venue.rooms.idle_timeout > 0:
        print("  空闲自动关闭:", int(venue.rooms.idle_timeout // 60), "分钟")
    tc = time_control
    if tc.is_timed:
        parts = []
        if tc.total > 0:
            parts.append(f"每方总时限 {int(tc.total)} 秒")
        if tc.per_move > 0:
            parts.append(f"每手限时 {int(tc.per_move)} 秒")
        print("  对局限时   :", "；".join(parts))
    else:
        print("  对局限时   : 不限（可在创建房间时按局设置）")
    print("  棋谱保存目录:", venue.rooms.records_dir)
    print("=" * 54)
    print("  扫码入口（手机连同一 WiFi 后访问）：")
    try:
        print(qr_ascii(lobby))
    except Exception:
        pass
    print("  Ctrl+C 退出")
    try:
        venue.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        if display_pump is not None:
            display_pump.stop()
        if display is not None:
            closer = getattr(display, "close", None)
            if closer:
                try:
                    closer()
                except Exception:
                    pass
        venue.shutdown()
    return 0


def cmd_oled_preview(args) -> int:
    """不启动对弈服务，直接渲染一帧并可发送到真实 OLED。"""
    from .oled import demo_view, render_winrate_frame

    view = demo_view(args.black, args.move, args.engine, args.verdict)
    fb = render_winrate_frame(view, args.width, args.height)
    spec = (getattr(args, "display", "") or "").strip()
    if spec:
        display = None
        try:
            display = make_display(spec)
            display.show(view)
            err = getattr(display, "error", None)
            if err:
                print(f"OLED 发送失败（{spec}）：{err}")
                return 1
            print(f"OLED 发送成功：{spec}")
        except Exception as exc:
            print(f"OLED 发送失败（{spec}）：{exc}")
            return 1
        finally:
            closer = getattr(display, "close", None) if display is not None else None
            if closer:
                try:
                    closer()
                except Exception:
                    pass
    print(fb.to_ascii())
    print(f"已渲染 {args.width}x{args.height}，黑方胜率 {view['black_winrate']*100:.1f}%")
    return 0

def _attach_teams(t: Tournament) -> None:
    for i, table in enumerate(sorted(t.tables.values(), key=lambda x: x.no)):
        black = demo_side(f"{table.no}桌黑队", captain_weight=3.0, guest_weight=2.0)
        white = demo_side(f"{table.no}桌白队", captain_weight=3.0, guest_weight=2.0)
        table.black_team = black
        table.white_team = white


def cmd_demo(args) -> int:
    from .rules import create_rules
    from .referee import Referee

    rules = create_rules(GameType.GO, 9, komi=7.5)
    ref = Referee(rules, names={Color.BLACK: "红队", Color.WHITE: "蓝队"})
    print("== 演示：9路围棋 + 犯规/终局小结 ==")
    seq = [(Color.BLACK, 4, 4), (Color.WHITE, 2, 2), (Color.BLACK, 4, 3),
           (Color.WHITE, 3, 4), (Color.BLACK, 4, 4),   # 重复落子 -> 犯规
           (Color.BLACK, 4, 4)]                         # 再犯 -> 判负
    for c, x, y in seq:
        out = ref.play(c, x, y)
        tag = "" if out.accepted else f"  <非法: {out.result.value}>"
        print(f"  {c.name_cn}方 落 ({x},{y})  手数={len(rules.moves)}{tag}")
        if out.foul:
            print(f"    ⚠ 犯规：{out.foul.foul_type.name_cn} "
                  f"（{ref.foul_count(c)} 次）{'-> 判负' if out.loss_by_foul else '-> 警告'}")
    print("\n== 终局小结 ==")
    import json
    print(json.dumps(ref.summary(), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(args) -> int:
    import unittest
    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _harden_console() -> None:
    """让中文/符号在 GBK 控制台或管道重定向下不报错（不可编码字符降级为 ?）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

def main(argv=None) -> int:
    _harden_console()
    p = argparse.ArgumentParser(prog="smart-arena",
                                description="多棋种赛事规则与智慧赛场（参照 Katayzy）")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="启动智慧赛场局域网服务")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--tables", type=int, default=0,
                   help="预置演示棋桌数量(0-5，默认 0=纯对弈大厅)")
    s.add_argument("--engine", default=None, help="KataGo 可执行文件路径")
    s.add_argument("--advertised-host", default=None)
    s.add_argument("--autoplay", action="store_true", help="自动推演(演示用)")
    s.add_argument("--interval", type=float, default=1.2)
    s.add_argument("--teams", action="store_true", help="挂载团队赛制名册")
    s.add_argument("--idle-timeout", type=float, default=None,
                   help="房间空闲自动关闭的分钟数（默认 30，0 表示不自动关闭）")
    s.add_argument("--records-dir", default=None,
                   help="棋谱保存目录（默认 exe 同级 / 仓库 records）")
    s.add_argument("--time-total", type=float, default=0.0,
                   help="每方总时限（秒，0=不限；创建房间时可覆写）")
    s.add_argument("--time-per-move", type=float, default=0.0,
                   help="每手限时（秒，0=不限；创建房间时可覆写）")
    s.add_argument("--display", default="",
                   help="外置显示规格：serial:COM5 / i2c:1:0x3c / console；见 docs/OLED.md")
    s.add_argument("--display-room", default=None,
                   help="固定显示某一个房间码；缺省显示最近活跃对局")
    s.set_defaults(func=cmd_serve)
    d = sub.add_parser("demo", help="运行裁判/规则演示")
    d.set_defaults(func=cmd_demo)

    t = sub.add_parser("test", help="运行自带单元测试")
    t.set_defaults(func=cmd_selftest)

    o = sub.add_parser("oled-preview", help="渲染/发送一帧 OLED 胜率画面（不启动服务）")
    o.add_argument("--display", default="",
                   help="留空只打印 ASCII；也可用 serial:COM5 / i2c:1:0x3c")
    o.add_argument("--width", type=int, default=128)
    o.add_argument("--height", type=int, default=32, choices=(32, 64))
    o.add_argument("--black", type=float, default=0.62, help="黑方示例胜率 0..1")
    o.add_argument("--move", type=int, default=42, dest="move")
    o.add_argument("--engine", default="katago")
    o.add_argument("--verdict", default="ongoing")
    o.set_defaults(func=cmd_oled_preview)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())