# PICO_CAN 工程、固件与日志工具

目标板为 NUCLEO-G474RE。本目录来自上传的 `PICO_CAN.zip`，保留原源码、工具、依赖、配置、六个固件文件和全部历史 CSV；本次未修改固件行为、日志结果或原有检查器。

- [下载完整原始 ZIP](../../archives/PICO_CAN_20261027.zip)：上传包全部 310 个文件，包含编译缓存和中间文件。
- [文件校验清单](import-manifest.json)：已展开的 152 个原文件与 ZIP 内容逐字节一致。
- [当前项目说明](../../README.md) · [2026-10-27 实测报告](../../docs/validation/2026-10-27.md) · [日志索引](../../docs/validation/log-archive.md)

原始 ZIP 的 SHA-256：

```text
8cc4dca7b14e591d20dfe7bb6b1b3a07c4da9bfc26f8c2a0fe0e5a42c4ebe3fd
```

## 源码与工程文件

| 入口 | 内容 |
| --- | --- |
| [App/can_bringup.c](App/can_bringup.c) | 内部回环、外部触发发送、收发队列、日志与自动判据 |
| [App/can_bringup.h](App/can_bringup.h) | 应用接口和测试状态结构 |
| [Core/Src/main.c](Core/Src/main.c) | 外设初始化与 CanTest 应用入口 |
| [Core/Src/fdcan.c](Core/Src/fdcan.c) | FDCAN 初始化 |
| [Core/Src/usart.c](Core/Src/usart.c) | LPUART1 日志串口初始化 |
| [PICO_CAN.ioc](PICO_CAN.ioc) | CubeMX 工程配置 |
| [CMakeLists.txt](CMakeLists.txt) / [CMakePresets.json](CMakePresets.json) | 两种模式的构建配置 |
| [PICO_CAN.code-workspace](PICO_CAN.code-workspace) / [.vscode](.vscode/) | VS Code 工作区、任务与调试配置 |
| [Drivers](Drivers/) | 原工程附带的 STM32 HAL 与 CMSIS 依赖及许可文件 |

编译配置 `Loopback` 使用 `PICO_EXTERNAL_CAN=OFF`，`External` 使用 `PICO_EXTERNAL_CAN=ON`。两种模式共享应用源码，具体外设模式和过滤 ID 由编译选项选择。

## 六个原始固件文件

| 模式 | ELF（烧录脚本默认使用） | HEX | BIN |
| --- | --- | --- | --- |
| 内部回环 | [Loopback/PICO_CAN.elf](build/Loopback/PICO_CAN.elf) | [Loopback/PICO_CAN.hex](build/Loopback/PICO_CAN.hex) | [Loopback/PICO_CAN.bin](build/Loopback/PICO_CAN.bin) |
| 外部 CAN | [External/PICO_CAN.elf](build/External/PICO_CAN.elf) | [External/PICO_CAN.hex](build/External/PICO_CAN.hex) | [External/PICO_CAN.bin](build/External/PICO_CAN.bin) |

| 模式 | ELF 字节数 | HEX 字节数 | BIN 字节数 |
| --- | --- | --- | --- |
| Loopback | 1410928 | 65205 | 23160 |
| External | 1410892 | 65128 | 23128 |

六个文件的 SHA-256 均与原工程 [preparation_checks.json](preparation_checks.json) 一致，详细值同时收录在 [import-manifest.json](import-manifest.json)。

归档时已检查：ELF 为 ARM ELF32，Flash 装载基址为 `0x08000000`，复位向量和初始栈地址在对应有效范围；HEX 记录校验和有效，其定义的 Flash 字节与 ELF、BIN 一致。HEX 在 `0x080001D8`—`0x080001DF` 省略了 8 个零填充字节，ELF / BIN 中保留该填充，校验时按格式差异处理。

此次没有重新编译或连接硬件测试，六个产物为上传包中的原始文件。

## 烧录与日志采集入口

| 入口 | 调用内容 | 作用 |
| --- | --- | --- |
| [01_Open_Project.cmd](01_Open_Project.cmd) | VS Code 工作区 | 打开项目 |
| [02_Build_All.cmd](02_Build_All.cmd) | [scripts/build.ps1](scripts/build.ps1) 的 All 模式 | 编译两种配置 |
| [03_Flash_Loopback.cmd](03_Flash_Loopback.cmd) | [scripts/flash.ps1](scripts/flash.ps1)，Loopback | 烧录 build/Loopback/PICO_CAN.elf |
| [04_Capture_Log.cmd](04_Capture_Log.cmd) | [scripts/capture.ps1](scripts/capture.ps1) | 采集 ST-LINK 虚拟串口并保存 CSV |
| [05_Flash_External.cmd](05_Flash_External.cmd) | [scripts/flash.ps1](scripts/flash.ps1)，External | 烧录 build/External/PICO_CAN.elf |
| [scripts/check_log.py](scripts/check_log.py) | Python 标准库 | 按原有每类事件 100 条及 PASS 汇总规则检查日志 |

`flash.ps1` 通过 SWD 写入 ELF，随后执行校验和复位。BIN 为不含装载地址的原始数据，若在其他工具中手动选择 BIN，Flash 起始地址使用 `0x08000000`；ELF 与 HEX 自带地址信息。

在 Windows 上使用时，先打开已解压或克隆的本工程目录。沿用原机目录时为 `D:\STM32Projects\PICO_CAN`；放到其他目录时脚本通过自身位置确定工程根目录。

1. 连接开发板 ST-LINK USB，按实验选择 03 或 05 烧录。
2. 运行 04，看到串口打开与保存路径后按 RESET。
3. 内部回环自动执行；外部单触发实验发送一条 `0x321`、8 字节 `00 88 77 66 55 44 33 22`，等待返回 100 条 `0x123`。
4. 保留本轮 CSV，并在 USBCAN 中另行导出 CAN 收发记录。详细参数见[通信配置与采集说明](../../docs/can-bringup.md)。

若要手动指定日志端口，在 PowerShell 中进入本工程目录后运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\capture.ps1" -Port COM5 -Seconds 60
```

COM5 是示例，需要替换为设备管理器中的 ST-LINK 虚拟串口。采集使用 115200 8N1，每次按启动时间写入本工程的 `logs` 目录；默认上限 60 秒，收到 `# RESULT=` 后结束，原始 FAIL 也会保存。

## 原版自动判据

实际源码确认：第一条有效 `0x321` 启动发送序列，此后发送 100 条 `0x123`；末尾自动 PASS 条件却仍要求 `rx_unique=100`。因此，电脑只发一条触发、完整收到 100 条返回时，单触发功能已实现，但原版程序仍会报告 FAIL。

`check_log.py` 同样要求 TX_SUBMIT、TX_DONE、RX 各有序号 0—99 的 100 条记录、完整 CSV 列头和 PASS 汇总。它的自动规则与本次单触发功能目标分别说明，具体结果见[实测报告](../../docs/validation/2026-10-27.md)。

最新 [17:11:37 内部回环日志](../../logs/2026-10-27/board_20261027_171137.csv)已完整核对通过。原工程的源码、脚本和固件保持上传时的字节。

如果以后调整单触发模式的自动判据，应另行编译、实测和记录新版本。当前归档没有修改源码或将旧 FAIL 改为 PASS。

## 工具路径与历史记录

原脚本和编辑器配置保留上传时的设置：

- `scripts/build.ps1` 使用原机 STM32Cube 工具包中的 GCC、CMake、Ninja 版本，并包含 `D:\STM32Tools\bin`。
- `scripts/flash.ps1` 在当前用户 `AppData\Local\stm32cube\bundles\programmer\2.23.0\bin` 查找 STM32CubeProgrammer。
- `CMakePresets.json`、`.vscode/launch.json` 和其他工程配置中含原 Windows 用户目录、CubeMX、调试器与 SVD 路径。

换电脑时需要安装工具，并按实际位置调整这些配置；仓库保留的是原工程快照。已展开目录省略 CMake 缓存、对象文件和中间元数据，重新编译时由工具生成；完整原始 ZIP 仍保留它们。

[原工程 README](README.md)、[PREPARATION_STATUS.md](PREPARATION_STATUS.md)和准备校验记录保留当时的历史状态，当前项目进展以外层仓库首页和实测报告为准。[工程 logs](logs/)包含原包全部 20 份历史板端记录，[本轮 USBCAN TXT](../../logs/2026-10-27/2026.10.27.txt)单独保存在外层按日期归档的目录。

第三方依赖许可随原文件保留：[CMSIS](Drivers/CMSIS/LICENSE.txt)、[STM32G4 设备支持](Drivers/CMSIS/Device/ST/STM32G4xx/LICENSE.txt)、[STM32 HAL](Drivers/STM32G4xx_HAL_Driver/LICENSE.txt)。
