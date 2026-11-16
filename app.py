"""桌面入口（打包为 exe 后双击即可运行）。

用法：
* 不带参数运行（双击 exe）-> 启动线上对弈服务并自动打开浏览器（对弈大厅 /play）；
* 带命令行参数运行        -> 等价于 ``python run.py <参数>``（serve / demo / test）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    def _worker() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


def _run_desktop(port: int = 8000) -> int:
    from arena.tournament import Tournament
    from arena.venue.qr import qr_ascii
    from arena.venue.server import VenueServer

    # 本阶段主打"线上对弈"：不再默认推演演示赛场（智慧赛场见 ISSUE-004）。
    tournament = Tournament()

    # 胜率 / 改卷引擎：默认使用**随程序打包的内置 KataGo**；可用环境变量
    # SMART_ARENA_ENGINE=KataGo 可执行文件路径 覆盖；若都不可用则回退内置启发式。
    from arena.ai import make_default_evaluator, make_evaluator
    env_engine = os.environ.get("SMART_ARENA_ENGINE")
    evaluator = make_evaluator(env_engine) if env_engine else make_default_evaluator()

    venue = VenueServer(tournament, host="0.0.0.0", port=port, evaluator=evaluator)
    try:
        venue.build()
    except OSError:                      # 端口被占用则改用随机端口
        venue = VenueServer(tournament, host="0.0.0.0", port=0, evaluator=evaluator)
        venue.build()

    local_url = f"http://127.0.0.1:{venue.port}/play"
    bar = "=" * 56
    print(bar)
    print("  线上对弈已启动")
    print("  对弈大厅   :", local_url)
    print("  局域网大厅 :", venue.base_url + "play")
    print("  玩法       : 创建房间 -> 记住 4 位对局码 -> 报给对手扫码或输入")
    print("  支持棋种   : 围棋 / 五子棋 / 翻转棋（人人对战、人机对战）")
    print("  胜率引擎   :", "KataGo（内置）" if getattr(evaluator, "name", "") == "katago"
          else "内置启发式（未随包提供 KataGo）")
    print("  死活题改卷 :", f"http://127.0.0.1:{venue.port}/study",
          "（人做死活题，软件按胜率改卷）")
    print(bar)
    print("  正在自动打开浏览器；关闭本窗口即停止服务（Ctrl+C）")
    try:
        print(qr_ascii(venue.base_url + "play"))
    except Exception:
        pass

    _open_browser_later(local_url)
    try:
        venue.httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        venue.shutdown()
    return 0


def main(argv=None) -> int:
    from arena.cli import _harden_console
    _harden_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        from arena.cli import main as cli_main
        return cli_main(argv)
    return _run_desktop()


if __name__ == "__main__":
    sys.exit(main())