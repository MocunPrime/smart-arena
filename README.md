# 多棋种赛事规则与智慧赛场（Smart Arena）

> 毕业设计原型 —— 参照 [Katayzy](https://github.com/Coderchen-001/Katayzy) 的棋类数据模型，
> 把“围棋单机分析软件”扩展为 **多棋种赛事裁判 + 团队赛制 + 智慧赛场观看** 的完整系统。

本项目依据会议纪要《多棋种赛事规则与智慧赛场设计》实现：以围棋规则为基础，扩展到
**围棋 / 五子棋 / 翻转棋** 三种棋，配套裁判（犯规、计时、终局汇总）、团队赛（分阶段上场 +
加权投票 + 超时强制落子）与智慧赛场（局域网扫码看实时胜率）。

> **当前范围说明**：本阶段聚焦 **软件部分**（规则 / 裁判 / 团队赛制 / 智慧赛场 / AI 适配），
> 已全部完成并通过单元测试。**智慧棋盘（硬件）部分暂缓**，仅在 `arena/hardware.py` 预留接口，
> 详见 [`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) 的 **ISSUE-001**。

---

## 一、整体定位

- **参考项目**：Katayzy（Lizzie / LizzieYzy Next 的 Java 重构版）。本项目的领域模型
  （颜色 `Stone`、棋盘 `BoardData`、胜率、推荐点）对齐 Katayzy 的 `featurecat.lizzie`，
  便于后续把逻辑移植回 Java。
- **成果形态**：一个**可运行的软件原型**，包含三层：
  1. **纯逻辑层**（规则 / 裁判 / 团队赛 / 赛程）—— 零外部依赖，可单元测试；
  2. **AI 分析层** —— 优先接 KataGo（GTP），无引擎时自动降级为启发式评估；
  3. **智慧赛场展示层** —— 标准库 HTTP + SSE，局域网内扫码实时观赛。

## 二、会议需求 → 功能对应

| 会议要求（会议纪要） | 对应实现 |
| --- | --- |
| 违规要“弹窗 + 音效” | `referee` 抛出 `foul` 事件，展示层以事件流 `foul` 推送；音效由前端触发 |
| 禁入点（自杀）、不找劫材提劫不允许下 | `GoRules.is_legal` 判定 `SUICIDE` / `KO` |
| 记录犯规，第一次警告、第二次判负 | `Referee.foul_limit=2`，第 2 次犯规直接判负 |
| 终局汇总：谁先弃权、最后一手 | `Referee.summary()` 汇总 `pass_order`、`last_move`、犯规、比分 |
| 足球式“前锋→中场→后卫”分阶段上场 | `team.PhaseRule` 按手数切换上场名册 |
| 团队投票，队长/嘉宾权重更高、可调 | `team.Member.weight` / `is_captain` / `is_guest`，`demo_side()` 给队长 3.0、嘉宾 2.0 |
| 限时投票，超时强制按最高票落 | `VotingSession.timeout_s` + `resolve()`，到点由 `forced_point()` 强制落子 |
| 智慧赛场：家长扫码看实时胜率 | `venue.VenueServer`：`/` 大厅二维码、`/table/<n>` 实时棋盘、`/events` SSE |
| 对接 KataGo（GTP） | `ai.GtpClient` + `KataGoEvaluator`，缺失时 `HeuristicEvaluator` 兜底 |
| 多棋种（不止围棋） | `rules` 注册表：`GoRules` / `GomokuRules` / `ReversiRules` |
| 三种部署方案（树莓派 / PC+蓝牙 / WiFi 棋盘） | **暂缓** —— 仅预留接口，见 `docs/OPEN-ISSUES.md` ISSUE-001 |

## 三、目录结构

```
biye/
├── run.py                     # 一键启动入口： python run.py serve --autoplay
├── arena/
│   ├── model.py               # 领域模型：Color / GameType / Move / FoulRecord / Verdict
│   ├── rules/
│   │   ├── base.py            # RuleSet 抽象基类（棋盘、气、合法性、胜负、计分）
│   │   ├── go.py              # 围棋：提子、自杀、打劫、中国数子法、两停终局
│   │   ├── gomoku.py          # 五子棋：五连、黑方禁手（长连/三三/四四）
│   │   ├── reversi.py         # 翻转棋：合法翻转、跳过、子数判定
│   │   └── __init__.py        # 棋种注册表 create_rules()
│   ├── referee.py             # 裁判：犯规记录、计时、弃权顺序、终局小结
│   ├── team.py                # 团队赛：名册权重、分阶段上场、加权投票、超时强制
│   ├── tournament.py          # 赛程/多桌管理：EventBus、Table、Tournament
│   ├── ai.py                  # AI：GTP 客户端 + KataGo 适配 + 启发式兜底
│   ├── hardware.py            # 硬件接口（预留，暂缓实现，见 OPEN-ISSUES ISSUE-001）
│   ├── cli.py                 # 命令行：serve / demo / test
│   └── venue/
│       ├── server.py          # 智慧赛场 HTTP + SSE 服务
│       ├── qr.py              # 二维码（segno：SVG / PNG / 终端）
│       └── web/               # 前端：大厅页、单桌页、样式、脚本
├── tools/mock_gtp_engine.py   # 模拟 GTP 引擎（测试/演示用）
├── tests/                     # 单元测试（31 项）
└── docs/                      # 设计文档、需求映射表、开放问题、会议转写
```

## 四、快速开始

```powershell
# 1) 运行自检（31 项单元测试）
py run.py test

# 2) 运行裁判 / 规则演示（含犯规与终局小结）
py run.py demo

# 3) 启动智慧赛场（自动推演 3 桌棋，供扫码观赛）
py run.py serve --autoplay

# 4) 启动并挂载团队赛名册（含分阶段上场、加权投票）
py run.py serve --tables 3 --teams --autoplay
```

启动后会打印局域网地址和终端二维码：

```
  局域网地址 : http://192.168.x.x:8000/
  扫码入口（手机连同一 WiFi 后访问）：
  ██ ▄▄ ...（二维码）
```

手机连上同一热点/局域网后扫码，打开大厅页选择桌号，即可观看实时棋盘与胜率。

### 常用参数

| 参数 | 说明 |
| --- | --- |
| `--port` | 监听端口（默认 8000，`0` 表示随机端口） |
| `--tables` | 演示棋桌数量（1–5，默认 3） |
| `--host` | 绑定地址（默认 0.0.0.0） |
| `--advertised-host` | 二维码/播报地址所用的主机名（默认自动探测本机局域网 IP） |
| `--engine` | KataGo 可执行文件路径（如 `katago gtp -model ... -config ...`） |
| `--autoplay` | 自动推演（演示用，主力为启发式） |
| `--teams` | 为每桌挂载团队赛名册 |
| `--interval` | 自动推演每一步的间隔秒数（默认 1.2） |

## 五、依赖

- 运行环境：**Python 3.8+**（推荐 3.13）。
- 核心逻辑：**零外部依赖**（仅标准库）。
- 二维码（可选）：`pip install segno`（未安装时 `/qr.svg`、`/qr.png` 返回空，其余功能不受影响）。
- 围棋分析（可选）：KataGo 可执行文件，通过 `--engine` 指定；无引擎时自动使用启发式评估。

```powershell
py -m pip install -r requirements.txt
```

## 六、智慧赛场接口一览

| 路径 | 说明 |
| --- | --- |
| `GET /` | 大厅：桌号列表 + 扫码入口 |
| `GET /table/<n>` | 单桌实时棋盘（家长手机观看） |
| `GET /api/tables` | 全部桌位快照（JSON） |
| `GET /api/table/<n>` | 单桌详细状态（含胜率、团队、投票） |
| `GET /events?table=<n>` | SSE 实时事件流（可按桌过滤） |
| `GET /qr.svg` `GET /qr.png` | 服务地址二维码 |
| `POST /api/play` | 落子（`{table,color,x,y}`，供裁判端/演示调用） |
| `POST /api/newtable` | 新建棋桌 |

## 七、文档

- 详细设计：`docs/设计文档.md`
- 会议需求映射：`docs/需求映射表.md`
- **开放问题（含智慧棋盘硬件）**：`docs/OPEN-ISSUES.md`
- 会议原始转写：`docs/会议记录-原始转写.txt`

## 八、说明与后续

- 本项目为**软件原型**：AI 默认启发式，接入 KataGo 后可获得正式形势判断。
- 团队赛权重、阶段划分、限时秒数均可在 `team.py` / `demo_side()` 中调整。
- **硬件（智慧棋盘）为后续工作**：软件侧已预留标准接口（`arena/hardware.py`），
  待与硬件方案确认后接入，跟踪见 [`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) **ISSUE-001**。