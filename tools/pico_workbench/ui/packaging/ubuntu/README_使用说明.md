> 本文保留上游 Ubuntu 24.04 发布说明。Ubuntu 22.04 源码适配及验证边界见仓库 `docs/Ubuntu_22.04.md`；本轮未构建或重新发布经过完整验证的 Ubuntu 22.04 便携包。

# Ubuntu 24.04最新版适配（2026-11-15）

适用：Ubuntu 24.04桌面版、Intel/AMD x86_64。不是Windows ZIP、不是ARM64包，也不保证Ubuntu22.04的glibc兼容。

包含最新原生开发控制台、日志查看器、位置/速度滑块、双机独立目标与波形、可设置时长、按型号限流、疑似受阻报警及联动停机。默认限流RS10P 5.3A、RS00 4.7A；散热、负载与高电流仍待单独实物验收。

## 使用

1. 在Ubuntu中解压tar.gz至可写目录，保留文件权限和符号链接。可用`tar -xzf 文件名.tar.gz`，不要先在Windows解压后逐个复制。
2. 运行`bash 打开开发控制台.sh`或`bash 打开日志查看器.sh`。包内自带Python/Tk运行环境，无需安装Python依赖。
3. 运行`bash 检查环境.sh`。包内包括固定Arm GNU14.3.rel1、CMake、Ninja、OpenOCD、依赖库和中文字体；不需要下载这些编译/烧录组件。
4. 首次访问USB可能需要执行`bash 安装USB权限.sh`并输入管理员密码，完成后拔插ST-LINK/USB-CAN；必要时注销重新登录。
5. 工具页“一键打包”会导出Linux tar.gz，含当前源码、运行环境及离线编译/烧录工具；历史日志不包含，另存SHA256校验值。
6. 单机或双机选择对应实验，编译后再烧录。Linux无STM32CubeProgrammer时使用OpenOCD，按可识别的ST-LINK虚拟串口序列号选择唯一开发板；连接实验时只复位，不自动使能。

VS Code和CubeMX使用本机已安装的Linux版，不把Windows EXE转换成Linux程序。厂商调试软件入口也需要设置可在Linux运行的对应程序，Windows EXE会被明确拒绝。包内编译、烧录和控制台实验不依赖这两个编辑器。

## 验证与边界

发布包在真实Ubuntu24.04 GitHub Actions中构建。测试包括源码回归、冻结程序原生界面自检、包含空格与中文路径的迁移、随包工具版本检测，以及通过冻结CLI真正编译RS10P/RS00/双机三份ARM固件。验证报告放在包内`UBUNTU_VALIDATION.json`，外部下载带SHA256校验值。

没有在云端连接ST-LINK或电机，所以OpenOCD实际写入、Linux串口实物通信、实际停机反馈和USB权限在用户机器上仍需验证；不会把软件自检视为实物通过。历史Windows包保持原样，本次新增Ubuntu包单独发布。

OpenOCD命令依据官方文档：[烧录及verify/reset](https://openocd.org/doc/html/Flash-Programming.html)、[调试器序列号选择](https://openocd.org/doc/html/Debug-Adapter-Configuration.html)。Arm GNU下载校验值来自Arm官方固定版本SHA256文件。OpenOCD对应Ubuntu源码与补丁、各工具许可证随包保留。
