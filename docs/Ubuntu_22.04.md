# Ubuntu 22.04 源码使用指南

更新：2026-11-15。本页针对本地合并后的源码，不是对历史 Ubuntu 24.04 二进制包的兼容承诺。

## 本次适配

在 Ubuntu 22.04.5 / Python 3.10.12 上完成源码测试和编译。控制台同时识别仓库目录与导出的独立工作区，不再要求原作者电脑的目录结构。构建兼容系统 CMake 3.22，不使用 `--fresh`；SHA256、归档处理不依赖 Python 3.11 新接口。保留原有 BMS、Power、Dual 的 CAN1/2/3 配置及双设备读取重试策略。

源码控制台含原生 Tk 界面、日志查看器、实验目录、单/双电机位置和速度调试、诊断及记录功能。安全参数及受阻联动逻辑的软件回归通过，不代表已完成实物验收。

## 环境与启动

以下命令由用户按需执行；本轮没有安装系统软件或修改 USB 权限。

```bash
sudo apt update
sudo apt install python3 python3-tk cmake ninja-build gcc-arm-none-eabi libnewlib-arm-none-eabi openocd fonts-noto-cjk

bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/ui/start.sh"
```

需要有桌面会话及有效 DISPLAY。串口库已包含在源码的 `ui/vendor` 中。仅打开日志查看器：

```bash
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/ui/start.sh" --logs
```

检查工具与串口（只读，不烧录、不使能电机）：

```bash
python3 "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/check_environment.py"
```

`ready` 表示编译/烧录工具可定位，不表示硬件验证通过；`firmware.*.exists=false` 表示该实验尚未在控制台的输出目录编译。批量验证使用的临时目录与控制台输出目录不同。

## 编译及选择 CAN 通道

在控制台选择实验后点击编译，或使用共享构建入口：

```bash
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/build.sh" All
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/build.sh" RS10P-Tuning
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/build.sh" BMS-Read-500K-CAN1
```

`All` 仅指历史入口的 Loopback 和 External 两个基础实验，**不是全部电机程序**。其他实验请在控制台逐项选择。BMS/Power/Dual 的旧控制台名称保留 CAN3；带 `-CAN1`、`-CAN2` 的新名称显式选择对应通道。直接配置工程时仍可用 `-DPICO_CAN_CHANNEL=1/2/3`，默认 CAN1；电机程序有自己的通道配置，不能据此随意改线。接线见仓库硬件文档。

工具检测优先复用可用的本机/随包工具，缺省支持 PATH 中的 CMake、Ninja、Arm GCC 和 OpenOCD；若装有 STM32CubeProgrammer，可选择该后端。VS Code、CubeMX 是可选外部程序，不是打开控制台的前置条件。

## USB 权限与烧录：需要用户主动操作

如果当前用户没有设备访问权限，可自行运行以下脚本，授权后拔插设备，必要时注销登录：

```bash
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/ui/packaging/ubuntu/安装USB权限.sh"
```

先确认板卡、固件、供电、接线及安全停止措施，再在控制台烧录。命令行示例（**执行即可能写入开发板**）：

```bash
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/flash.sh" Loopback
# 多板时第二个参数填写实际已连接 ST-LINK 的序列号：
# bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/scripts/linux/flash.sh" Loopback SERIAL
```

没有镜像、未找到唯一开发板或指定序列号不匹配时拒绝烧录。当前选择依赖可识别的 ST-LINK 虚拟串口；只有调试接口而没有虚拟串口的探针需要另行配置，不能保证自动识别。本轮未执行烧录、CAN 实物通信、调速、运动或使能。

厂商 Windows 调试 EXE / Wine 入口仅为可选兼容辅助，需要另备合法软件与 Wine，不是原生控制台的必要组件；本轮未验证它。源码目录不要直接运行“安装桌面入口.sh”，该脚本用于包含冻结可执行程序的导出包。

## 打包与验证边界

现有 Ubuntu 24.04 发布包仍按其原始平台标记，不能当作已验证的 Ubuntu 22.04 包。本轮新增 Ubuntu 22.04 / Python 3.10 CI 构建矩阵，但尚未在远端执行，也没有发布新包。本机未安装 PyInstaller，因此**未完成冻结程序和全离线便携包的端到端验证**。已验证带中文和空格路径的源码工作区导出及实际固件编译。

本地结果及复测命令见 [合并验证记录](validation/2026-11-15-ubuntu22-local-merge.md)。上游历史电机反馈跳变、停止后位置不稳定等异常仍需排查；软件测试通过不能消除这些硬件风险。
