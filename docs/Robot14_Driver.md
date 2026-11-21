# Robot14：14 电机 + CAN1 双设备驱动（2026-11-16）

## 1. 本次交付与边界

新增独立的 `PICO_APP=Robot14` 整机镜像，**不是把单机测试程序并排启动**。CAN1 复用已有的 `DualDeviceReader` / `DeviceReader` 与 BMS、电源板协议解析；CAN2/3 使用各自独立的发送状态、接收环与电机对象。旧测试镜像仍保留。

- “G474 主频 160hz”按 **160 MHz** 实现。
- 用户所称 RS10 按本次附件 **RS10P** 实现，不代用其他 RS10 型号参数。
- 本次只修改、编译和软件仿真，**没有烧录、复位开发板或使能电机**。
- 默认无故障启动仅查询电机参数；应用必须显式请求使能。收到电机故障时会发全局停机帧。
- 这是整机通信/驱动基础层，不包含步态、逆运动学、关节方向/机械零位标定，新增专用 14 电机监视/调参界面，见 `docs/Robot14_Tuning.md`；不使用旧单/双机串口控制协议。
- 已有电池/电源数据读取已融合；尚未制定整机欠压/过流/温度阈值、接触器/电源板切断策略。**不要把“数据已读到”理解为电源安全联锁已经完成。**

## 2. 总线与 ID

- **CAN1 / FDCAN1**：PA11 RX、PA12 TX，AF9；BMS + 电源板共用这一路，沿用原双设备配置 **500 kbps**。BMS 标准帧请求为 RTR/DLC0，CRC 大端；电源板扩展帧、设备 ID `0xAA`、状态大端。
- **CAN2 / FDCAN2**：PB12 RX、PB13 TX，AF9；RS00：ID **1、2、3**；RS10P：ID **4、5、6、7**。
- **CAN3 / FDCAN3**：PA8 RX、PA15 TX，AF11；RS00：ID **8、9、10**；RS10P：ID **11、12、13、14**。
- 两路电机总线均为 **Classic CAN / 29 位扩展 ID / 8 字节 / 1 Mbps**，不是 CAN FD；主机 ID 为 `0xFD`。
- 三路总线相互独立，不能把 CAN1 的 500K 与电机的 1M 接成同一物理总线。MCU 引脚须经对应 CAN 收发器，不直接接 CANH/CANL。
- 电机 ID、波特率须预先逐台配置好。本驱动**不自动修改 ID、波特率、机械零位或持久化参数**，也不能辨别同一总线上 ID 重复的两台实物。
- 按实物线路检查各路两端终端电阻、参考地、收发器供电及使能/静默脚。PA15 用作 CAN3 TX，调试采用 PA13/PA14 的 SWD，不使用完整 JTAG。

拓扑唯一配置：`firmware/PICO_CAN/App/robot/Peripheral/rs_motor.c` 的 `robot_motor_config`。

## 3. 手册协议核对与单位

依据本次提供的 `RS00使用说明书260713.pdf` 与 `RS10P使用说明书260907.pdf`：PDF 第 31–32 页类型 1/2；第 38 页参数表（以 PDF 页序为准）。

- 类型 1：运动控制；类型 2：反馈；类型 3：使能；类型 4：停机（不附带清故障）；类型 17：读取；类型 18：写入；类型 21：故障/警告反馈。
- RS00 类型 1/2 的速度编码量程 **±33 rad/s**，力矩 **±14 N·m**。
- RS10P 类型 1/2 的速度编码量程 **±13 rad/s**，力矩 **±42 N·m**。协议编码量程不等于额定或允许持续工作力矩。
- 两者类型 1/2 位置编码均为 **±12.57 rad**，Kp 为 0–500，Kd 为 0–5。类型 1/2 的 uint16 为大端，参数索引/参数原始值使用小端。
- `0x7019 mechPos` 是输出轴累计位置，`0x701B mechVel` 是输出轴速度。**这些物理值不再除以 25**。类型 2 的有限量程位置与累计位置不同，不能用其代替长行程多圈累计角。
- API 的 position / velocity / torque 分别为输出轴 **rad / rad/s / N·m**；具体机械零点与正方向还须逐关节标定。

调试阶段软件输入范围刻意比协议范围小：速度 ±1 rad/s，前馈力矩 ±1 N·m，Kp 0–5，Kd 0–1；拒绝 NaN/Inf 与越界值，不偷偷截断。提交时和 ACTIVE 每次安全检查还限制当前反馈下的估算阻抗合力矩不大于 2 N·m。

**这些只是调试软件防护，不是经过认证的力矩、速度、行程或电流硬限制。** MIT 阻抗控制中，“目标速度小”并不保证实际速度小。估算值、传感器误差、通信延迟、机械负载及编码量化仍影响实际输出。没有关节机械行程数据，当前不应驱动完整装配机构。零 Kp/Kd 的近零力矩命令也不能支撑重力负载。

## 4. 分层结构与所有权

参考 `new_dog2.4_6014` 的应用/模块/通信/外设/系统分层，但不复制其自动使能行为；将 `Periphal` 规范为 `Peripheral`：

```text
App/robot/
  System/robot_config.h          总线、主机与时间参数
  Peripheral/rs_motor.[ch]       RS00/RS10P 无状态编解码 + 拓扑
  Modules/motor_network.[ch]     14 独立节点、使能握手、安全状态机
  Communicate/robot_can.[ch]     三路 HAL 收发、独立 RX 环、TX 截止时间
  Communicate/robot_link.[ch]    二进制会话/压缩批量命令/节点遥测
  Communicate/robot_uart.[ch]    中断RX、时间戳、低优先TX、错误隔离
  Application/robot_app.[ch]     单一 CAN owner、命令队列、双设备融合、快照
  robot14.cmake                 本镜像及 FreeRTOS 构建源列表
```

- CAN IRQ 只接收、验证基本帧格式、写入所属总线的环形缓冲；不解析浮点、不打印、不调用 RTOS。
- 高优先级 `RobotComm` 任务独占 CAN 发送、电机状态机和双设备轮询。其他任务只通过 API 投递请求，**不要直接操作 hfdcan 或 MotorNetwork 全局状态**。
- 每路 RX 环 64 槽、有效容量 63；三路各自计数。命令队列 32 项，任务每轮最多处理 32 请求及每路 63 接收帧。
- 无无限软件 TX 队列；跟踪硬件 3 个 TX 槽，pending 超过 20 ms 请求撤销。统计 `tx_submitted` 仅表示 HAL 接受入队，**不等于已经获得总线 ACK**。
- 每个电机总线每轮最多提交一帧，节点轮转。控制目标周期 10 ms/节点（100 Hz），通信任务约每 1 ms 服务；这是调试初始调度，不是硬件验证过的硬实时承诺。
- CAN1 仍为原双设备交替读取：上电宽限 3 s、请求间隔 200 ms、应答超时 700 ms、每项最多 2 次、数据 10 s 过期。不加载单设备测试应用，也不写电源板控制参数。

## 5. 时钟 / CubeMX / FreeRTOS

生产配置文件：`firmware/PICO_CAN/PICO_CAN.ioc`。

- HSI16 → PLLM=4、PLLN=80、PLLR=2 → SYSCLK/HCLK **160 MHz**。
- Range1 **BOOST**，FLASH latency **4**。
- APB1 /2 = **80 MHz**，APB2 /1 = **160 MHz**；FDCAN kernel 选择 PCLK1=80 MHz。
- CAN1：prescaler=10；CAN2/3：prescaler=5；均 SJW=2、BS1=13、BS2=2，16 TQ/bit，采样点 87.5%。
- 三路普通模式、自动重传；电机扩展过滤到主机 `0xFD`，再由软件核对总线/电机 ID/类型。CAN1 标准过滤 0x100–0x105、扩展过滤电源 ID 0xAA。
- CMSIS-RTOS V2 + FreeRTOS **10.3.1**、GCC ARM_CM4F port，heap_4、堆 **16384 B**，静态/动态分配均开启。
- SysTick：RTOS，**1 kHz**；TIM6：独立 HAL 1 ms 时基。不要再给其他功能占用 TIM6 或重复定义这些中断。
- NVIC：CAN1/2/3 IT0 **5**，TIM6 **5**，SysTick/PendSV **15**，分组 4；最大 RTOS syscall 中断优先级 5。
- `RobotComm`：CMSIS High(40)，栈 **4096 B**（CubeMX 中 1024 words）；`Telemetry`：Normal(24)，栈 **2048 B**（512 words）。
- 栈溢出检查模式 2、malloc 失败 hook；错误进入 `Error_Handler`，并不保证此时软件还能发送停机帧。

**兼容性设计**：只有 `PICO_APP=Robot14` 使用上述 160 MHz / RTOS / 新 CAN 时基。旧测试应用继续保留原 16 MHz 时钟，避免其硬编码波特率校验及既有实测条件失效；因此不能把旧单机测试 ELF 当成新整机 ELF。

### CubeMX 核验与再生成注意

已用本机 CubeMX **6.18.1** 在临时 `.ioc` 上执行加载/保存核验，读回后关键参数保持一致。**这是配置读写验证，不是完整“重新生成源码后仍通过编译”的验证。** 本机缺少完整 G4 firmware package；当前仓库自带最小 HAL，不依赖下载也能构建 Robot14。

TIM6 采用 `Core/Src/stm32g4xx_hal_timebase_tim.c` 的小型 CMSIS 寄存器实现，避免额外引入缺失的 HAL_TIM 驱动。不要将 CubeMX 新生成的 HAL_TIM 版 timebase/IRQ 与当前实现同时编译。

当前 Core 文件保留了生产/旧镜像的条件分支，部分不在 CubeMX USER CODE 区。**不要直接对正在使用的工程目录点击 Generate Code 并无审查覆盖**。再生成请使用单独临时目录（并先保存当前修改），比较 `main.c`、`fdcan.c`、`stm32g4xx_it.c`、`freertos.c`、`FreeRTOSConfig.h`、HAL timebase 与 CMake 源列表，保留上述镜像分支，随后完整回归。`KeepUserCode=true` 并不能保住所有这些集成改动。

## 6. 使能、命令及停机接口

包含 `Application/robot_app.h`。以下 API 供正常 RTOS **任务上下文**使用；不从 ISR 调用，不从调试器绕过 API 写内部状态。

- `Robot_GetSnapshot(&s)`：复制一致性快照，启动完成前返回 false。快照约 20 ms 发布一次。
- `Robot_RequestEnable(id)`：向 owner 投递请求；返回 true **仅代表入队成功**。需要该电机新鲜位置/速度（≤500 ms）且 |速度|≤0.1 rad/s，再执行停机确认 → 写/读回 MIT 模式 0 → 写/读回通信看门狗 → 近零力矩命令 → 使能 → 等待运行态反馈。任一超时/不匹配联动停机。
- `Robot_SetCommand(id,&command)`：只在该电机 ACTIVE 后投递有效目标；所有活动电机都须持续刷新。输入校验失败/队列满返回 false；状态不允许会在 owner 中拒绝，查看 `command_rejected` 和节点 phase。
- `Robot_RequestStop()`：高优先处理的全局锁存停机请求，不经普通命令队列排队。**本轮运行不提供软件解除锁存**，排除问题并按安全步骤复位后重新准备。

`RsCommand` 字段：`position, velocity, torque, kp, kd`。示意（并非自动运行的示例程序）：

```c
/* 仅在人工允许、机构支撑、已完成使能且快照为 MOTOR_ACTIVE 时执行；
   若用于保持/加载，需要明确的关节零点、限位和上层控制设计。 */
RsCommand c = {.position=0, .velocity=0, .torque=0, .kp=0, .kd=0};
bool queued = Robot_SetCommand(1, &c);
/* 每 10–20 ms 刷新每个 ACTIVE 节点；queued 不代表已执行。 */
```

- **总线按“是否真正接入”判定**：CAN2/3 只有在成功发出过一帧（收到 ACK）或收到过帧之后才算已接入。从未接入的空载总线（例如只接 CAN2、CAN3 空着）会继续低频探测，其发送超时只累计到统计里，**不会触发全局锁存停机**，另一条总线可独立轮询；空载总线上后续接入电机时，收到 ACK 后会自动转为正常轮询，无需复位。
- 已接入的总线一旦出现 bus-off、接入之后新增的发送过期、RX 环/FIFO 丢帧，仍触发全局锁存停机；活动电机命令年龄 >100 ms 或类型 2 反馈年龄 >100 ms、任一电机故障、握手超过 300 ms 同样触发。接入前已发生的历史超时不会追溯触发。
- 该判定只放宽“从未有节点应答”的空载总线；能进入 ACTIVE 的电机必须先有新鲜反馈，因此不会出现“已使能电机在没有总线的通道上失控”的情况。真正的总线故障仍需按原有流程处理。
- 故障时先撤销两个电机总线的旧硬件 TX 请求，再轮转发停机；每台约 50 ms 重试，收到发送停机之后的复位态反馈才清该台 `stop_pending` 位。
- 电机 `0x7028 canTimeout` 写入 **4000（200 ms）**并读回确认后才能使能，作为断线/MCU 失控的第二道防护；具体固件的超时动作必须上板确认。
- **总线断路时停机帧也可能发不到**；总线停机、MCU 复位/卡死、看门狗设定与电源切断均须在支撑/低功率条件下验证。软件停机不能代替硬件急停。
- 默认只读启动不会主动停掉在本控制器启动前就已运行的外部电机。接线/烧录前应先解除负载并安全断电，不能依赖软件启动状态保证实物失能。

## 7. Ubuntu 22.04 / VSCode 构建与检查

工程根目录为 `/home/zjy/Systems and Control/PICO/pico-firmware`，路径含空格，终端中务必整体加引号。

```bash
cd "/home/zjy/Systems and Control/PICO/pico-firmware"
bash firmware/PICO_CAN/scripts/build.sh Robot14
bash firmware/PICO_CAN/scripts/test-host.sh
```

也可进入 `firmware/PICO_CAN` 执行 `cmake --preset Linux-Robot14` 与 `cmake --build --preset Linux-Robot14 --parallel 4`。

产物在 `firmware/PICO_CAN/build/Linux-Robot14/PICO_CAN.{elf,hex,bin}`。不需要 Windows 的 STM32 安装路径；FreeRTOS 已入仓，本地 `cmake + Ninja + arm-none-eabi-*` 即可构建。旧构建目录 `build/Robot14` 也可能存在；调试务必确认 ELF 是本次构建。

### 诊断构建：CAN1 / CAN2 物理对调

只用于隔离收发器/接线故障，**不是生产配置**。逻辑拓扑不变（CAN1 设备、CAN2/3 电机），但物理上设备走 FDCAN2（PB12/PB13，500 kbps），电机走 FDCAN1（PA11/PA12，1 Mbps），位时序、过滤器与中断实例一起交换；主机遥测中的 CAN1/CAN2 仍是逻辑编号。

```bash
cmake -S firmware/PICO_CAN -B firmware/PICO_CAN/build/Linux-Robot14-Swap -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="firmware/PICO_CAN/cmake/gcc-arm-none-eabi.cmake" \
  -DCMAKE_BUILD_TYPE=Debug -DPICO_APP=Robot14 -DPICO_ROBOT_SWAP_CAN12=ON
cmake --build firmware/PICO_CAN/build/Linux-Robot14-Swap --parallel 4
```

烧录前必须把两路 CANH/CANL 物理对调：电机线束接 CAN1 收发器（PA12/PA11），BMS/电源板接 CAN2 收发器（PB13/PB12），并保持共地与终端电阻。测完重新烧回 `build/Linux-Robot14/PICO_CAN.elf`，恢复标准接线。2026-11-21 的实测结果见 `docs/validation/2026-11-21-can12-swap.md`。

VSCode：打开**工程根目录**，终端 → 运行任务 → **Robot14: Build (Ubuntu)**；其前置任务会配置。另有 **Robot14: Host regression (no hardware)**。另有 **Robot14: Visual tuning (read-only connect)**；未添加自动烧录任务。

原工作台的程序列表新增 **14电机整机 · CAN2/3 + CAN1双设备**，支持专用 **14电机整机可视化调参**。原单/双机示波器新增进入专用窗口的入口；必须结束旧连接，不能向本镜像发送旧调参命令。详见 `docs/Robot14_Tuning.md`。

当前观测入口：

- LPUART1 / PA2 TX、PA3 RX，115200，改为 Robot14 专用二进制会话；连接默认只读，只有显式使能后才允许目标续约。不得用旧ASCII采集器解析本镜像。
- SWD 调试中看 `robot_app.c` 的 `snapshot`：`network.motors[0..13]`（下标=id−1）、各节点 phase/反馈/fault_word、`can[0..2]`、`devices.bms/power`、拒绝与任务超期计数。
- 断点会冻结通信并触发电机超时，**有负载运转时不要随意打断点**；先停机或采用非阻塞采集。

## 8. 上板验收顺序与 2026-11-21 进度

| 步骤 | 状态 |
| --- | --- |
| 1. 机械支撑、逐台核对型号/总线/ID、终端电阻 | 部分完成：ID1–7 已核对，CAN2 实物可用；CAN3/8–14 未接入 |
| 2. 烧录并确认 160 MHz / 80 MHz / 1 ms / 无超期 | 已完成：INFO 返回 160 MHz，任务无超期 |
| 3. CAN1 双设备 500K | 电源板已通过（约 53.3 V）；**BMS 仍无应答** |
| 4. CAN2 逐台到 7 台、1M 位时序与回包 | **已完成**：ID1–7 全部返回位置/速度；CAN3 空载不再触发锁存 |
| 5. 单台零力矩/位置/速度/力矩与 0x7005、0x7028 读回 | **已完成**：7 台逐台通过，ACTIVE→IDLE 正常，无故障位 |
| 6. 停止、拔线、未 ACK、bus-off、复位失能时间 | 部分完成：锁存/复位流程已实测；拔线失能时间与联动仍需专项记录 |
| 7. 14 台联合、关节零点/方向/限位、电源联锁 | 未开始；CAN2 七台整组“零力矩 + 三种模式”已通过，CAN3 未接入 |

仍未完成：CAN3/ID8–14 接入、BMS 应答、额定力矩/温升/机械行程验收、关节级零点/方向/限位、电源安全联锁。**软件/小幅度实测通过不等于整机验收通过。**

软件验证记录见 `docs/validation/2026-11-16-robot14.md`。**编译/仿真通过不等于 14 台实物已经联调通过。**

后续上位机集成验证见 `docs/validation/2026-11-16-robot14-tuning.md`（新的固件已替换旧ASCII汇总）。
