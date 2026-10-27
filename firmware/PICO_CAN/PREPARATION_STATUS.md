# 开发环境准备记录

检查日期：2026-10-23。目标板：NUCLEO-G474RE。

## 已完成

| 项目 | 检查结果 |
|---|---|
| VS Code STM32 官方扩展包 3.11.0 及相关组件 | 已安装；STM32Cube Core、工程管理、构建及调试组件已激活 |
| STM32CubeMX 6.18.1 | 已安装，已实际生成本工程 |
| STM32CubeG4 1.6.3 | 已完整安装；工程所需 HAL/CMSIS 源码已复制到本地 |
| GCC 14.3.1、GDB、CMake、Ninja | 已安装并运行；两种固件编译成功 |
| STM32CubeProgrammer 2.23.0、ST-LINK GDB Server | 已安装并运行 |
| ST-LINK USB 调试、虚拟串口及桥接驱动 | 官方驱动检查通过 |
| G474 器件包、NUCLEO-G474RE 板卡包及 SVD | 已安装 |
| 工程依赖检查 | `cube --json bundle install --no --project` 返回 `NothingToInstall` |
| 内部回环固件 | ELF、BIN、HEX 已生成；BIN 23,160 字节 |
| 外部双向收发固件 | ELF、BIN、HEX 已生成；BIN 23,128 字节 |
| 日志检查器 | 7 项合成日志检查通过：正常内/外部日志通过，缺帧、重复、错数据、缺总结及错误计数均被拒绝 |
| 无板卡分支 | 烧录脚本检测不到 ST-LINK 时退出，不尝试写入 |
| 离线恢复文件 | 保存于 `D:\STM32Tools\offline`，附校验记录及原配置备份 |

工程位于 `D:\STM32Projects\PICO_CAN`。选择纯英文路径以便嵌入式工具稳定运行；原 PICO 文件夹和桌面均留有入口。工作区信任仅增加了这个新建工程目录。

## 接板后直接执行

1. 连接开发板的板载 ST-LINK USB 接口。
2. 运行 `03_Flash_Loopback.cmd`，确认烧录及校验成功。
3. 运行 `04_Capture_Log.cmd`，串口打开后按板上 RESET。
4. 等待约 15 秒，检查 `# RESULT=PASS` 和绿色用户 LED 常亮。原始日志自动保存到 `logs`。

内部回环所需的软件、驱动、源码和固件均已在本机，不需要继续下载。完整说明见 [README.md](README.md)。固件校验值和软件检查结果见 [preparation_checks.json](preparation_checks.json)。

## 实物验证状态

尚未连接并运行开发板，因此烧录、串口输出、内部回环以及外部 CAN 电气链路的实物结果均为**待验证**。上述编译结果和合成日志测试不代表硬件通过。

外部双向收发固件已准备，但 USB-CAN 的专用驱动和上位机程序取决于实际适配器型号；当前没有识别到该设备，未安装未知型号的软件。PPT 后续的电机只读和多节点实验还需按实际设备协议配置。
