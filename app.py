"""桌面入口（打包为 exe 后双击即可运行）。

用法：
* 不带参数运行（双击 exe）-> 启动演示赛场（3 桌，自动推演），并自动打开浏览器；
* 带命令行参数运行        -> 等价于 ``python run.py <参数>``（serve / demo / test）。
"""
from __future__ import annotations

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


def _run_desktop(tables: int = 3, port: int = 8000) -> int:
    from arena.cli import _attach_teams, _autoplay, build_demo_tournament
    from arena.venue.qr import qr_ascii
    from arena.venue.server import VenueServer

    tournament = build_demo_tournament(tables)
    _attach_teams(tournament)

    venue = VenueServer(tournament, host="0.0.0.0", port=port)
    try:
        venue.build()
    except OSError:                      # 端口被占用则改用随机端口
        venue = VenueServer(tournament, host="0.0.0.0", port=0)
        venue.build()

    _autoplay(tournament, 1.2)

    local_url = f"http://127.0.0.1:{venue.port}/"
    bar = "=" * 56
    print(bar)
    print("  智慧赛场已启动（演示模式）")
    print("  本机地址   :", local_url)
    print("  局域网地址 :", venue.base_url)
    print("  棋桌数量   :", len(tournament.tables))
    print(bar)
    print("  正在自动打开浏览器；关闭本窗口即停止服务（Ctrl+C）")
    try:
        print(qr_ascii(venue.base_url))
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