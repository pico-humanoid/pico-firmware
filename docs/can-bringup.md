# CAN 验证配置、串口消息与日志采集

本文记录 NUCLEO-G474RE 验证工程的通信参数、报文与操作流程。硬件与引脚见[接线文档](hardware/README.md)，实际结果见[2026-10-27 测试记录](validation/2026-10-27.md)，项目进度见[仓库首页](../README.md)。

## 开始前

按[硬件与接线](hardware/README.md)连接开发板、收发器与 USB-CAN，核对 3.3 V 供电和总线两端的终端电阻。日志使用 LPUART1（PA2 TX、PA3 RX）经 ST-LINK 虚拟串口输出。

## 三种速率与两类 COM 口

| 通路 | 设置 | 作用 |
| --- | --- | --- |
| 开发板 ST-LINK 虚拟串口 | 115200 bit/s，8 数据位、无校验、1 停止位（8N1） | 从 G474 的 LPUART1 读取文本日志 |
| USB-CAN-A 电脑端串口 | 默认 2000000 bit/s | USBCAN 软件与适配器之间传输转换协议 |
| 当前外部 CAN 测试 | 1 Mbit/s，正常模式，经典 CAN | 适配器、收发器与 G474 之间的真实 CAN 通信 |

此前 Windows 上 ST-LINK 为 COM5、USB-CAN-A 为 COM6；端口号会随电脑和连接方式变化，使用前从设备管理器核对。采集脚本选择 ST-LINK 的 COM 口，USBCAN 软件选择适配器的 COM 口；两者可以同时工作。

USB-CAN-A 的驱动、配置工具与操作说明见[微雪官方文档](https://www.waveshare.net/wiki/USB-CAN-A)。适配器的串口速率和 CAN 位速率分别设置，不能将开发板日志用的 115200 套用到适配器端口。

## 基础收发测试报文

以下为经典 CAN 标准数据帧测试约定，标准 ID、数据帧、DLC 均需在 USBCAN 中正确选择。后续关节协议使用扩展帧，需另行配置。

| 方向 | 固定 ID | 首帧数据 | 单触发实验数量 / 末帧数据 |
| --- | --- | --- | --- |
| USB-CAN-A → G474 | `0x321` | `00 88 77 66 55 44 33 22` | 1 条触发帧 |
| G474 → USB-CAN-A | `0x123` | `00 22 33 44 55 66 77 88` | 100 条；末帧 `63 22 33 44 55 66 77 88` |

- 单触发功能的操作为：电脑发送一条有效 `0x321`，板端开始发送自己的 100 条 `0x123`，数据长度为 8 字节，返回间隔约 100 ms。
- 返回第一字节是测试序号 `00`—`63`（十六进制，即十进制 0—99），后 7 字节固定。
- 本轮功能核对要求电脑触发记录与板端 RX 对应，板端 100 条 TX_DONE 与电脑 100 条返回记录按 ID、DLC、数据和顺序一致。
- 已上传的[实际源码](../firmware/PICO_CAN/App/can_bringup.c)中，自动 PASS 条件仍要求板端 `rx_unique=100`，因此单次触发后会打印 FAIL。这个自动判据与单触发功能目标存在差异，原始 RESULT 保留，并在测试报告中解释。
- 若另做每方向 100 帧的测试，电脑侧保持 ID 为 `0x321`，仅使第一字节从 `00` 递增到 `63`，每 100 ms 发送一次。相同载荷重复 100 次不符合唯一序号要求。

2026-10-27 两端日志已验证“一条触发、100 条返回”。单触发功能核对通过，固件自动 RESULT 仍为 FAIL；后续若修改外部模式的自动判据，需重新编译、测试和记录版本，不能回写旧日志中的结果。

## 串口消息格式

逐帧日志的列顺序为：

```text
t_ms,event,format,id,dlc,data
```

| 字段 | 含义 |
| --- | --- |
| `t_ms` | 开发板启动后的毫秒数，不是电脑的日期时间 |
| `event` | `TX_SUBMIT`、`TX_DONE`、`RX` 等事件 |
| `format` | 帧格式；本次基础测试记录为 `STD`（标准帧） |
| `id` | CAN 帧 ID，使用十六进制文本 |
| `dlc` | 数据长度；本次为 8 |
| `data` | 按字节书写的十六进制载荷 |

外部实验的原始消息示例：

```text
11376,RX,STD,0x321,8,00 88 77 66 55 44 33 22
11381,TX_SUBMIT,STD,0x123,8,00 22 33 44 55 66 77 88
11386,TX_DONE,STD,0x123,8,00 22 33 44 55 66 77 88
```

`TX_SUBMIT` 表示固件提交发送，`TX_DONE` 表示记录到发送完成事件，`RX` 表示板端接收。这些事件分别记录，不将“提交成功”直接视为对端已经收到。

每轮末尾的 `# RESULT=...` 为汇总行，主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `RESULT` | 固件根据本轮测试条件给出的 PASS / FAIL |
| `tx_submit` / `tx_done` | 提交发送数 / 发送完成数 |
| `rx_unique` / `rx_missing` | 唯一接收序号数 / 缺少的预期序号数 |
| `rx_duplicate` / `rx_invalid` | 重复帧数 / 无效测试帧数 |
| `tx_submit_failed` | 发送提交失败计数 |
| `rx_fifo_lost_events` / `rx_queue_dropped` | 接收 FIFO 丢失事件 / 软件接收队列丢弃计数 |
| `rx_read_failed` / `tx_event_lost_events` | 读取接收失败 / 发送事件丢失计数 |
| `bus_off_events` / `fatal` | Bus-off 事件 / 致命错误标志或计数 |
| `tec` / `rec` | 汇总时报告的发送 / 接收错误计数器值 |

`rx_missing` 由预期序号集合计算，解释时要同时核对电脑端实际发送记录。本轮 `rx_missing=99` 与电脑仅发送 1 帧相符，不能据此计算物理总线丢包率。

## 每次如何采集日志

以下启动项和脚本已收录在 [firmware/PICO_CAN](../firmware/PICO_CAN/)。原机工程路径为 `D:\STM32Projects\PICO_CAN`，换位置使用时以实际工程目录为准。原脚本依赖已安装的 Windows STM32 工具及对应路径，配置说明见[工程导入说明](../firmware/PICO_CAN/IMPORT.md)。

| 本地启动项 | 作用 |
| --- | --- |
| [03_Flash_Loopback.cmd](../firmware/PICO_CAN/03_Flash_Loopback.cmd) | 经 flash.ps1 加载 build/Loopback/PICO_CAN.elf，测试控制器内部发送与接收 |
| [04_Capture_Log.cmd](../firmware/PICO_CAN/04_Capture_Log.cmd) | 调用 capture.ps1，读取 ST-LINK 虚拟串口并保存 CSV，不负责烧录 |
| [05_Flash_External.cmd](../firmware/PICO_CAN/05_Flash_External.cmd) | 经 flash.ps1 加载 build/External/PICO_CAN.elf，运行外部收发测试 |

只有切换实验模式或修改固件后才需要重新烧录，开发板运行最近一次烧入的版本。内部回环不经过外部收发器和线束，结果与外部收发分别记录。

1. 连接 ST-LINK USB 数据线，确认开发板虚拟串口编号，关闭占用同一串口的其他软件。
2. 根据实验选择内部回环或外部收发固件；外部测试先配好 USB-CAN-A 并暂停发送。
3. 运行 `04_Capture_Log.cmd`。若自动识别失败，使用下面的命令并替换实际 ST-LINK 端口号。
4. 看到 `Serial ... opened` 和 `Saving to ...` 后，再按开发板 RESET，采集从启动开始的完整记录。
5. 内部回环复位后自动执行；外部单触发实验复位后，从 USBCAN 发送一条已约定的有效触发帧，等待板端返回 100 帧。如另做每方向 100 帧测试，再使用递增发送配置。
6. 等待 `# RESULT=` 或采集超时，再查看本轮 CSV。外部测试还需在 USBCAN 中单独导出收发记录。

```powershell
powershell -ExecutionPolicy Bypass -File "D:\STM32Projects\PICO_CAN\scripts\capture.ps1" -Port COM5 -Seconds 60
```

COM5 仅为示例。采集串口固定使用当前程序的 115200 8N1，默认采集上限为 60 秒，可通过 `-Seconds` 调整；脚本收到 `# RESULT=` 后会提前结束，失败前已经收到的日志也会保留。

每次启动采集时按电脑时间创建文件：

```text
D:\STM32Projects\PICO_CAN\logs\board_YYYYMMDD_HHMMSS.csv
```

未开启采集时，开发板仍可运行，但串口输出不会自动保存到电脑。保留启动信息、列头、全部逐帧记录和末尾 RESULT，并记录固件版本、模式、接线及工具设置。

如果在克隆后的 `firmware/PICO_CAN` 中运行，新 CSV 会保存到该工程自己的 `logs` 目录；仓库根目录按日期整理的 `logs/2026-10-27` 是已归档实验记录，脚本不会自动将新日志发布到 GitHub。原工程的 20 份历史 CSV 已[原样保留](../firmware/PICO_CAN/logs/)，其状态见[日志索引](validation/log-archive.md)。

## 板载状态灯

当前验证程序使用 NUCLEO 板载 PA5 / LD2：慢闪为等待或测试中，常亮为测试通过，快闪为失败。后续蜂鸣器和两个外接 LED 的接线约定见[提示器件引脚](hardware/README.md#已约定的提示器件引脚)。
