# PICO-Firmware 固件设计

[PICO-Humanoid](https://pico-humanoid.github.io/) 的固件子项目，负责关节、电池 BMS、电源板的 CAN 通信，以及设备状态、运行管理和上下位机接口。

当前验证平台：**NUCLEO-G474RE + SN65HVD230 + USB-CAN-A**。更新日期：2026-10-27。

## 当前进展

| 工作 | 状态与结果 |
| --- | --- |
| 验证工程与工具 | 源码、两种模式的六个烧录文件、烧录 / 采集脚本和原始日志已归档 |
| 内部回环 | 已通过：发送提交、发送完成、接收各 100 条，RESULT=PASS |
| 外部 CAN | 已验证：电脑发 1 条 `0x321`，板端返回 100 条 `0x123`，两端记录逐帧一致 |
| 引脚与通信方案 | 三路 CAN、蜂鸣器和两个 LED 已选脚；当前实测覆盖 FDCAN1 |
| 设备与整机联调 | 关节 / BMS / 电源板只读查询、多节点及上下位机联调待开展 |
| 后续固件开发 | 关节管理、周期与目标处理、状态机等任务和异常验收已规划，待实现与验证 |

外部原版程序的自动 `RESULT=FAIL` 来自仍要求接收 100 条输入的共用判据；本轮单触发返回功能已核对。详细结论与原始记录见[2026-10-27 实测报告](docs/validation/2026-10-27.md)。

## 子模块与文档

| 入口 | 内容 |
| --- | --- |
| [验证工程](firmware/PICO_CAN/IMPORT.md) | 源码、ELF / HEX / BIN、构建与烧录入口、文件校验 |
| [硬件与接线](docs/hardware/README.md) | 开发板、收发器、三路 CAN、蜂鸣器和 LED 引脚 |
| [通信方案](docs/communication/README.md) | 关节 / BMS / 电源板协议、CAN 分路、上下位机分工 |
| [CAN 验证操作](docs/can-bringup.md) | 串口与 CAN 参数、测试报文、日志消息、每次采集步骤 |
| [验证与结果](docs/validation/README.md) | 各阶段状态、结果图片预留、实测报告和日志索引 |
| [固件开发计划](docs/firmware-development.md) | 九项工作、推进顺序、超时 / 错帧 / 断连与恢复验收 |
| [协作与资料分工](docs/collaboration/README.md) | 已知信息、固件侧工作、需其他组确认的事项与可选表格 |
| [参考资料](docs/resources.md) | 项目资料、设备协议、官方手册和工具入口 |

## 工程与日志下载

- [完整原始工程 ZIP](archives/PICO_CAN_20261027.zip) · [已展开源码](firmware/PICO_CAN/) · [六个烧录文件](firmware/PICO_CAN/IMPORT.md#六个原始固件文件)
- [本轮原始日志](logs/2026-10-27/) · [全部历史日志索引](docs/validation/log-archive.md)

## 下一步

1. 固件侧先读已有协议并实现编解码，使用现有 G474 与 USB-CAN 完成扩展帧和单设备只读验证。
2. 推进关节状态、周期与整组目标、状态机和故障管理，先完成模拟闭环。
3. 按[协作清单](docs/collaboration/README.md)核对装配、实际接线与控制约束，逐步开展多节点和上下位机联调。

相关项目：[机械设计](https://github.com/pico-humanoid/pico-mechanism) · [电气设计](https://github.com/pico-humanoid/pico-electronics)

工具资料：[Waveshare USB-CAN-A 官方说明](https://www.waveshare.net/wiki/USB-CAN-A) · [全部参考资料](docs/resources.md)
