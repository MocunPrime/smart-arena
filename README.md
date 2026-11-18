# 多棋种赛事规则与智慧赛场（Smart Arena）

> 毕业设计原型 —— 参照 [Katayzy](https://github.com/Coderchen-001/Katayzy) 的棋类数据模型，
> 把“围棋单机分析软件”扩展为 **多棋种赛事裁判 + 团队赛制 + 智慧赛场观看** 的完整系统。

本项目依据会议纪要《多棋种赛事规则与智慧赛场设计》实现：以围棋规则为基础，扩展到
**围棋 / 五子棋 / 翻转棋** 三种棋，配套裁判（犯规、计时、终局汇总）、团队赛（分阶段上场 +
加权投票 + 超时强制落子）与智慧赛场（局域网扫码看实时胜率）。

> **当前范围说明**：
> * **本阶段主功能 = 线上对弈（下棋）**：局域网内创建房间、4 位对局码加入、实时落子，
>   已完整实现（见第六节），支持围棋 / 五子棋 / 翻转棋的人人对战与人机对战。
> * **死活题改卷（本阶段主功能之一）**：人做死活题，软件按"连续走对的关键手胜率≥90%"改卷，
>   内置入门/初级/中级/高级多难度题库，见第七节。
> * **智慧赛场（场馆观赛 / 多桌导播）暂缓启用**：代码与页面全部保留，由 `arena/venue/server.py`
>   的 `VENUE_ENABLED` 统一控制，默认关闭，详见 [`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) **ISSUE-004**。
> * **外置 OLED 胜率屏已接入**：支持 SSD1306 0.91/0.96 英寸（128x32/128x64），
>   对弈时实时显示黑白胜率、手数与终局/弃权状态，见 [`docs/OLED.md`](docs/OLED.md)。
> * **硬件连接日志**：只记录 OLED 连接、断连和通信异常，写入 `logs/hardware.log`，不会记录棋局过程。
> * **实体棋盘硬件暂缓**：传感器落子链路仍保留接口，跟踪见 **ISSUE-001**。

---

## 一、整体定位

- **参考项目**：Katayzy（Lizzie / LizzieYzy Next 的 Java 重构版）。本项目的领域模型
  （颜色 `Stone`、棋盘 `BoardData`、胜率、推荐点）对齐 Katayzy 的 `featurecat.lizzie`，
  便于后续把逻辑移植回 Java。
- **成果形态**：一个**可运行的软件原型**，包含三层：
  1. **纯逻辑层**（规则 / 裁判 / 团队赛 / 赛程）—— 零外部依赖，可单元测试；
  2. **AI 分析层** —— **内置 KataGo**（随 exe / 仓库分发，开箱即用），无引擎时自动降级为启发式评估；
  3. **展示层** —— 标准库 HTTP + SSE：本阶段提供**线上对弈**（`/play` 大厅 + `/room/<code>` 对局页），
     智慧赛场观赛页（`/table/<n>`）已实现但暂缓启用（`VENUE_ENABLED=False`）。

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
| 对接 KataGo（GTP） | **内置 KataGo v1.18.1（CPU/Eigen）+ 小网络**，`arena.ai` 自动发现；缺失时 `HeuristicEvaluator` 兜底 |
| 多棋种（不止围棋） | `rules` 注册表：`GoRules` / `GomokuRules` / `ReversiRules` |
| 外置 OLED 显示实时胜率 | **已完成** —— SSD1306 128x32/128x64，I2C / 串口桥，事件驱动刷新 |
| 实体棋盘与三种部署实测 | **暂缓** —— 保留接口，见 `docs/OPEN-ISSUES.md` ISSUE-001 |
| 某方在对方某手后弃权、谁是第一个弃权的 | `Referee.pass_log` / `first_pass`；对局页"弃权记录"按钮可查询 |
| 改卷：人做死活题、连续几手胜率≥90% 判对 | `arena/study/`（`QuizSession` / `StudyManager`）+ `/study` 改卷页 |

## 三、目录结构

```
biye/
├── run.py                     # 命令行入口： python run.py serve --autoplay
├── app.py                     # 桌面入口：双击启动赛场并打开浏览器（exe 打包入口）
├── SmartArena.spec            # PyInstaller 打包配置
├── 打包exe.bat                # 一键重新打包
├── requirements.txt           # 运行依赖（segno、pyserial）
├── requirements-build.txt     # 打包依赖（pyinstaller）
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
│   ├── hardware.py            # 硬件接入：显示设备、棋盘链路、事件刷新泵
│   ├── oled.py                # SSD1306 驱动、胜率位图渲染、I2C/串口传输
│   ├── cli.py                 # 命令行：serve / demo / test / oled-preview
│   ├── play/                  # 线上对弈：房间 / 对局码 / 座位 / 启发式 AI 陪练
│   ├── study/                 # 死活题改卷：题库 / 做题会话 / 连对判定
│   └── venue/
│       ├── server.py          # 智慧赛场 HTTP + SSE 服务
│       ├── qr.py              # 二维码（segno：SVG / PNG / 终端）
│       └── web/               # 前端：首页/对弈大厅、对局页、改卷页、棋谱存档与回放页、单桌页、样式、脚本
├── tools/
│   ├── mock_gtp_engine.py     # 模拟 GTP 引擎（测试/演示用）
│   ├── ssd1306_bridge/        # OLED 串口桥 Arduino/ESP 固件
│   └── build_exe.ps1          # 打包脚本
├── engine/                    # 内置 KataGo 引擎 + 小网络（自动发现，随包分发）
├── tests/                     # 单元测试（126 项，含对弈 / 改卷 / 棋谱回放 / OLED / 硬件日志 / 引擎适配）
├── release/                   # 打包产物：SmartArena.exe
└── docs/                      # 设计文档、需求映射表、OLED 接入、开放问题、会议转写
```

## 四、快速开始

```powershell
# 1) 运行自检（125 项单元测试）
py run.py test

# 2) 运行裁判 / 规则演示（含犯规与终局小结）
py run.py demo

# 3) 启动线上对弈（本阶段主功能）；浏览器打开 http://127.0.0.1:8000/play
py run.py serve

# 4) 外置 OLED 画面预览（不接硬件；详见 docs/OLED.md）
py run.py oled-preview

# 5) 接上 SSD1306 后，通过串口桥显示实时胜率
py run.py serve --display serial:COM5

# 6) 需要观赛演示时，再预置棋桌（智慧赛场当前默认停用，见 ISSUE-004）
py run.py serve --tables 3 --teams --autoplay
```

启动后会打印对弈大厅地址、局域网地址和终端二维码：

```
  局域网地址 : http://192.168.x.x:8000/
  扫码入口（手机连同一 WiFi 后访问）：
  ██ ▄▄ ...（二维码）
```

手机连上同一热点/局域网后扫码（或输入 `http://<主机IP>:8000/play`）即可进入对弈大厅：
创建房间拿到 4 位对局码 -> 对手输入/扫码加入 -> 开始下棋。

### 常用参数

| 参数 | 说明 |
| --- | --- |
| `--port` | 监听端口（默认 8000，`0` 表示随机端口） |
| `--tables` | 预置演示棋桌数量（0–5，默认 0=纯对弈大厅） |
| `--host` | 绑定地址（默认 0.0.0.0） |
| `--advertised-host` | 二维码/播报地址所用的主机名（默认自动探测本机局域网 IP） |
| `--engine` | KataGo 可执行文件路径（如 `katago gtp -model ... -config ...`） |
| `--autoplay` | 自动推演（演示用，主力为启发式） |
| `--teams` | 为每桌挂载团队赛名册 |
| `--interval` | 自动推演每一步的间隔秒数（默认 1.2） |
| `--display` | 外置显示器：`serial:COM5` / `i2c:1:0x3c` / `console`；128x64 加 `@128x64` |
| `--display-room` | 只显示指定 4 位房间码；缺省显示最近活跃房间 |

### 外置 SSD1306 OLED 胜率屏

对接 **SSD1306 0.91 英寸 128x32 OLED** 时，先把
[`tools/ssd1306_bridge/ssd1306_bridge.ino`](tools/ssd1306_bridge/ssd1306_bridge.ino)
烧录到 Arduino/ESP 开发板，再运行：

```powershell
py -m pip install pyserial
py run.py oled-preview --display serial:COM5
py run.py serve --display serial:COM5
```

树莓派可直接使用 I2C：`py run.py serve --display i2c:1:0x3c`。
接线、128x64 参数、环境变量和排障说明见 **[`docs/OLED.md`](docs/OLED.md)**。

## 五、依赖

- 运行环境：**Python 3.8+**（推荐 3.13）。
- 核心逻辑：**零外部依赖**（仅标准库）。
- 二维码（可选）：`pip install segno`（未安装时 `/qr.svg`、`/qr.png` 返回空，其余功能不受影响）。
- 围棋分析：**内置 KataGo**（`engine/`，随源码与 exe 分发），自动发现、无需配置；
  仍可用 `--engine <路径>` 或环境变量 `SMART_ARENA_ENGINE` 覆盖为自备引擎；都没有时回退启发式评估。
- 外置 OLED：树莓派 I2C 需 `smbus2`；Windows 串口桥需 `pyserial`。未安装时仅显示功能不可用，不影响对弈。

```powershell
py -m pip install -r requirements.txt
```

## 六、线上对弈（本阶段主功能）

不依赖外网的**局域网对弈软件**：一台电脑当主机，棋手用手机/电脑连上同一 WiFi / 热点，
打开大厅创建房间，把 **4 位对局码** 报给对手（或让对手扫二维码）即可开下。

- 棋种：围棋 / 五子棋 / 翻转棋，棋盘大小可选；
- 模式：**人人对战（pvp）** 与 **人机对战（pve）**（内置启发式 AI，无需 KataGo、无需外网）；
- 规则：复用 `arena/referee.py` 与 `arena/rules/*` —— 非法手**弹窗 + 声音 + 记录**，
  **第一次警告、第二次判负**；围棋打劫/禁入点、五子棋禁手、翻转棋非法点均判为犯规；
- 操作：落子 / **停一手（Pass）** / **认输**；
- 操作补充：对局页有 **"弃权记录"按钮**，可随时查询"某方在对方某手之后停一手（弃权）"，
  并标出谁是**第一个弃权方**；终局弹窗也会显示该信息；
- 终局：弹出汇总（胜负、谁认输、谁先停一手、最后一手、犯规记录）；
- **棋谱存档**：**每一局都会自动保存为 SGF 棋谱**（终局、认输、双方停一手，以及房间关闭时都会保存，幂等不重复），
  存放在 exe 同级 / 仓库根目录的 `records/`（可用环境变量 `SMART_ARENA_RECORDS_DIR` 覆盖）；
  大厅**棋谱存档**区可列表与下载，终局 / 关闭弹窗也提供下载链接；
- **棋谱回放（可视化）**：`/records` 棋谱存档页可按棋种筛选、搜索并显示**终局缩略图**；点开进入 `/replay/<name>` **逐手回放**（播放/暂停、拖动进度条、手数列表跳转、键盘 ←/→/空格）；回放由服务端用规则引擎重建每一手局面，会计算提子。
- **房间空闲自动关闭**：房间内默认 **30 分钟**无人操作（无落子/停一手/认输）即自动关闭，
  关闭时自动保存棋谱并向在线页面推送“房间已关闭 + 下载棋谱”提示；空闲时间可配置。
- 实时：走子通过 SSE 即时同步给对手与（启用后的）观赛页；房间关闭也会推送 `room_closed` 事件。

**入口**：启动服务后访问 `http://<主机IP>:8000/play`，或直接双击 `SmartArena.exe`。

| 路径 | 说明 |
| --- | --- |
| `GET /` | 统一首页（可视化入口：对弈 / 改卷 / 棋谱 / 智慧赛场） |
| `GET /play` | 对弈大厅：创建房间 / 按对局码加入 / 房间列表 |
| `GET /records` | 棋谱存档页：列表、筛选、搜索、终局缩略图 |
| `GET /replay/<name>` | 棋谱回放页：逐手播放 / 拖动进度 / 手数列表 |
| `GET /room/<code>` | 对弈页：棋盘、落子、停一手、认输、终局汇总 |
| `GET /api/rooms` | 房间列表（JSON） |
| `GET /api/room/<code>?token=…` | 房间状态（带 token 时含“我是谁 / 能否走子”） |
| `GET /api/records` | 棋谱存档列表（JSON） |
| `GET /api/room/<code>/record` | 下载该房间最近保存的 SGF 棋谱 |
| `GET /api/records/<name>` | 按文件名下载棋谱 |
| `GET /api/records/<name>/replay` | 棋谱回放数据（逐手棋盘快照；`?frames=0` 只返回终局） |
| `POST /api/room/create` | 创建房间，返回 4 位对局码 |
| `POST /api/room/<code>/join` | 落座（执黑 / 执白 / 自动坐空位） |
| `POST /api/room/<code>/move` | 落子 |
| `POST /api/room/<code>/pass` | 停一手 |
| `POST /api/room/<code>/resign` | 认输 |

## 七、死活题改卷（改卷功能）

会议/需求补充要求"软件要有改卷功能"：**人做死活题，软件按胜率改卷——连续若干手胜率都在 90% 以上**
即判为做对。本阶段把该需求做成一个独立的**改卷页**（`/study`）。

- **题库**：内置 **8 道**不同难度的经典死活/杀棋常型（入门 / 初级 / 中级 / 高级），
  按"紧气提子 / 扑 / 倒扑 / 追杀 / 征子"等公共围棋理论整理成棋盘与参考解答线；
- **判定**：每落一手给出本手"胜率"，**连续走对的关键手数达到本题要求**（且被围白棋被提）即判做对；
  走错一手胜率降到约 30%，连对计数清零，可"重做本题"；
- **胜率来源**：接入**内置 KataGo** 时由引擎 `kata-analyze` 给出**真实胜率**（改卷页会标注
  “KataGo 引擎”）；无引擎时回退**参考解答模型**（踩在正解续着上记 ≥90%，走错记 ~30%）。

| 路径 | 说明 |
| --- | --- |
| `GET /study` | 改卷页：按难度选题、落子、查看逐手胜率与连对进度 |
| `GET /api/study/problems` | 题库列表（JSON，不含解答） |
| `POST /api/study/start` | 开始一题 `{id, streak_needed?, threshold?}`，返回做题会话 |
| `GET /api/study/<sid>` | 单次做题会话状态 |
| `POST /api/study/<sid>/move` | 人类落子 `{x, y}`，返回本手胜率 / 是否连对 |
| `POST /api/study/<sid>/reset` | 重做本题 |

## 八、智慧赛场接口一览（暂停启用，见 ISSUE-004）

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

## 九、文档

- 详细设计：`docs/设计文档.md`
- 会议需求映射：`docs/需求映射表.md`
- **开放问题（含智慧棋盘硬件）**：`docs/OPEN-ISSUES.md`
- **外置 OLED 接入**：`docs/OLED.md`
- 会议原始转写：`docs/会议记录-原始转写.txt`

## 十、说明与后续

- 本项目为**软件原型**：已**内置 KataGo** 用于胜率 / 改卷；人机陪练 AI 仍为启发式（够用、极快）。
- **智慧赛场（场馆观赛）暂缓启用**：把 `arena/venue/server.py` 的 `VENUE_ENABLED` 置为 `True` 即恢复，见 ISSUE-004。
- 团队赛权重、阶段划分、限时秒数均可在 `team.py` / `demo_side()` 中调整。
- **外置 OLED 胜率屏已完成**：SSD1306 128x32/128x64，支持 I2C 与串口桥，见 [`docs/OLED.md`](docs/OLED.md)。
- **实体棋盘（传感器/落子识别）仍为后续工作**：接口保留在 `arena/hardware.py`，跟踪见 [`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) **ISSUE-001**。

---

## 十一、打包为 exe（单文件）

仓库根目录的 `SmartArena.spec` 已配置好打包，已构建的成品在 **`release\SmartArena.exe`**
（Windows 64 位单文件，约 40 MB，**已内置 KataGo 引擎与网络**，无需安装 Python、无需另配引擎）。

- **双击 `SmartArena.exe`**：自动启动**线上对弈**服务并打开浏览器（对弈大厅 `/play`）；
- **带参数运行**：等价于命令行，例如 `SmartArena.exe serve --port 9000` 或 `SmartArena.exe serve --display serial:COM5`。

重新打包：

```powershell
py -m pip install -r requirements.txt -r requirements-build.txt
py -m PyInstaller --noconfirm --clean --distpath release --workpath build SmartArena.spec
```

`SmartArena.spec` 的 `datas` 已包含 `engine/`（KataGo 引擎 + 小网络），打包后单文件即可离线跑分析。
也可以直接双击根目录的 `打包exe.bat`。

> 提示：单文件版首次启动需解压到临时目录，约 2–5 秒；若被 Windows Defender / SmartScreen
> 拦截，选择“仍要运行”即可。
