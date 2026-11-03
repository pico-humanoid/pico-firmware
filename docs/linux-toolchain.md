# Linux 开发工具链

配置与验证日期：2026-10-31。当前主机：Ubuntu 22.04.5 LTS，x86_64。

最初的工具链安装阶段只适配开发环境与构建入口，没有修改固件业务源码、历史日志和归档烧录文件。随后新增了 BMS / 电源板只读软件，见本文末尾更新与[读取验收说明](device-read-validation.md)。仍未连接硬件，不代表已完成 Linux 板级验收。

## 1. 已有与新增工具

| 工具 | 本机版本 | 本次处理 |
| --- | --- | --- |
| ARM GNU GCC / binutils / newlib | GCC 10.3.1 | 保留现有系统安装，已实际编译两种固件 |
| CMake | 3.22.1 | 保留现有系统安装 |
| Ninja | 1.10.1 | 保留现有系统安装 |
| 原生 GCC / G++ / Make | GCC / G++ 11.4.0 | 保留；可用于后续主机侧测试 |
| GDB Multiarch | 12.1 | 保留，验证 ARM 架构及固件 ELF 符号读取 |
| Python | 3.10.12 | 保留 |
| pyserial | 3.5 | 已有，导入与串口枚举通过 |
| pytest | 6.2.5 | 已有，导入通过；不表示已新增业务单元测试 |
| OpenOCD | 0.11.0 | 新增，验证启动及 STM32G4 配置离线解析 |
| ST-LINK tools | 1.7.0 | 新增 `st-info`、`st-flash`、`st-util`、`st-trace` |
| can-utils | 2020.11.0 | 新增 `candump`、`cansend` 等工具 |
| clangd / clang-format | 14.0.0 | 新增，验证启动；clangd 对固件源文件进行解析 |
| STM32CubeMX | 已有安装，未核验版本 | `/home/zjy/STM32CubeMX/STM32CubeMX`；本次未启动 GUI、未重新生成代码 |

### 用户目录安装说明

由于系统级安装需要 sudo 密码，本次新增工具使用用户目录安装，而不是 `sudo apt install`：

- 从本机配置的 Ubuntu 软件源用 `apt-get download` 下载 `.deb`，使用 `dpkg-deb -x` 提取。
- 安装前缀：`/home/zjy/.local/opt/pico-linux-tools`。
- 命令入口：`/home/zjy/.local/bin`，已经位于当前 PATH；现有 shell 配置也包含该路径，未修改 shell 启动文件。
- 每个入口只为自身进程设置所需动态库路径；OpenOCD 入口另外指定其脚本目录。没有全局设置 `LD_LIBRARY_PATH`。
- 软件包版本与下载文件 SHA-256 收据：`/home/zjy/.local/opt/pico-linux-tools/install-manifest.json`。
- 提取包内的许可证和文档随安装目录保留。
- **这些用户目录包没有登记到系统 dpkg 数据库，也不会由系统 apt upgrade 自动维护。** 后续需主动更新，或者迁移至系统包安装；迁移时也应处理用户命令入口的 PATH 优先级。
- 本次没有执行包安装后脚本，没有向系统安装这些包附带的 udev、modprobe 或服务配置。

现有编译器版本与原始 Windows 工程的 GCC 14.3.1 不同。当前 Linux 构建通过，但不能据此认定新旧镜像字节相同或已通过同样的板级测试。

## 2. 环境检查

从仓库根目录执行：

```bash
./firmware/PICO_CAN/scripts/check-env.sh
```

检查内容：必要命令存在、Python 模块可导入、GDB 能选择 ARM 架构，以及 OpenOCD 能解析 ST-LINK / STM32G4 配置。

OpenOCD 使用 `noinit` 和 `shutdown`，不会初始化调试器、烧录或复位硬件。命令存在也不替代真实设备测试。

## 3. Linux 构建入口

从仓库根目录执行：

```bash
# 内部回环
./firmware/PICO_CAN/scripts/build.sh Loopback

# 外部 CAN
./firmware/PICO_CAN/scripts/build.sh External

# 全部六种普通模式（原两种 + 三种单设备读取 + 双设备读取）
./firmware/PICO_CAN/scripts/build.sh All

# 可选：调整并行数，默认 4
PICO_BUILD_JOBS=2 ./firmware/PICO_CAN/scripts/build.sh All
```

也可以直接使用 CMake 预设：

```bash
cd firmware/PICO_CAN
cmake --preset Linux-Loopback
cmake --build --preset Linux-Loopback --parallel 4
cmake --preset Linux-External
cmake --build --preset Linux-External --parallel 4
```

预设独立于原有 Windows PATH 设置，从 Linux PATH 查找工具。输出目录：

```text
firmware/PICO_CAN/build/Linux-Loopback/
firmware/PICO_CAN/build/Linux-External/
```

每个目录包含 `PICO_CAN.elf`、`PICO_CAN.hex`、`PICO_CAN.bin` 和 `compile_commands.json` 等。它们不会覆盖原始 `build/Loopback`、`build/External` 中已归档的镜像。现有 `.gitignore` 会忽略新增构建目录。

原有 Windows `.ps1` / `.cmd`、编辑器任务和调试配置保留，**并没有因此自动变成 Linux 兼容配置**；目前 Linux 使用上述命令行入口。

## 4. 代码索引与离线调试检查

构建完成后，从仓库根目录可以执行：

```bash
clangd \
  --check="$PWD/firmware/PICO_CAN/Core/Src/main.c" \
  --compile-commands-dir="$PWD/firmware/PICO_CAN/build/Linux-Loopback" \
  '--query-driver=/usr/bin/arm-none-eabi-*'

gdb-multiarch -nx -q -batch \
  firmware/PICO_CAN/build/Linux-Loopback/PICO_CAN.elf \
  -ex 'info address main'

python3 -m serial.tools.list_ports
```

`--query-driver` 允许 clangd 查询指定路径的本机交叉编译器；若编译器换了安装位置，需调整这一选项。没有硬件时串口枚举输出 `no ports found` 不视为环境安装失败。

clang-format 已能使用，但本次没有批量格式化导入的源码。

## 5. 待硬件到位后验证的内容

### USB 与串口权限

本机已经存在 ST-LINK udev 规则，但本次未能验证实际设备访问权限，也没有修改用户组。

如接板后出现权限错误，由用户在自己的管理员终端确认并执行所需配置，例如：

```bash
# 先检查当前用户组和设备权限，再决定是否需要添加。
id
sudo usermod -aG dialout,plugdev "$USER"
sudo udevadm control --reload-rules
```

修改用户组后重新登录，设备重新插拔。没有必要为了无硬件编译而提前开放全部 USB 权限，更不要对设备节点统一使用 `chmod 777`。

### 烧录与在线调试

本次准备的是 **OpenOCD + ST-LINK + GDB Multiarch** 命令行路线。OpenOCD 已通过目标配置解析，实际芯片探测、Flash 写入、校验、复位和断点调试仍待硬件验证。

**STM32CubeProgrammer CLI / STM32CubeIDE / ST 专用 GDB Server 本次未新增安装。** 它们不是当前命令行编译的前提；原来的 Windows `flash.ps1` 仍依赖 Windows 版 CubeProgrammer，不能直接在 Linux 使用。

### CAN 与串口

- can-utils 面向 SocketCAN 接口。装好工具不代表 Waveshare USB-CAN-A 已有对应 Linux 驱动或会自动成为 `can0`；实际适配要按设备工作模式另行确认。
- 本次没有创建虚拟 CAN 接口，没有修改内核模块或网络设备；相关操作可能需要管理员权限。
- 工具安装时 pyserial 已准备好，原有 Windows `capture.ps1` 保留；随后新增了独立的 `capture_device.py`，见第 7 节。
- 没有修改 `check_log.py` 的历史日志兼容问题，也没有调整外部测试判据；这些属于后续测试工具工作，不是安装工具链。

## 6. 工具链安装阶段的无硬件验证记录

- 环境检查：通过。
- 两种 Linux 预设：配置、编译、链接以及 ELF / HEX / BIN 生成全部成功。
- GDB：读取 ELF 中的 `main` 符号成功。
- OpenOCD：ST-LINK / STM32G4 配置离线解析成功。
- clangd：`main.c` 解析零错误；`can_bringup.c` 在两种模式的编译配置下解析均为零错误。
- pyserial：导入、枚举正常；伪终端（PTY）双向读写测试通过，没有物理串口设备。
- 固件业务代码、原始镜像和历史日志未修改。

结论：已具备本机命令行开发和无硬件编译所需工具；不代表完成硬件联调、机器人业务开发或全部编辑器集成。

## 7. 后续软件更新：设备只读模式（2026-10-31）

工具安装之后已新增协议、收发层、轮询器和单设备读取应用，历史“业务代码未修改”结论仅指上一阶段。

```bash
cd /home/zjy/PICO/pico-firmware
./firmware/PICO_CAN/scripts/test-host.sh
./firmware/PICO_CAN/scripts/build.sh Devices
```

新增 `Linux-BMS-Read-500K`、`Linux-Power-Read-1M`、`Linux-Power-Read-500K` 预设；该阶段`build.sh All`构建五种模式；2026-11-03加入Dual后为六种。
五种固件交叉编译成功，新增五项主机测试通过。`scripts/capture_device.py` 已支持新固件的 ST-LINK 串口原始日志采集，不是 USB-CAN-A 适配器程序。

完整构建、烧录、参数覆盖、协议不确定项和实物验收步骤见 [BMS / 电源板读取与验收](device-read-validation.md)。尚无真实设备通信或位速率修改结果。


## 8. 双设备500K预设（2026-11-03）

新增`Linux-Dual-Read-500K`，可通过`bash /home/zjy/PICO/pico-firmware/firmware/PICO_CAN/scripts/build.sh Dual-Read-500K`构建。两个500K设备共用FDCAN1，应用层独立状态、共享轮询；不是双CAN通道。产物位于`/home/zjy/PICO/pico-firmware/firmware/PICO_CAN/build/Linux-Dual-Read-500K/`。`Devices`和`All`均包含该镜像。当前主机测试13/13通过，硬件待验收，详见`/home/zjy/PICO/pico-firmware/docs/device-read-validation.md`第9节。
