# 外置 SSD1306 OLED 胜率屏

本项目支持把线上对弈的**实时胜率、手数、引擎状态、终局/弃权信息**显示到外置
**SSD1306 0.91 英寸 OLED（128x32，I2C）**。0.96 英寸 128x64 型号同样支持，
启动参数末尾加 `@128x64` 即可。

胜率数据直接取房间事件里已经计算好的结果，显示刷新**不会额外调用 KataGo**。

## 一、接线

0.91 英寸 SSD1306 通常有 4 个引脚：

| OLED | 连接 |
| --- | --- |
| `VCC` | 3.3V（建议 3.3V，避免裸屏逻辑电平过压） |
| `GND` | GND |
| `SCL` | I2C 时钟 |
| `SDA` | I2C 数据 |

常见开发板 I2C 引脚：

| 开发板 | SDA | SCL |
| --- | --- | --- |
| Arduino Uno / Nano | A4 | A5 |
| ESP32 | GPIO21 | GPIO22 |
| ESP8266 | D2 (GPIO4) | D1 (GPIO5) |
| 树莓派 40-pin | GPIO2 (Pin 3) | GPIO3 (Pin 5) |

默认 I2C 地址为 `0x3C`。如果模块背面改成 `0x3D`，把命令里的地址同步改成
`i2c:1:0x3d`，并修改固件里的 `SSD1306_ADDR`。

## 二、先做无硬件预览

不接 OLED 也能先检查画面布局：

```powershell
py run.py oled-preview
py run.py oled-preview --height 64 --black 0.78 --move 88
```

第一行会打印 ASCII 点阵预览，便于确认 128x32 / 128x64 布局是否正确。

## 三、Windows + 单片机串口桥（推荐给 exe 用户）

Windows 桌面程序不方便直接访问 I2C，推荐使用一块 Arduino / ESP 开发板做桥：

1. 按上面的引脚表把开发板与 OLED 接好；
2. 用 Arduino IDE 打开并烧录 `tools/ssd1306_bridge/ssd1306_bridge.ino`；
3. 电脑安装串口依赖：

```powershell
py -m pip install pyserial
```

4. 在“设备管理器”查看开发板串口，例如 `COM5`；
5. 先发送一帧测试画面：

```powershell
py run.py oled-preview --display serial:COM5
```

6. 对接线上对弈：

```powershell
py run.py serve --display serial:COM5
```

128x64 型号使用：

```powershell
py run.py serve --display serial:COM5@128x64
```

打包后的 exe 用法相同：

```powershell
.\release\SmartArena.exe serve --display serial:COM5
```

双击 exe 时也可以先设置环境变量：

```powershell
$env:SMART_ARENA_DISPLAY = "serial:COM5"
$env:SMART_ARENA_DISPLAY_ROOM = "AB12"   # 可选：只显示某个房间
.\release\SmartArena.exe
```

串口桥协议为：

```text
0xAA | control(1) | len_lo(1) | len_hi(1) | payload(len)
```

`control=0x00` 表示 SSD1306 命令，`0x40` 表示显存数据。固件负责把数据转发到
I2C OLED；未接硬件时程序不会崩溃，只会记录通信错误。

## 四、树莓派 / Linux 本机 I2C

树莓派直接连接 OLED，无需单片机桥：

```bash
sudo raspi-config          # Interface Options -> I2C -> Enable
sudo apt install i2c-tools
i2cdetect -y 1             # 正常应看到 3c（或 3d）
pip install smbus2
```

然后运行：

```bash
python run.py serve --display i2c:1:0x3c
```

128x64：

```bash
python run.py serve --display i2c:1:0x3c@128x64
```

## 五、屏幕内容

- 128x32：左上角显示手数 `M<手数>`，两侧显示黑/白胜率 `Bxx% / Wxx%`，底部为胜率条；
- 128x64：显示引擎名、手数、大号百分比、胜率条，以及 `READY / PLAYING / B WIN /
  W WIN / DRAW / FP 黑 / FP 白` 等状态；
- 房间关闭时保留最后一帧并显示结束状态；
- 默认显示最近活跃房间，可用 `--display-room <房间码>` 固定某一桌。

## 六、代码位置

- `arena/oled.py`：SSD1306 帧缓冲、5x7 字体、胜率画面渲染、I2C/串口传输；
- `arena/hardware.py`：`Ssd1306Display`、`make_display()`、事件驱动 `DisplayPump`；
- `arena/cli.py`：`serve --display ...` 与 `oled-preview` 命令；
- `app.py`：桌面版读取 `SMART_ARENA_DISPLAY` 环境变量；
- `tools/ssd1306_bridge/ssd1306_bridge.ino`：Arduino/ESP 串口桥固件。

## 七、故障排查

| 现象 | 处理 |
| --- | --- |
| 屏幕全黑 | 检查 3.3V、GND、SDA/SCL 是否接反；用 `i2cdetect -y 1` 查地址 |
| 启动时提示 `未就绪` | 检查 `smbus2` / `pyserial` 是否安装、串口是否被其他软件占用 |
| `serial:COM5` 打不开 | 在设备管理器确认端口号；关闭 Arduino 串口监视器 |
| 128x64 只亮一半/花屏 | 启动参数加 `@128x64`；128x32 不要加 |
| 胜率不更新 | 确认对局正在落子；显示泵只监听 `state` / `room_closed` 事件 |
| 树莓派找不到 I2C | 确认 I2C 已启用且用户有 `/dev/i2c-1` 权限 |

> 说明：固件只做协议转发，不包含任何第三方 OLED 库，也不需要联网。
## 八、硬件连接日志

OLED 连接日志只记录硬件连接生命周期，不记录棋局、落子或胜率变化：

* 源码运行：`logs/hardware.log`（项目根目录）；
* exe 运行：`logs/hardware.log`（exe 同级目录）；
* 可通过环境变量 `SMART_ARENA_HARDWARE_LOG` 指定绝对路径或文件名。

日志内容包括连接尝试、连接成功、连接失败、通信失败恢复和断开连接。日志写入失败时会静默降级，不影响对弈或 OLED 显示。
