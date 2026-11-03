# BMS / 电源板只读固件与硬件验收

更新：2026-11-03。平台：Ubuntu 22.04、NUCLEO-G474RE、FDCAN1；设备侧对照使用USB-CAN-A。

**当前结论（截至 2026-11-03，含当日双设备软件验证）：**

- **USB-CAN → 电源板 500K**：26 轮/312 次，60 秒级窗口通过，`Can_baud=2`。
- **USB-CAN → BMS 500K**：65 轮/325 次，60 秒级窗口通过，CRC 全过。
- **USB-CAN → 电源板 500K 无共地单轮**：12/12，仅为该次条件下的对照，不是所有拓扑无需参考地或隔离的证明。
- **G474 → 电源板/BMS**：未通过；G474 侧 `LEC=5`、0 TX_DONE/0 RX、bus-off。现有排查主要指向 **SN65HVD230 模块驱动/接收异常**（11/1 同模块 1M 曾通过，之后曾有 TX/RX 反接），仍需更换模块后复测闭环，不能据此永久排除所有电气因素。
- **双设备软件（2026-11-03）**：新增`Dual-Read-500K`，BMS与电源板共用FDCAN1、500K；交叉编译及主机测试已通过，尚未烧录/实机验收。详见**第9节**。
- 已完成/失败清单与对应日志见 **第 8 节**；旧过程记录已归档，不再逐条展开。
此文档对应开发计划中的协议模块、通用收发层、单设备读取三项工作，不代表机器人全部业务已完成。

## 1. 本轮完成与范围

新增链路：

```text
main.c：按 PICO_APP 选择应用
  → device_read_app.c：启动、串口日志、状态灯
    → device_reader.c：轮询、超时、有限重试、数据新鲜度
      → protocol/{bms,power}_protocol.c：只读请求与回复解析
    → transport/can_transport.c：FDCAN1 硬件收发、接收队列、发送事件与错误计数
```

- `App/protocol/can_frame.h`：不依赖 HAL 的经典 CAN 帧，区分 STD/EXT、DATA/RTR、DLC 0～8。
- `App/protocol/bms_protocol.*`：构造 BMS 远程查询，检查 CRC，解析电压、电流、容量、SOC、温度等。
- `App/protocol/power_protocol.*`：查询版本、两种状态和九项可读参数；保留完整 ID、状态和参数原始数据。
- `App/device_reader.*`：顺序轮询，一次一个待回复查询，统计失败与超时；独立记录各类数据的更新时间。
- `App/transport/can_transport.*`：正常模式 FDCAN1，支持 500 kbit/s、1 Mbit/s，按设备过滤，ISR 仅收帧入队、不打印串口。
- `App/device_read_app.*`：将上述模块接入固件，输出原始收发记录、解析值和健康信息。
- `scripts/capture_device.py`：采集 **G474 的 ST-LINK 虚拟串口**日志；不是 USB-CAN-A 协议程序。
- `tests/` 与 `scripts/test-host.sh`：协议、调度、模拟 HAL、实际应用层和伪终端采集测试。

原 `App/can_bringup.c`、归档镜像、原始日志未修改。`main.c` 在 USER CODE 区选择应用；CMake 每次只链接一种应用，避免 HAL 回调冲突。

### 只读边界

以下边界针对普通 `BMS` / `Power` / `Dual` 读取镜像；独立的 `PowerBaud` 测试镜像（历史过程已归档）不能称为严格只读镜像。普通镜像不链接写入测试模块。

- BMS 只查询 `0x100/0x101/0x102/0x103/0x105`，不写 EEPROM/保护参数。
- 电源板仅发送类型 `0x05` 版本、`0x02` 状态、`0x07` 参数读取；不发送 `0x01` 控制、`0x08` 参数写入或恢复默认。
- 没有自动改设备位速率、自动控制支路、自动重启设备。
- `BMS`/`Power`镜像各服务一类设备；`Dual`镜像服务**同一FDCAN1总线上的BMS和电源板**。尚未实现FDCAN1/FDCAN2双总线同时读取。
- USB-CAN-A 电脑端只读工具已位于仓库根目录 `tools/usb_can_power_probe.py` 与 `tools/usb_can_power_read.py`；与 G474 串口采集脚本不同。

## 2. 协议依据与尚待确认项

来源见 [参考资料](resources.md)：电气仓库的《嘉佰达 CAN 通讯协议定义》、电源板《使用说明 V1.5_20260507》。本轮读取的原件 SHA-256：

```text
BMS DOCX: d49b1f708cb55812b13b781d0abd77f44c5afa96d0bd45376287c947b4983034
电源板 PDF: 181f8fc5c1e8ea53923fe887f5f4f9a57a984d82376ee32dd0024fe7cc96ac7d
```

### BMS

- 文档默认 **500 kbit/s、11 位标准帧**；主机发 RTR，BMS 用相同 ID 的 DATA 帧回复。
- 单设备BMS镜像查询RTR默认DLC=8，没有8字节请求载荷，可配置成DLC=0。新增Dual预设明确使用此前USB-CAN已验证的DLC=0；G474双设备链路仍需实机验收。
- 回复默认 DLC=8。前 6 字节 CRC16，初值 `0xFFFF`、反射多项式 `0xA001`。
- 数据字按文档高字节先传；CRC 字段默认 BIG，可单独配置 LITTLE，不会改变数据字段字节序。
- 温度采用 `0.1°C = 原始值 - 2731`；输出 `temperature_decic=250` 表示 25.0°C。
- `0x104` 文档 CRC 描述不一致，本轮不查询，避免伪造确定性。
- 文档称位速率可定义，但未找到明确修改命令，**没有编造 BMS 改速率指令**。

### 电源板

- 文档默认 **1 Mbit/s、29 位扩展数据帧、DLC=8**。
- 请求 ID 为 `(通信类型 << 24) | POWER_ID`；回复按 ID 的 bit16～23 匹配来源。
- `POWER_ID` 默认配置为 `0xAA`，必须核对实际板卡 ID。
- 2026-11-01 用户已确认类型 `0x03` / `0x04` 状态使用大端序，默认及两个 Power Linux 预设均改为 `BIG`；保留 RAW/LITTLE 调试选项及原始字节。这不改变参数索引/float 的小端编码。
- 类型 `0x03` 的 ID 中电流字段描述存在冲突，**无论字节序如何配置都不解析该电流**；完整 ID 保留在日志。
- 参数索引使用小端。`uint8_t` 参数取回复 Byte4，保留 Byte5～7 和 `tail_nonzero`；float 参数按小端 IEEE binary32 解码。当前实物 `Can_baud` 回复值区 `01 01 00 03`，不能整体作为 LE32 枚举。
- `Can_baud` 代码：`1=1M、2=500K、3=250K、4=125K`。读取程序能识别四种参数值，但当前传输层只支持 500K/1M。
- 文档描述类型 `0x08` 参数修改重新上电生效；本轮只有读取，不包含写入过程。

**尤其注意：构建 `Power-Read-500K` 只改变 G474 的通信速率，不会把电源板从 1M 改为 500K。**
若电源板仍为 1M，该固件读不到它是预期现象。不要把不同位速率的节点放在同一条活动总线上尝试通信。

## 3. 无硬件测试与构建

从仓库根目录：

```bash
cd /home/zjy/PICO/pico-firmware

# 主机测试：不访问真实设备
./firmware/PICO_CAN/scripts/test-host.sh

# 只构建三个设备读取镜像
./firmware/PICO_CAN/scripts/build.sh Devices

# 或构建全部五种：原回环、原外部测试及三个设备读取镜像
./firmware/PICO_CAN/scripts/build.sh All
```

也可以分别执行：

```bash
./firmware/PICO_CAN/scripts/build.sh BMS-Read-500K
./firmware/PICO_CAN/scripts/build.sh Power-Read-1M
./firmware/PICO_CAN/scripts/build.sh Power-Read-500K
```

每个输出目录中均有 `PICO_CAN.elf`、`PICO_CAN.hex`、`PICO_CAN.bin`：

```text
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-BMS-Read-500K/
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Power-Read-1M/
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Power-Read-500K/
```

设备读取模式由 `PICO_APP=BMS/Power` 选择，固定使用正常 CAN 模式。`PICO_EXTERNAL_CAN` 仅用于原 `Bringup`，不能用它将设备读取镜像切成回环。

### 配置实物差异

```bash
cd /home/zjy/PICO/pico-firmware/firmware/PICO_CAN

# 示例：实际电源板 ID 是 AB；尚未确认状态字节序
cmake --preset Linux-Power-Read-1M -DPICO_POWER_ID=0xAB -DPICO_POWER_STATUS_ENDIAN=RAW
cmake --build --preset Linux-Power-Read-1M --parallel 4

# 仅在协议补充资料/抓包确认后，明确指定状态小端
cmake --preset Linux-Power-Read-1M -DPICO_POWER_STATUS_ENDIAN=LITTLE
cmake --build --preset Linux-Power-Read-1M --parallel 4

# 示例：实物要求 RTR DLC=0，CRC 低字节先传
cmake --preset Linux-BMS-Read-500K -DPICO_BMS_RTR_DLC=0 -DPICO_BMS_CRC_ENDIAN=LITTLE
cmake --build --preset Linux-BMS-Read-500K --parallel 4
```

以上是配置方法，不是对真实设备参数的断言。默认参数：`POWER_ID=0xAA`、`RTR_DLC=8`、`BMS_CRC_ENDIAN=BIG`、`POWER_STATUS_ENDIAN=BIG`。

**CMake 缓存会保留手动修改。** `build.sh` 不会自动清除这些覆盖值。需要恢复默认时，重新带上上述默认参数配置对应预设；注意不同预设有独立缓存。可核对 `build/<预设>/CMakeCache.txt`，并在上电日志确认实际参数。

## 4. 硬件到位后的烧录与日志

### 4.1 接线和前提

沿用 [硬件接线说明](hardware/README.md)：FDCAN1 为 PA12/TX、PA11/RX，经正确供电的 CAN 收发器连接设备 CANH/CANL；**MCU 引脚不能直接接 CANH/CANL**。核对电平、公共参考地、两端终端电阻及设备供电，不在不明确的电池动力接线处试接。

日志为 LPUART1 PA2/TX、PA3/RX，115200、8N1，通过原 ST-LINK VCP 通道采集。只查询 CAN 不代表可以省略安全供电和接线检查。

### 4.2 烧录示例

接好 ST-LINK 后，从工程目录执行。以下命令会真实改写目标 Flash；本次 16:46 验收由用户预先完成烧录，采集期间未再次执行烧录。

```bash
cd /home/zjy/PICO/pico-firmware/firmware/PICO_CAN

# BMS 500K
openocd -f interface/stlink.cfg -c "transport select hla_swd" \
  -f target/stm32g4x.cfg -c "adapter speed 1000" \
  -c "program build/Linux-BMS-Read-500K/PICO_CAN.elf verify reset exit"

# 电源板默认 1M：需要时单独执行，不是紧接着覆盖 BMS 固件
openocd -f interface/stlink.cfg -c "transport select hla_swd" \
  -f target/stm32g4x.cfg -c "adapter speed 1000" \
  -c "program build/Linux-Power-Read-1M/PICO_CAN.elf verify reset exit"
```

电源板已独立确认改成 500K 并重新上电后，再将路径换成 `build/Linux-Power-Read-500K/PICO_CAN.elf`。

如 USB 权限不足，按 [Linux 工具链](linux-toolchain.md) 处理设备权限；不要通过改写未知设备或反复更改供电参数来排查权限问题。

### 4.3 采集

```bash
cd /home/zjy/PICO/pico-firmware/firmware/PICO_CAN
python3 -m serial.tools.list_ports -v

# /dev/ttyACM0 仅为示例，必须选择 ST-LINK VCP，不是 USB-CAN-A 的串口
python3 scripts/capture_device.py \
  --port /dev/ttyACM0 --output /tmp/bms-read-500k-01.csv \
  --label BMS-Read-500K --duration 60
```

看到 `READY` 后手动复位 G474，以记录完整启动配置和第一轮查询。脚本按原字节保存（含 `#` 注释行），同时生成 `.csv.json` 元数据；不向串口发送数据，不覆盖已有文件。电源板测试换一个输出名及标签。

- 默认无数据 10 秒停止，可通过 `--idle-timeout` 调整。
- 有限时长采集正常结束返回 0，**只表示采集完成，不表示设备 PASS**。
- 串口错误/空闲超时返回 1；Ctrl+C 返回 130，保留已采集内容。
- 新固件日志格式不同于原 100 帧测试，**不要用原 `check_log.py` / `RESULT=PASS` 判据验收**。

## 5. 如何读日志、判断结果

原始行格式：

```text
t_ms,event,channel,format,kind,id,dlc,data
1000,TX_SUBMIT,FDCAN1,STD,RTR,0x00000100,8,
```

- `TX_SUBMIT`：HAL 接受了请求，不等于已在总线上成功发送。
- `TX_DONE`：读取到控制器发送事件，不等于设备业务回复；时间是主循环观察时间，不是硬件发送时间戳。
- `TX_TIMEOUT`：请求 300 ms 内未观察到完成，撤销尚挂起的硬件发送请求。可能是发送失败，也可能是发送事件丢失；要结合回复、TEC/REC 和统计排查。
- `RX`：完整收到的帧；仍需协议检查才能计为有效数据。RTR 行没有数据载荷，即使 DLC=8。
- `# BMS` / `# POWER`：通过格式、ID、长度及适用的 CRC 等检查后输出解析。电源板 `UNCONFIRMED_ENDIAN` 是明确未确认，不是零电压或零电流。
- `# HEALTH`：每 5 秒汇总。`invalid` 是已知协议帧校验失败，`ignored` 是不属于当前查询集的帧；硬件过滤器已拒收的帧不会出现在这两个计数里。

`seen` 表示启动以来曾收到哪些有效查询类别；`valid` 表示这些类别是否仍在 10 秒新鲜度窗口内：

- BMS bit0～4 依次为 `0x100/101/102/103/105`，全部新鲜为 `0x1F`。
- 电源板 bit0～11 依次为版本 / 状态03 / 状态04 / Can_baud / Com_baud / remoteCtrl / fanspeedCtrl / POWER_ID / soundEffect / currocpt / sdT / arTime，全部新鲜为 `0x0FFF`。原 `0x0F` 只覆盖四项，不再表示本版全部成功。
- `valid` 只说明协议可接受且新鲜，**不保证 RAW 字段已解析、不保证物理数值正确**。
- 调试器可读取 `g_device_reader`：各类原始/解析值、`last_ok_ms[]` 和错误计数。
- LD2 只在所有查询类别新鲜且未 bus-off 时点亮，不能单独作为硬件验收结论。

时序默认启动后 1 秒开始查询，回复超时 500 ms、查询/重试间隔 200 ms，每类最多 3 次尝试后转下一类并持续循环。控制器自动重发关闭，重试由调度器管理；`tx_rejected` 与回复超时分开统计。协议没有事务序号，跨重试的迟到回复无法完全区分，已在调度器注释说明。

收发层还统计硬件 RX FIFO 丢失、软件队列溢出、读取错误、发送事件丢失/未知事件及 bus-off。软件接收队列可用 31 帧，不提供无限缓冲；当前是低频只读验收应用，不是高负载整机日志方案。

bus-off 后禁止新提交，不自动恢复，先排除位速率/接线/终端问题，再复位重试。UART 发送失败后应用停止后续查询，避免继续产生无法记录的测试流量；错误发生前已提交的硬件请求仍需按真实总线状态分析。

## 6. 推荐硬件测试顺序

1. **只接 BMS，G474 500K。** 确认 STD/RTR 请求与同 ID 的 DATA 回复，检查 CRC、SOC、正负电流、温度和容量是否与独立读数一致。
2. **只接电源板，G474 1M。** 核对设备 ID、版本、状态03/04、Can_baud=1；用抓包/厂商补充资料确认状态字节序，重新构建后核对数值。若参数读不到，要单独检查索引/编码，不把其他已收到的数据当作全部成功。
3. **USB-CAN-A 独立读取交叉验证。** 适配器需使用相同速率、帧格式和只读报文；可使用仓库根目录 `tools/` 下两个只读脚本。保存原始 ID、DLC、字节和时间作对照。
4. **另行验证电源板改速率。** 必须先确认写参数步骤、保存方式、断电重上电和回退方案；本轮程序不会执行写入。实际改好后使用 Power-Read-500K，确认通信与 Can_baud=2；同时验证原 1M 设置不再正常通信。不能仅凭主机配置切换就宣告设备改速成功。
5. **再决定同时读取方案。** 若无法统一位速率，需要两条物理 CAN 总线、两个收发器与 FDCAN1/FDCAN2 支持；目前不具备双总线固件，不能把两种默认速率的设备直接并到同一总线。

建议每个正确配置连续采集至少 60 秒，并补做未接设备、错误速率、错误 ID、断开再恢复等故障测试。查看 `query_failures`、丢帧、bus-off 和 `valid` 过期行为，保留真实原始日志；电池/动力线操作须按设备安全规程进行。

## 7. 初版离线验证记录（2026-10-31，历史）

- 原 Loopback / External，加 BMS-500K / Power-1M / Power-500K 共五种 Linux 预设构建成功，产生 ELF / HEX / BIN。
- 5 项 CTest 全部通过：协议与调度、模拟 HAL 收发、Power 应用层、BMS 应用层、Linux PTY 日志采集（其中 Python 内含 4 项测试）。
- C 测试覆盖正常/错误 CRC、错误 DLC/格式/来源、端序、只读请求白名单、有限重试、时间回绕、过期、延迟帧、TX 提交/完成区分、撤销与硬件缓冲复用、队列丢帧、bus-off 和 UART 故障等。
- 启用 AddressSanitizer / UndefinedBehaviorSanitizer 后五项 CTest 亦全部通过。sanitizer 用于 C 主机测试；Python PTY 测试不受 C sanitizer 检查。某些沙箱的 ptrace 限制会使 LeakSanitizer 无法启动，需要在允许的宿主环境运行，不能误当作固件运行结果。
- 另行编译通过 RTR=0 / CRC 小端、状态 BIG/LITTLE 和不同设备 ID 组合；7 种非法构建配置均按预期拒绝。
- 无实物，未验证真实 CAN 时钟、电气信号、设备固件版本、滤波与 ACK、实际 CRC/端序、设备改速率及双总线同时读取。

结论：已提供可编译、可离线测试、可按配置烧录的单设备读取软件。硬件到位后可以从本说明直接开始测试，但仍可能需要依据实物调整配置或补充协议细节，不能保证完全无需改动。

## 8. 测试结果汇总（2026-11-03 整理）

> 本节替代原第 8～12 节的过程记录，只保留当前结论对应的已完成/失败测试与证据。未纳入发布的中间日志保留于本地归档（Git 忽略，不随仓库上传）；公开保留的证据见第 8.4 节及仓库根目录 `logs/README.md`；`logs/2026-10-27/` 等第 1～7 节引用的历史日志不在本次清理范围。

### 8.1 已完成并通过

| 日期 | 测试 | 结果 | 主要日志 |
| --- | --- | --- | --- |
| 2026-11-01 | G474 → 电源板 1M 只读 60 秒 | **PASS**：TX_SUBMIT/TX_DONE/RX 各 300，12 类×25，`seen=valid=0xFFF`，TEC=REC=0 | `../logs/g474/20261101-164647-power-read-1m-fresh.log`（`.verified.log`/`.analysis.json`/`.chunks.jsonl.gz`/`.log.json` 同前缀） |
| 2026-11-02 | USB-CAN → 电源板 500K，26 轮 | **PASS**：312/312，首末回复跨度 69.913599 秒，`Can_baud=2` | `../logs/usb-can/20261102-211204-975831-baud-validation.jsonl` + `.analysis.json` |
| 2026-11-02 | USB-CAN → BMS 500K，65 轮 | **PASS**：325/325，CRC 全过，跨度 71.399980 秒 | `../logs/usb-can/20261102-215849-134211-bms-read.jsonl` + `.analysis.json` |
| 2026-11-03 | USB-CAN → 电源板 500K，无共地，1 轮 | **PASS**：12/12，`Can_baud=2`，V1.08 | `../logs/usb-can/20261103-003114-351422-baud-validation.jsonl` + `.summary.json` |
| 2026-11-02 | G474 PA12↔PA11 跳线环回 | **PASS**：13/13 `match=1` | `../logs/g474/20261102-2340-pin-loop-resume.log` + `.run-summary.json` |

- 电源板/BMS 的两个 500K 通过结果为 60 秒级窗口；无共地单轮只用于隔离“速率/总线/共地”，不替代 60 秒窗口。
- 主机 CTest 11/2 历史记录为 11/11；11/3 最新普通及 ASan/UBSan 测试均为 13/13，见第 9 节。均仅为软件测试，不作为硬件通过证据。
- 11/1 的 G474→电源板 1M 是历史基线；11/2 之后同一模块出现回归（见 8.2）。

### 8.2 失败与无效测试

| 日期/时间 | 测试 | 结果 | 原因/判读 | 主要日志 |
| --- | --- | --- | --- | --- |
| 2026-11-02 18:39/18:46 | G474 → 电源板 1M 只读 | 失败：16 TX_SUBMIT、0 TX_DONE、0 RX，TEC→248，bus-off | 当时 TX/RX 已反接或模块已受损；后续定位为 SN65HVD230 损坏 | `../logs/g474/20261102-184636-power-read-1m-repowered-confirm.log` |
| 2026-11-02 21:34～21:57 | USB-CAN → BMS 多次首条查询超时 | 失败/未闭环 | BMS 启动/唤醒偶发无回复；随后 65 轮通过，根因未闭环 | `../logs/usb-can/20261102-215716-964058-bms-read.jsonl` |
| 2026-11-02 22:46/23:18/23:30 | G474 → BMS 500K 只读 | 失败：16 TX_SUBMIT、0 TX_DONE、0 RX、0 条 BMS，`LEC=5`，bus-off | 同一模块损坏；BMS 两线无地是待评估的拓扑因素，不是本轮主因 | `../logs/g474/20261102-2246-g474-bms-500k-dlc0.log` + `.run-summary.json`；`../logs/g474/20261102-2330-g474-bms-500k-txrx-fixed.log` |
| 2026-11-03 00:12 | G474 → 电源板 500K（未上电） | **无效** | 电源板未上电，不能作为 DUT 失败结论 | 已归档，不再引用 |
| 2026-11-03 00:18/00:36 | G474 → 电源板 500K 只读 | 失败：10～17 TX_SUBMIT、0 TX_DONE、0 RX、0 条 POWER，TEC→248，bus-off | 电源板已确认 500K；USB-CAN 无共地 12/12 成功；剩余为模块带载驱动损坏 | `../logs/g474/20261103-0018-g474-power-500k-powered.log`；`../logs/g474/20261103-0036-g474-power-500k-term-on.log` |
| 2026-11-03 00:20 | G474 → 电源板 1M 交叉验证 | 失败：17 TX_SUBMIT、0 TX_DONE、0 RX、0 条 POWER，TEC→248，bus-off | 电源板实际为 500K，1M 本就不匹配；同时模块已损坏 | `../logs/g474/20261103-0020-g474-power-1m-crosscheck.log` |
| 2026-11-03 01:09 | PinLoop 模块本地环回（120Ω 终端） | 失败：PA12=0 时 PA11=1；H/L 仅 0/0.2V | 模块 RXD/总线驱动损坏 | `../logs/g474/20261103-0109-pinloop-load-test.log` |

**已排除项：**

- G474 PA12/PA11：跳线环回 13/13；FDCAN 位时序 `NBTP=0x02010C01`（500K）。
- 电源板 500K、CANH/CANL、终端、共地：USB-CAN 无共地 12/12，`Can_baud=2`。
- BMS 协议/CRC：USB-CAN 325/325、60 秒窗口通过。
- 当前判断：异常集中于 **SN65HVD230 模块**；存在历史通过、后续 TX/RX 反接及带载异常记录。损坏机制和最终恢复结果仍需替换模块后复测确认。

### 8.3 下一步

1. 更换 SN65HVD230 模块；旧模块不再上电测试。
2. 换新后先跑 `Power-Read-500K` 60 秒：目标 `TX_DONE`、`# POWER`、`seen=valid=0xFFF`、`TEC=REC=0`。
3. 电源板通过后，再用同一新模块试 BMS 500K；若仍无回复，再评估 BMS 两线隔离方案。
4. 不把 USB-CAN 单轮读取、主机 CTest 或历史 1M 窗口扩大为当前硬件全验收。

### 8.4 GitHub 发布的日志保留范围

> 路径相对仓库根目录；8.1/8.2 的 `../logs/` 相对本文档目录。

- **保留原始证据：** 8.1/8.2 所列通过、失败和关键交叉验证的原始日志，以及对应采集元数据、窗口分析和运行汇总。不会因为测试失败而移除关键证据。
- **保留软件证据：** `logs/host/` 的协议、改速和最新双设备测试/构建记录；最新状态以 `20261103-dual-500k-validation.json` 为准。
- **保留诊断记录：** `logs/flash/` 的烧录校验、寄存器、bus-off 和引脚环回记录，体积很小且包含不同于普通采集的诊断信息。
- **无损压缩：** 11/1 的串口分片时间索引以 `20261101-164647-power-read-1m-fresh.chunks.jsonl.gz` 发布。解压字节与原 JSONL 完全相同，历史分析中的原文件 SHA-256 仍可核对。
- **不上传：** 重复控制台输出、运行标签、旧中间日志目录及整包清理备份；保留在 Git 忽略的本地归档中。控制台输出不是原始采集的替代，本次保留了对应原始数据和元数据。
- 原仓库已跟踪的 `logs/2026-10-27/`、工程包内历史日志、原始镜像和 ZIP 不变，不借清理之名重写既有记录。

完整公开文件清单与 SHA-256 见 `logs/evidence-manifest.json`，用途索引见 `logs/README.md`，整理规则见 `docs/repository-upload.md`。


## 9. 双设备500K固件完善与构建（2026-11-03）

### 9.1 拓扑、边界与实现

本镜像是**一条FDCAN1总线接BMS和电源板两个设备**，不是FDCAN1/FDCAN2双总线。沿用PA12=TX、PA11=RX，经外部CAN收发器连接总线；BMS与电源板都必须已工作于500K。镜像不会自动修改设备速率、写参数、控制MOS或支路。此前第8节的硬件失败结论保持不变。

- 新增`/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/App/dual_device_reader.c`与`.h`，维护两套独立DeviceReader状态，按设备交替调度，总共最多一个待回复查询。两设备的查询索引分别推进，BMS5类、电源板12类，不要求轮数相同。
- BMS：STD RTR、DLC0、CRC大端，只读0x100/101/102/103/105；电源板：EXT DATA、POWER_ID=0xAA、状态大端，只读版本、状态及九项参数。`PowerBaud`模块未链接进Dual镜像。
- 共享发送间隔至少200ms；单次回复超时700ms，每项查询只有一次尝试，超时后记录失败并轮询下一设备，不在同一查询内重试。设备后续轮询仍会再次读取该项，不是首次异常就停止整个固件。
- 两套数据各自维护seen/valid、回复、CRC/解析无效、超时、失败及轮询周期计数；cycles表示索引推进完整轮数，不等于成功轮数。数据超过10秒未更新则失效；一个设备持续超时可能延长另一设备的整轮时间，因此不能为了点亮LED而保留过期样本。
- 总线bus-off锁存后停发但继续老化两套数据，不自动恢复；串口日志输出失败后停发，避免静默继续测试。LD2只有两设备所有字段都新鲜且无总线/串口故障时才亮，不代表硬件验收PASS。
- 保留原始TX_SUBMIT/TX_DONE/RX日志及解析行，每5秒输出共享`# HEALTH,device=DUAL`和分别标记BMS/POWER的`# DEVICE_HEALTH`。健康状态下期望BMS `seen=valid=0x01F`，电源板 `seen=valid=0xFFF`；总线TEC/REC、收发丢失和超时计数仍须独立检查。

### 9.2 构建与产物

从任意目录执行：

```bash
bash /home/zjy/PICO/pico-firmware/firmware/PICO_CAN/scripts/build.sh Dual-Read-500K
```

对应CMake预设`Linux-Dual-Read-500K`，应用`PICO_APP=Dual`。CMake拒绝Dual使用1M，避免两设备在一条总线使用错误速率。`build.sh Devices`与`All`均包含此镜像，All共六种普通模式，改速测试镜像仍需单独显式选择。

产物：

```text
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Dual-Read-500K/PICO_CAN.elf
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Dual-Read-500K/PICO_CAN.hex
/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Dual-Read-500K/PICO_CAN.bin
```

本次Debug构建Flash占用33,424字节，链接器报告RAM占用6,632字节（含链接脚本预留）；BIN大小33,424字节。HEX重新转换出的BIN与生成的BIN逐字节一致，镜像不含PowerBaudTest符号。

### 9.3 软件验证与待验收

- 普通主机CTest **13/13通过**，AddressSanitizer/UBSan构建 **13/13通过**（`ASAN_OPTIONS=detect_leaks=0`）。新增双设备调度与应用层测试，并补充标准/扩展过滤器同时配置的模拟HAL检查。
- 覆盖正常双设备65秒模拟、任一设备持续无回复时另一设备继续查询、单设备错误不完成另一设备请求、无效CRC、发送拒绝、超时、数据失效、tick回绕、bus-off/串口故障停发、初始化失败。该模拟65秒不是硬件65秒测试。
- Loopback、External、BMS500K、Power1M、Power500K、Dual500K六种普通镜像，以及两个显式PowerBaud方向的交叉编译均通过；编译选项保留`-Wall -Wextra -Werror`。
- 构建、测试输出及产物SHA256记录在`/home/zjy/PICO/pico-firmware/logs/host/20261103-dual-500k-validation.json`及其中引用的日志。
- **本轮没有烧录、复位、打开串口或发送硬件CAN指令。** 软件构建完成，G474双设备500K硬件验收待进行；旧收发器故障不能通过软件编译消除。上板后应分别检查两设备完整查询集及各自超过60秒的有效回复窗口、CRC/查询错误、TX_DONE、TEC/REC和丢帧计数，不沿用只适用于电源板的分析器自动判定双设备PASS。
