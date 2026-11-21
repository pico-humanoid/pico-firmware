> Ubuntu 22.04 从源码运行请先看 [本地适配指南](Ubuntu_22.04.md)。本文中的 Ubuntu 24.04 发行包记录不是本次已验证的 22.04 二进制包。

# 当前桌面发行包：Windows 11月14日 / Ubuntu 11月15日

本次Windows包：[PICO-Windows-x64-20261114_215203.zip](https://github.com/pico-humanoid/pico-firmware/releases/download/desktop-v2026.11.14/PICO-Windows-x64-20261114_215203.zip)。请完整解压后启动，不在ZIP内运行；首次USB驱动可能需要管理员权限。

Windows包包含Windows运行环境和离线开发工具，不能在Ubuntu上运行。最新版Ubuntu包使用原生Linux程序，包含相同的最新位置/速度交互、双机联调、波形、限流和报警功能，以及离线Arm GCC、CMake、Ninja和OpenOCD工具。

**Ubuntu 24.04 x86_64：[发布下载](https://github.com/pico-humanoid/pico-firmware/releases/tag/desktop-v2026.11.15) · [详细使用说明](Ubuntu_20261115.md)。** 解压后运行`bash 打开开发控制台.sh`；首次连接USB执行`bash 安装USB权限.sh`。VS Code/CubeMX使用本机Linux版。第三方工具按原许可证使用，其附带不表示项目替代了厂商授权。

Ubuntu包通过120项源码测试、冻结程序原生界面自检、中文及空格目录迁移、三份最新ARM固件实际编译与原生一键再打包检查。未在CI连接实物开发板或电机，USB权限和实际烧录/收发仍需在目标电脑验证。

[当前交互实验说明](Motor_Tuning.md) · [程序索引](program-index.md) · [11月10日历史状态](weekly/2026-11-10.md) · [11月14日实测及异常](validation/2026-11-14-motor.md)

---

以下为11月5日历史便携版本说明，不能视为11月14日新Ubuntu包发布记录。

# PICO 桌面开发控制台与日志查看器

版本：2026.11.05。两个程序均附带 Python/Tk 运行环境，不需要另装 Python，也不使用网页服务。请完整解压，保留程序旁的 `_internal`、`project` 等目录；不能只拿走一个 EXE 或 ELF。

## 下载哪个包

| 包 | 用途 |
| --- | --- |
| Windows-x64.zip | Windows 10/11 64 位；包含双程序、运行环境和源码工作区 |
| Ubuntu-24.04-x86_64.tar.gz | Ubuntu 24.04 桌面版、Intel/AMD 64 位；包含双程序、运行环境、源码和 USB 规则 |
| 本地 FullOffline 完整包 | 在上述基础上附带已准备的对应系统开发工具，供原用户迁移；不作为第三方软件的公开下载镜像 |

GitHub 公开包中的日志查看器可直接使用。开发控制台界面和记录管理也可直接使用；打开编辑器、硬件配置、编译、烧录分别需要对应外部工具。FullOffline 包已附带这些工具；公开包可以复用机器上已有的安装。

## Windows

1. 解压到可写目录，例如 `D:\PICO-Workbench`，不要直接在 ZIP 内运行。
2. 双击 `PICOConsole.exe` 或“打开开发控制台.cmd”。
3. 双击 `PICOLogViewer.exe` 或“打开日志查看器.cmd”。
4. “检查环境.cmd”列出找到的工具与路径。FullOffline 包先运行“首次准备.ps1”的配套入口。
5. 接板后选择实际出现的串口；COM 号不会固定为原电脑的 COM5/COM6。

## Ubuntu

1. 将 tar.gz 复制到 Ubuntu，在“文件”中解压到主目录等 Linux 文件系统，例如 `~/PICO-Workbench`。保留符号链接和执行权限，推荐 ext4；不要用 Windows 解压后再逐个拷贝文件。
2. 终端进入解压目录，运行：

   ```bash
   bash 打开开发控制台.sh
   bash 打开日志查看器.sh
   ```

   两个窗口可分别打开。若文件管理器允许执行脚本，也可双击并选择“运行”。
3. 可运行 `bash 安装桌面入口.sh`，之后在 Ubuntu 应用程序菜单搜索“PICO”。移动目录后重新运行一次即可更新路径。
4. 首次需要连接开发板或 USB-CAN 时，运行 `bash 安装USB权限.sh`，在 Ubuntu 系统窗口输入管理员密码，然后拔插设备。查看历史日志不需要这个步骤。
5. FullOffline 包先运行 `bash 首次准备.sh`。全程使用包内文件，不下载 Python、插件或开发工具。

适用的是 Ubuntu 24.04 x86_64 桌面环境；ARM64、Server 无桌面和其他发行版不在本包验证范围。程序不需要以 root 身份运行；只有安装 USB 规则需要管理员权限。

## 编程、编译与烧录

在控制台选择实验后，“打开 VS Code”会生成匹配的工作区并打开相应源码；Ctrl+Shift+B 调用同目录的 PICOCLI，使用同一个实验配置。编译和烧录使用当前系统的独立构建目录。

内置：内部回环、外部双向收发、BMS-Read-500K、Power-Read-1M、Power-Read-500K、Dual-Read-500K。Dual 共用 FDCAN1 / 500K。设备只读采集结果显示为待验收，不套用旧 100 帧 PASS 判据。

公开包缺少外部工具时可从官方渠道安装：

- [VS Code](https://code.visualstudio.com/download)，STM32 官方扩展包。
- [STM32CubeMX](https://www.st.com/en/development-tools/stm32cubemx.html)，STM32CubeG4 1.6.3。
- [STM32Cube 开发工具](https://www.st.com/en/development-tools/stm32-vscode-extension.html)：GCC、CMake、Ninja、CubeProgrammer、ST-LINK GDB Server。

也可把完整离线工具放到程序目录的 `tools`，或设置 `CUBE_BUNDLE_PATH` 指向 STM32 bundles 目录。外部设备的驱动和访问权限仍须在目标电脑启用。

## 日志与记录

数据保存在当前解压目录的 `project/logs`，自定义配置和备注保存在 `project/ui/state`。移动整个目录会一起带走这些文件；GitHub 下载不会自动同步你本地的实验记录。

日志查看器包含中文事件、设备字段与单位、健康快照、原文、复核报告、关键词和精确 CAN ID 筛选。自动刷新默认保留阅读位置，“跟随最新”用于查看实时尾部。数值来自打开的日志，不是预设的合格值；历史文件不是当前实测值。

## 校验与故障排查

- 下载旁边的 `.sha256` 文件可核对压缩包完整性。
- `PICOCLI check` / `PICOCLI.exe check`：环境路径检查。
- `PICOCLI self-test` / `PICOCLI.exe self-test`：无硬件的窗口、日志解析和工作区检查，不烧录开发板。
- Ubuntu 提示 Permission denied：确认在 Linux 文件系统解压，并执行 `chmod +x PICOConsole PICOLogViewer PICOCLI *.sh`。
- 看不到端口：插入支持数据传输的 USB 线、安装 USB 权限后重新连接；选择实际端口。
- 应用测试与固件编译通过不代表硬件 CAN 验收通过，硬件结果以对应实物日志为准。

程序与构建源码见仓库 `tools/pico_workbench`；发行附件见仓库 Releases。版本中附带的第三方软件保留各自许可与声明，详见 THIRD_PARTY_NOTICES.md。

## 本版软件验证

Windows 原生便携程序与 Ubuntu 24.04 WSL2 隔离环境中的原生 Linux 便携程序均已通过双窗口、日志解析、单位、零计数和工作区自检；两系统各 53 项源码检查通过。尚未在此次打包测试中连接实物开发板，WSL2 测试不替代目标电脑的 USB 和电气链路验证。

## 完整离线工具包的软件检查

Windows 和 Ubuntu 24.04 WSL2 的完整迁移副本均已从包内工具路径编译六种配置：Loopback、External、BMS-Read-500K、Power-Read-1M、Power-Read-500K、Dual-Read-500K。包内 VS Code 扩展和 Cube/Clangd 检查通过；Ubuntu CubeMX 的 JRE 可运行。迁移后仍先重新编译所选实验，再烧录，避免复用其他目录的缓存和调试路径。

GitHub Release 的 Windows / Ubuntu 公开应用包已重新下载并核对 SHA-256，在包含空格的新目录、移除 Python 环境变量后通过自检。公开包不包含第三方编辑器和开发工具安装；完整工具副本供原用户本地迁移。

## Robot14 整机可视化调参（2026-11-16新增）

实验中心新增 **14电机整机可视化调参**，旧调参窗口也有入口。`bash tools/pico_workbench/ui/start.sh --robot14` 可直接打开。需要本次新Robot14固件；连接只读，不自动烧录/复位/使能。支持14节点监视、逐台MIT阻抗参数、普通单节点停机、全部锁存停机与日志CSV。详见 [Robot14调参说明](Robot14_Tuning.md)。目前仅软件/模拟验证，未做真实电机测试。
