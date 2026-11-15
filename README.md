# PICO-Firmware 固件设计

[PICO-Humanoid](https://pico-humanoid.github.io/) 的固件子项目，负责关节、电池 BMS、电源板的 CAN 通信，以及设备状态、运行管理和上下位机接口。

当前验证平台：**NUCLEO-G474RE + 3.3V CAN 收发器（SN65HVD230，或 TJA1051T/3 且 VIO=3.3V、S=GND）+ USB-CAN-A**。更新日期：2026-11-08。

## 当前进展

| 工作 | 状态与结果 |
| --- | --- |
| 验证工程与工具 | 源码、两种模式的六个烧录文件、烧录 / 采集脚本和原始日志已归档 |
| 内部回环 | 已通过：发送提交、发送完成、接收各 100 条，RESULT=PASS |
| 外部 CAN | 已验证：电脑发 1 条 `0x321`，板端返回 100 条 `0x123`，两端记录逐帧一致 |
| 引脚与通信方案 | 三路 CAN、蜂鸣器和两个 LED 已选脚；当前实测覆盖 FDCAN1 |
| BMS / 电源板只读软件 | 双设备共用FDCAN1的500K镜像已生成、主机测试13/13通过，尚未上板；USB-CAN→BMS 500K 325/325、USB-CAN→电源板500K 312/312已通过；**G474→电源板500K 已通过放宽判据**（135s、640 TX_DONE/637 RX、0 bus-off、TEC/REC=0、query_failures=0；3次首次超时重试成功）；严格“无重试/无孤立帧”判据仍NOT_PASS。**G474→BMS 500K 已通过严格判据**（347/347/347、0超时/0无效/0 bus-off、53.43V/99%）；**Dual 同总线 500K 已在 CAN1/CAN2/CAN3 实机验证**（CAN1 干净 PASS；CAN2/CAN3 功能可用：BMS 启动偶发 1 次失败后 mask 仍填满，电源板 1–2 次首次超时重试成功、0 失败；统一 3 秒启动宽限，两个设备每项最多 2 次尝试；已修复错误计数器固定读 hfdcan1 的误报）；5V TJA1051T/3 需 VIO=3.3V、S=GND，不能把 VIO 接 5V |
| 设备与整机联调 | 关节查询、双总线同时读取、多节点及上下位机联调待开展 |
| 后续固件开发 | 关节管理、周期与目标处理、状态机等任务和异常验收已规划，待实现与验证 |

外部原版程序的自动 `RESULT=FAIL` 来自仍要求接收 100 条输入的共用判据；本轮单触发返回功能已核对。详细结论与原始记录见[2026-10-27 实测报告](docs/validation/2026-10-27.md)。

## 子模块与文档

| 入口 | 内容 |
| --- | --- |
| [每周工作汇总](docs/weekly/README.md) | 每周二晚汇报；[本期：10/28—11/03](docs/weekly/2026-11-03.md)、历期记录与周报模板 |
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

- [完整原始工程 ZIP](archives/PICO_CAN_20261027.zip) · [已展开源码](firmware/PICO_CAN/) · [六个烧录文件](firmware/PICO_CAN/IMPORT.md#六个原始固件文件)
- [本轮原始日志](logs/2026-10-27/) · [全部历史日志索引](docs/validation/log-archive.md)

## 下一步

1. 更换 SN65HVD230 模块后完成 G474→电源板 500K 60秒验收；再复测 G474→BMS，若仍无回复再评估隔离。USB-CAN 已通过，详见 [BMS / 电源板验收说明第 8 节](docs/device-read-validation.md)。
2. 推进关节状态、周期与整组目标、状态机和故障管理，先完成模拟闭环。
3. 按[协作清单](docs/collaboration/README.md)核对装配、实际接线与控制约束，逐步开展多节点和上下位机联调。

相关项目：[机械设计](https://github.com/pico-humanoid/pico-mechanism) · [电气设计](https://github.com/pico-humanoid/pico-electronics)

工具资料：[Waveshare USB-CAN-A 官方说明](https://www.waveshare.net/wiki/USB-CAN-A) · [全部参考资料](docs/resources.md)
