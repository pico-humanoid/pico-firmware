# PICO：G474 CAN 验证工程

目标板：NUCLEO-G474RE。工程和依赖已经放在本机，编译、烧录及下面的内部回环验证均不需要联网。

## 第一次接板

1. 用带数据功能的 USB 线，把开发板的板载 ST-LINK USB 接口连接电脑。
2. 双击 `03_Flash_Loopback.cmd`。看到编程和校验成功后关闭窗口。
3. 双击 `04_Capture_Log.cmd`。窗口提示串口已打开后，按开发板 RESET 键。
4. 等待约 15 秒，查看 `# RESULT=PASS`。成功时板上的绿色用户 LED 常亮，失败时快速闪烁。
5. 原始日志保存在工程的 `logs` 文件夹。

内部回环只需要开发板和 USB 线，不需要 CAN 收发器、USB-CAN 或电机电源。这个步骤验证控制器、过滤、接收中断、队列和测试记录，外部电气链路另按下一节验证。

## 打开、修改和编译

- 双击 `01_Open_Project.cmd`，或者桌面的“PICO 开发环境”快捷方式。
- 双击 `02_Build_All.cmd`，可离线重新编译两种配置。
- `Loopback` 是默认配置，使用控制器内部回环。
- `External` 使用正常 CAN 模式，按下节的独立测试总线接线。
- 在 VS Code 的“运行和调试”中选择内部回环配置，按 F5 可下载并调试。观察 `g_can_test`，其中 `result=1` 表示通过，`result=2` 表示失败，`fatal` 保存初始化等错误。
- `PICO_CAN.ioc` 可用本机 CubeMX 6.18.1 打开。自定义逻辑在 `App`，入口放在 CubeMX 的 USER CODE 区域。

## 外部双向收发

这是 PPT 第 14 页的独立测试总线，测试时只连接 G474、收发器和 USB-CAN。

| G474 | SN65HVD230 模块 |
|---|---|
| PA12，FDCAN1_TX | TXD / D |
| PA11，FDCAN1_RX | RXD / R |
| 3.3 V | VCC，按模块实际规格确认 |
| GND | GND |

收发器的 CAN_H、CAN_L 分别接 USB-CAN 的 H、L，按接口要求连接参考地。清点内置端接，使总线主干两端各有一个 120 Ω。收发器应处于正常工作状态。

1. 双击 `05_Flash_External.cmd`。
2. USB-CAN 设置为 **1 Mbit/s、经典 CAN、正常工作模式**。
3. 打开日志采集窗口，按开发板 RESET。
4. 在 USB-CAN 工具里向板端发送 **标准数据帧 `0x321`，DLC=8**。共 100 帧，间隔 100 ms，数据为 `序号 88 77 66 55 44 33 22`，序号从十六进制 `00` 递增到 `63`。
5. 板端收到第一条有效测试帧后，开始反向发送 `0x123`，数据为 `序号 22 33 44 55 66 77 88`，同样 100 帧、间隔 100 ms。
6. 保存两端日志。板端应报告 PASS，USB-CAN 端也应确认收到完整的 100 条 `0x123`，无缺失、重复或数据错误。

USB-CAN 的驱动和上位机程序由具体型号决定，本准备包提供的是 G474/ST-LINK 环境。当前尚未识别到 USB-CAN 设备，因此没有安装不确定型号的适配器驱动。

## 日志与验收

CSV 每行包含板端毫秒时间、事件、帧格式、ID、长度及原始数据。`TX_SUBMIT` 表示 HAL 接受发送，`TX_DONE` 表示控制器产生发送完成事件，`RX` 表示取帧后通过测试数据检查。

内部回环要求每类事件各有 100 条，每个序号 0..99 恰好一次。FIFO 丢失事件、软件队列丢帧、无效帧、发送失败及总线关闭分别计数。FIFO 硬件丢失标志可能合并多次丢失，因此字段名称明确为“事件数”。

还可以运行 `python scripts/check_log.py logs/实际日志.csv` 独立检查内部回环日志；检查外部日志时加 `--external`。检查工具只使用 Python 标准库，无需安装包。

计时采用板端启动后的毫秒值。当前使用 HSI16，FDCAN=PCLK1=16 MHz，预分频 1，时间段 13/2，SJW 2，名义速率 1 Mbit/s，采样点 87.5%。内部回环通过后，外部时钟误差和实物电气条件仍以外部收发结果为准。

## 本机软件与离线文件

- STM32CubeMX：`D:\STM32Tools\STM32CubeMX-6.18.1\MX`。
- Cube 工具入口：`D:\STM32Tools\bin\cube.exe`。
- 编译、调试及烧录工具：当前用户的 `AppData\Local\stm32cube\bundles`。
- G4 固件库：`D:\STM32Cube\Respsitory\STM32Cube_FW_G4_V1.6.3`。
- 工程已经复制所需 HAL/CMSIS 文件，不依赖联网获取源码。
- 工具和固件离线安装包：`D:\STM32Tools\offline`。这些文件保留用于恢复环境。
- 原 VS Code 设置及用户 PATH 备份：`D:\STM32Tools\offline\config-backups`。

安装验证记录见 `PREPARATION_STATUS.md`。其中的软件检查与真实硬件验证分别记录，尚未上板的结果不会标成通过。

官方参考：[STM32CubeIDE for VS Code](https://dev.st.com/stm32cube-docs/stm32cubeide-vscode/latest/en/index.html)、[STM32CubeG4](https://github.com/STMicroelectronics/STM32CubeG4)、[ST 的 FDCAN 回环说明](https://www.st.com/content/st_com/en/technical-documents/an5348-introduction-to-fdcan-peripherals-for-stm32-mcus-stmicroelectronics_asset/chunk-002-topic-an5348-implementation-can-fd.html)。
