# PICO-Firmware 固件设计

[PICO-Humanoid](https://pico-humanoid.github.io/) 的固件子项目，负责关节、电池 BMS、电源板的 CAN 通信，以及设备状态、运行管理和上下位机接口。

当前验证平台：**NUCLEO-G474RE + 3.3V CAN 收发器（SN65HVD230，或 TJA1051T/3 且 VIO=3.3V、S=GND）+ USB-CAN-A**。更新日期：2026-11-15。

## Ubuntu 22.04 本地合并版

已将本地下载的 main 源码合入 zjy 工作区，保留 CAN1/2/3 及原有双设备读取行为。Ubuntu 22.04 源码用法见 [适配指南](docs/Ubuntu_22.04.md)，本轮软件验证见 [本地合并记录](docs/validation/2026-11-15-ubuntu22-local-merge.md)。下方 Ubuntu 24.04 发布包与历史实测是上游记录，不代表本次已发布 Ubuntu 22.04 包或完成实物验收。

## 当前进展与时间线

**截至2026年11月10日，电机与开发板的通信尚未完成，不能将后续成果回填成11月10日前已完成。** 基础CAN回环、USB-CAN对设备测试、固件编译及主机测试，与开发板直接访问电机是不同验证环节。11月21日已在 NUCLEO-G474RE 上完成 CAN2 七台电机的实机读写、逐台三种模式与七台整组测试，详见下表与[验证索引](docs/validation/README.md)。

| 时间 / 范围 | 状态与证据 |
| --- | --- |
| 验证工程与工具 | 源码、两种模式的六个烧录文件、烧录 / 采集脚本和原始日志已归档 |
| 内部回环 | 已通过：发送提交、发送完成、接收各 100 条，RESULT=PASS |
| 外部 CAN | 已验证：电脑发 1 条 `0x321`，板端返回 100 条 `0x123`，两端记录逐帧一致 |
| 引脚与通信方案 | 三路 CAN、蜂鸣器和两个 LED 已选脚；FDCAN1/2/3 均已在实物上使用 |
| BMS / 电源板只读软件 | 双设备共用FDCAN1的500K镜像已生成、主机测试13/13通过；USB-CAN→BMS 500K 325/325、USB-CAN→电源板500K 312/312已通过；**G474→电源板500K 已通过放宽判据**（135s、640 TX_DONE/637 RX、0 bus-off、TEC/REC=0、query_failures=0；3次首次超时重试成功）；严格“无重试/无孤立帧”判据仍NOT_PASS。**G474→BMS 500K 已通过严格判据**（347/347/347、0超时/0无效/0 bus-off、53.43V/99%）；**Dual 同总线 500K 已在 CAN1/CAN2/CAN3 实机验证**；5V TJA1051T/3 需 VIO=3.3V、S=GND，不能把 VIO 接 5V |
| 2026-11-21 电机链路 | **已打通**：CAN2 上 ID1–7（RS00 1–3、RS10P 4–7）1 Mbps 全部返回位置/速度。**逐台**：7 台的零力矩、力矩、位置、速度模式均完成并回到 IDLE；**整组**：7 台同时使能（约 0.13–0.16 s 全部 ACTIVE）、8 s 零力矩保持，以及批量力矩/位置/速度序列连续 **6 轮常规（0.6 N·m、位置 0.1 rad、速度 0.15 前馈）+ 5 轮加压（0.8 N·m、位置 0.2 rad、速度 0.2 前馈）全部通过**，无故障位、无锁存。此前“CAN2 无 ACK”经 CAN1/CAN2 物理对调诊断为**电机线束未真正接到 CAN2 收发器**，不是 FDCAN2/收发器故障；见[对调诊断](docs/validation/2026-11-21-can12-swap.md)与[整组排查](docs/validation/2026-11-21-multi-stop-investigation.md) |
| 2026-11-21 总线隔离 | Robot14 改为按“是否真正接入”判定总线：空载 CAN3 只探测、不再触发全局锁存；已接入总线出现 bus-off/新增超时仍全局停机。CAN3 空载 + CAN2 七台轮询实测通过 |
| 2026-11-21 整组异常停机排查 | 定位到主机“全局新鲜检查后逐台 enable”的时序问题（某台变旧/不静止导致异常并触发 STOP 锁存），改为逐台等待/失败跳过、位置基准前等待整组静止；修复后 6 轮常规 + 5 轮加压整组测试全部通过。固件新增停机原因码与 `0x8F` 调试帧；见[排查记录](docs/validation/2026-11-21-multi-stop-investigation.md) |
| 2026-11-21 可视化调参 | 窗口新增 **全部使能（零力矩）** 与 **复位开发板（清锁存）**；逐台/整组使能、MIT 力矩/位置/速度、CSV 记录；[调参流程](docs/Robot14_Tuning_Workflow.md) |
| 当前电机实验 | **CAN2**（PB13 TX / PB12 RX，1 Mbps），RS00 ID1–3、RS10P ID4–7；CAN1（PA12/PA11，500 kbps）接电源板/BMS。电源板 VMBUS 约 53.3 V 正常，BMS 仍无应答 |
| 设备与整机联调 | CAN2 七台已联调；CAN3/ID8–14 尚未接入；BMS 未应答；额定力矩/温升/机械行程未验收 |
| 后续固件开发 | 关节级零点/方向/限位、周期与目标处理、状态机、电源安全联锁待实现与验证 |
| 2026-10-27 基础CAN | 内部回环及PC触发板端返回报文已验证；不等同于电机通信通过 |
| 2026-11-14 后续实测记录 | 已取得双电机参数/目标回读、实际位置/速度/Iq及停止确认记录；存在位置跳变、停止后位置不稳定等问题；见[验证索引](logs/2026-11-14/README.md) |
| 当前开发控制台 | Windows / Ubuntu原生控制台、日志查看器、位置/速度滑块、可设置时长、双机联调、限流与受阻报警；[使用说明](docs/Motor_Tuning.md) |
| 软件验证 | 本地合并后 **49 项**固件主机测试；Robot14 相关 **55 项**固件主机测试、**167 项**界面测试通过；构建/仿真通过不替代硬件验证 |
| Ubuntu发布包 | 2026-11-15 Ubuntu24.04 x86_64原生包，含最新界面/实验及离线编译和OpenOCD烧录工具；[下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.15) · [使用和验证边界](docs/Ubuntu_20261115.md) |
| Windows发布包 | 用户提供的2026-11-14 Windows-x64快照；[发布下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.14)，不能在Ubuntu上运行；Ubuntu见下方独立发行包 |

历史失败日志保留，不用软件PASS覆盖原始数据；本次上传前只删除未引用的中间探测/失败轮次，文档引用的证据目录均保留。

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
| [Robot14 调参流程](docs/Robot14_Tuning_Workflow.md) | 逐台/整组使能、力矩/位置/速度、异常处理与 CSV 记录 |
| [固件开发计划](docs/firmware-development.md) | 九项工作、推进顺序、超时 / 错帧 / 断连与恢复验收 |
| [协作与资料分工](docs/collaboration/README.md) | 已知信息、固件侧工作、需其他组确认的事项与可选表格 |
| [GitHub 合并前整理](docs/repository-upload.md) | 上传范围、本地归档、证据校验与增量合并建议 |
| [参考资料](docs/resources.md) | 项目资料、设备协议、官方手册和工具入口 |

## 工程与日志下载

- **[桌面开发控制台与日志查看器](docs/desktop-workbench.md)**：Windows / Ubuntu 原生程序、迁移步骤、USB 权限及运行环境说明；[Windows下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.14) · [Ubuntu下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.15)。

- [完整原始工程 ZIP](archives/PICO_CAN_20261027.zip) · [已展开源码](firmware/PICO_CAN/) · [六个烧录文件](firmware/PICO_CAN/IMPORT.md#六个原始固件文件)
- [本轮原始日志](logs/2026-10-27/) · [全部历史日志索引](docs/validation/log-archive.md)

## 下一步

1. 接入 CAN3 的 ID8–14 并复测：总线隔离已按“真正接入”判定，空载 CAN3 不再拖死 CAN2。
2. BMS 仍无应答：检查 BMS 接线、供电与 500 kbps 设置；电源板已正常（VMBUS 约 53.3 V）。
3. 继续定位位置反馈跳变、停止后位置不稳定；保留每台 UID、时间、增益与原始 CSV，固件 `0x8F` 调试帧会给出停机原因。
4. 完成额定力矩下的温升、负载、停止确认与电源安全联锁验收；补关节级零点/方向/限位后再做整机动作。
5. 在目标 Ubuntu 电脑上复验 USB 权限、ST-LINK 烧录与七台整组调参流程。

相关项目：[机械设计](https://github.com/pico-humanoid/pico-mechanism) · [电气设计](https://github.com/pico-humanoid/pico-electronics)

工具资料：[Waveshare USB-CAN-A 官方说明](https://www.waveshare.net/wiki/USB-CAN-A) · [全部参考资料](docs/resources.md)

## 14 电机整机驱动（2026-11-16，2026-11-21 实机更新）

新增独立 `Robot14` 镜像：CAN2/3 各 7 台 RS00/RS10P，1Mbps 扩展帧；CAN1 融合原 BMS+电源板双设备 500K 读取，160MHz + CMSIS-RTOS2/FreeRTOS。默认只读、人工显式使能。

2026-11-21 实机更新：

- CAN2 的 ID1–7 全部打通，可逐台和整组使能；逐台力矩/位置/速度与七台整组测试完成（空载、小幅度）。
- 总线判定改为按“是否真正接入”：空载 CAN3 只探测、不再触发全局锁存；已接入总线故障仍全局停机。
- 可视化窗口新增 **全部使能（零力矩）** 与 **复位开发板（清锁存）**；[调参流程](docs/Robot14_Tuning_Workflow.md)。
- 固件新增停机原因码与 `0x8F` 调试帧；整组异常停机的排查与修复见[记录](docs/validation/2026-11-21-multi-stop-investigation.md)。
- 构建、接口、CubeMX 与安全边界见 [Robot14 驱动说明](docs/Robot14_Driver.md)；对调诊断见[记录](docs/validation/2026-11-21-can12-swap.md)。
