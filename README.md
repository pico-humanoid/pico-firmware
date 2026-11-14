# PICO-Firmware 固件设计

[PICO-Humanoid](https://pico-humanoid.github.io/) 的固件子项目，负责关节、电池 BMS、电源板的 CAN 通信，以及设备状态、运行管理和上下位机接口。

当前验证平台：**NUCLEO-G474RE + SN65HVD230 + USB-CAN-A**。仓库更新日期：2026-11-14。

## 当前进展与时间线

**截至2026年11月10日，电机与开发板的通信尚未完成，不能将后续成果回填成11月10日前已完成。** 基础CAN回环、USB-CAN对设备测试、固件编译及主机测试，与开发板直接访问电机是不同验证环节。

| 时间 / 范围 | 状态与证据 |
| --- | --- |
| 2026-10-27 基础CAN | 内部回环及PC触发板端返回报文已验证；不等同于电机通信通过 |
| 截至2026-11-10 电机链路 | 尚未完成，继续排查外设、引脚、时钟、速率与真实收发；见[11月10日阶段记录](docs/weekly/2026-11-10.md) |
| 2026-11-14 后续实测记录 | 已取得双电机参数/目标回读、实际位置/速度/Iq及停止确认记录；同时存在位置跳变、停止后位置不稳定等问题，不宣称整机或全部电机验收通过；见[验证索引](logs/2026-11-14/README.md) |
| 当前开发控制台 | Windows原生控制台、日志查看器、位置/速度滑块、可设置时长、双机联调、限流与受阻报警；[使用说明](docs/Motor_Tuning.md) |
| 软件验证 | 本轮46项固件主机测试与控制台专项测试通过；构建通过不替代硬件验证，额定限流功能未进行实物验收 |
| Windows发布包 | 用户提供的2026-11-14 Windows-x64快照；[发布下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.14)，不能在Ubuntu上运行；Ubuntu新版需单独构建验证 |

当前电机实验使用CAN1（PA12 TX / PA11 RX，1Mbps）；10P ID1、00 ID2。BMS/电源板独立实验与电机链路分别记录。历史失败日志保留，不用软件PASS覆盖原始数据。

## 子模块与文档

| 入口 | 内容 |
| --- | --- |
| [每周工作汇总](docs/weekly/README.md) | 每周二晚汇报；[11月10日阶段记录](docs/weekly/2026-11-10.md)与[11月14日后续记录](docs/validation/2026-11-14-motor.md)、历期记录与周报模板 |
| [当前程序索引](docs/program-index.md) | 所有固件应用、控制台、日志查看器与测试入口 |
| [验证工程](firmware/PICO_CAN/IMPORT.md) | 源码、ELF / HEX / BIN、构建与烧录入口、文件校验 |
| [Linux 工具链](docs/linux-toolchain.md) | Linux 环境检查、独立构建预设、安装记录与无硬件验证边界 |
| [BMS / 电源板读取与验收](docs/device-read-validation.md) | 新增只读软件、配置项、构建烧录采集命令、协议不确定项及硬件测试清单 |
| [硬件与接线](docs/hardware/README.md) | 开发板、收发器、三路 CAN、蜂鸣器和 LED 引脚 |
| [通信方案](docs/communication/README.md) | 关节 / BMS / 电源板协议、CAN 分路、上下位机分工 |
| [CAN 验证操作](docs/can-bringup.md) | 串口与 CAN 参数、测试报文、日志消息、每次采集步骤 |
| [验证与结果](docs/validation/README.md) | 各阶段状态、实测报告和日志索引 |
| [固件开发计划](docs/firmware-development.md) | 九项工作、推进顺序、超时 / 错帧 / 断连与恢复验收 |
| [协作与资料分工](docs/collaboration/README.md) | 已知信息、固件侧工作、需其他组确认的事项与可选表格 |
| [GitHub 合并前整理](docs/repository-upload.md) | 上传范围、本地归档、证据校验与增量合并建议 |
| [参考资料](docs/resources.md) | 项目资料、设备协议、官方手册和工具入口 |

## 工程与日志下载

- **[桌面开发控制台与日志查看器](docs/desktop-workbench.md)**：Windows / Ubuntu 原生程序、迁移步骤、USB 权限及运行环境说明；[下载便携程序](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.14)。

- [完整原始工程 ZIP](archives/PICO_CAN_20261027.zip) · [已展开源码](firmware/PICO_CAN/) · [六个烧录文件](firmware/PICO_CAN/IMPORT.md#六个原始固件文件)
- [本轮原始日志](logs/2026-10-27/) · [全部历史日志索引](docs/validation/log-archive.md)

## 下一步

1. 继续复现与定位位置反馈跳变、停止后位置不稳定和受阻问题，保留每台UID与失败记录。
2. 完成额定限流下的温度、负载、停止确认及双机异常联动实物验收。
3. 单独构建并验证新版Ubuntu包，再逐步开展机械装配与整机联调。

相关项目：[机械设计](https://github.com/pico-humanoid/pico-mechanism) · [电气设计](https://github.com/pico-humanoid/pico-electronics)

工具资料：[Waveshare USB-CAN-A 官方说明](https://www.waveshare.net/wiki/USB-CAN-A) · [全部参考资料](docs/resources.md)
