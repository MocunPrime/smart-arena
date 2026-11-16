"""多棋种裁判与智慧赛场（Smart Arena）。

参照 Katayzy（LizzieYzy Next 重构的围棋分析软件）的数据模型，把
"围棋分析"扩展为 "多棋种赛事裁判 + 团队赛制 + 智慧赛场观看"。

本包提供与 Katayzy/GTP 引擎解耦的纯逻辑层，便于论文验证与单元测试。
"""

__version__ = "0.2.0"

__all__ = ["model", "rules", "referee", "team", "tournament", "ai", "hardware", "venue"]