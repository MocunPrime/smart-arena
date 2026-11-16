"""最小 GTP 引擎，仅用于测试 ``arena.ai.GtpClient``（不参与正式运行）。"""
import sys


def respond(text=""):
    sys.stdout.write("= " + text + "\n\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "":
            respond("")      # 空行：中断分析
            continue
        op = cmd.split()[0].lower()
        if op in ("name",):
            respond("MockGTP")
        elif op in ("version",):
            respond("1.0")
        elif op in ("boardsize", "komi", "clear_board", "play", "time_left"):
            respond("")
        elif op == "genmove":
            respond("D4")
        elif op in ("kata-analyze", "genmove_analyze", "lz-analyze"):
            sys.stdout.write("info move D4 visits 512 winrate 0.62 scoreMean 3.4 pv D4\n")
            sys.stdout.flush()
        elif op == "final_score":
            respond("B+3.5")
        elif op == "quit":
            respond("")
            break
        else:
            respond("")


if __name__ == "__main__":
    main()