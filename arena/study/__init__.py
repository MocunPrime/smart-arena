"""死活题改卷（Study / Quiz）模块。

会议纪要要求"软件要有改卷功能"：让人类做死活题，由引擎计算人类落子的
胜率，连续若干手胜率都在 90% 以上即判为做对。

本模块把该需求拆成三部分：

* :mod:`arena.study.problems` —— 内置题库（不同难度的经典死活/杀棋常型）
* :class:`arena.study.quiz.QuizSession` —— 一次做题会话：跟踪人类每一手的
  "胜率"与"连续做对"计数，达到阈值即判对
* :class:`arena.study.quiz.StudyManager` —— 多会话管理，供 HTTP 层调用

胜率来源
--------
* 若能接入真实引擎（KataGo），可把 ``evaluator`` 传进来，用它给出的胜率；
* 默认（无引擎）用**参考解答模型**估算：走在标准答案的续着上记 ~0.95，
  走错记 ~0.30。棋盘上都是局部死活，直接套用全局胜率并无意义，因此用
  "是否踩在正解树里"来模拟引擎的胜率判断。

题库来源：经典死活/杀棋常型（如紧气提子、扑、倒扑、征子、追杀等），
属公共围棋理论，由本项目整理成棋盘坐标，不使用任何受版权保护的习题集。
"""
from __future__ import annotations

from .problems import BUILTIN_PROBLEMS, get_problem, list_problems
from .quiz import QuizError, QuizSession, StudyManager, parse_problem

__all__ = [
    "BUILTIN_PROBLEMS",
    "list_problems",
    "get_problem",
    "parse_problem",
    "QuizError",
    "QuizSession",
    "StudyManager",
]