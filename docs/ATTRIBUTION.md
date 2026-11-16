# 第三方组件与授权（Attribution）

本仓库随程序分发第三方组件，授权与来源如下。

## 1. KataGo（围棋引擎）

- **组件**：KataGo v1.18.1，Eigen / CPU 构建（Windows x64 单文件发行版解压所得）。
- **用途**：为本项目提供**胜率评估**（`kata-analyze`）：离线棋谱回放的双方胜率、
  以及死活题“改卷”的人类落子胜率。
- **来源**：<https://github.com/lightvector/KataGo> ，
  下载页 <https://github.com/lightvector/KataGo/releases/tag/v1.18.1>
  （`katago-v1.18.1-eigen-windows-x64.zip`）。
- **授权**：**MIT License**，Copyright 2025 David J Wu ("lightvector") and/or other authors.
  许可证全文见 [`engine/KataGo-LICENSE.txt`](../engine/KataGo-LICENSE.txt)。
- **随包文件**：`engine/katago.exe` 及同目录运行库（`*.dll`）、配置文件（`*.cfg`）、
  `cacert.pem`、`README.txt`。

## 2. KataGo 神经网络权重

- **组件**：`g170e-b10c128-s1141046784-d204142634.txt.gz`（小网络，体积小、CPU 可跑）。
- **来源**：KataGo 官方发布资产
  <https://github.com/lightvector/KataGo/releases/download/v1.3/g170e-b10c128-s1141046784-d204142634.txt.gz>。
- **授权**：KataGo 项目声明“仓库内全部代码与内容”均在 **MIT** 许可下发布，
  网络权重作为该项目的发布内容适用同一许可（见上）。
- **说明**：本项目仅将其用于本地形势判断 / 改卷，未作再训练或商业再分发承诺；
  如需更高棋力可自行替换 `engine/*.txt.gz`。

## 3. segno（二维码，可选依赖）

- **用途**：生成终端 / SVG / PNG 二维码（局域网扫码入口）。
- **来源**：<https://github.com/heuer/segno>；**授权**：BSD-3-Clause。

## 4. 参考项目 Katayzy（仅设计参考，未拷贝代码）

- **来源**：<https://github.com/Coderchen-001/Katayzy>（GPL）。
- **说明**：本项目仅在**领域模型 / 功能结构层面**参考该 Java 版 Lizzie，
  未复制其任何源代码，故不受其 GPL 传染；相关设计对应见根目录 `README.md`。