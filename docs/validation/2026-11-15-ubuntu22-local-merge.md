# 2026-11-15：本地 main 合入 zjy 与 Ubuntu 22.04 验证

## 来源与操作范围

- 目标：`/home/zjy/PICO/pico-firmware`，当前分支 `zjy`，开始时 HEAD `42640a3`，工作区干净。
- 来源：用户已经下载的 `/home/zjy/PICO/pico-firmware-main`；该目录不是 Git 仓库。540 个文件逐字节比对，与本地缓存 `origin/main` 的 `0fd9f2a` 一致。
- 三方参考共同基线：`274937b84231a478f0518721e3caf158105cf8dd`。使用本地内容整合，没有远端拉取。
- 引入 main 侧 267 个增量路径：244 个新增、14 个单边更新、9 个双方修改文件人工整合。后续增加适配修复、测试与本文档。
- 这是 **zjy 工作区内容合并**，没有创建 Git merge commit、提交或推送，没有改写分支历史；VS Code 中仍显示待提交的修改和新增文件。

## 冲突与保留项

9 个冲突文件：根 README、`device_read_app.c`、`transport/can_transport.c`、固件 CMakeLists、`fdcan.h`、`fdcan.c`、`main.c`、`stm32g4xx_it.c`、`test_app_dual.c`。

保留原有 CAN1/2/3 初始化、接收中断、通道配置，BMS/Power/Dual 路由、按选定句柄读取 CAN 计数器、Dual 上电 3 秒等待、每设备每项目最多两次尝试，以及本地 Linux 工具与文档。整合 main 的电机应用、CAN 诊断、原生控制台、日志查看器与打包工具。修正新旧代码混合后遗留的 CAN3 固定日志/寄存器读取，波特率切换测试也按实际选定总线判断计数器。

## Ubuntu 22.04 适配

- 源码仓库和独立导出工作区都能发现真实固件路径，实验不再因为缺少嵌套目录而消失。
- CMake 3.22 使用 `-U PICO_*` 清理上次实验配置，不再使用不受支持的 `--fresh`。
- Python 3.10 使用流式 SHA256；归档解包显式验证路径与链接，避免依赖较新版本的接口。
- Linux LP64 主机测试中使用 `UINT32_MAX` 修复位宽导致的溢出告警。
- 启动脚本前台运行，错误可见；构建/烧录脚本共用控制台的实验和工具选择；烧录必须显式执行并校验目标。
- 增加 CAN1/CAN2 只读实验，保留原 CAN3 名称；扩展通道回归测试。
- 打包平台按实际系统标记，新增 Ubuntu 22.04 / Python 3.10 CI 矩阵，保留独立的 Ubuntu 24.04 作业和历史发布包。

## 实际执行结果

环境：Ubuntu 22.04.5、Python 3.10.12。交叉编译矩阵使用 `/usr/bin/cmake`（3.22）和 `/usr/bin/arm-none-eabi-gcc`（10.3.1）、Ninja，不要求原作者的打包工具链。

- 固件主机 CTest：**49/49 PASS**，含 CAN1/CAN2/CAN3 双设备应用、路由、传输、协议、电机控制与安全状态机测试。
- 控制台 unittest：**127/127 PASS**，含真实 Tk 窗口测试；使用本机桌面会话，没有执行硬件动作。
- Linux USB-CAN 协议/伪终端 unittest：**7/7 PASS**。
- 图形界面 CLI self-test：**PASS**，31 个公开实验入口，以及日志、轨迹、诊断、打包路径等检查通过。
- ARM 交叉编译：**49/49 PASS**。包含 34 个内置配置（含保留的旧实验）、本地 BMS/Power/Dual 的 9 个通道配置、PinLoop/Listen/CanMultiBench/MotorDualFault、两种明确目标的 PowerBaud 切换配置。逐项结果见同目录 `2026-11-15-ubuntu22-build-matrix.json`。
- 源码实际构建入口：`build.sh All` 的 Loopback/External 通过，`build_selected.py RS10P-Tuning` 通过。脚本可优先采用本机 STM32Cube 工具包；上面的独立矩阵另外验证了系统旧版本工具。
- 将工作区导出到 `/tmp/PICO Ubuntu22 迁移验证/project`：34 个内置配置路径均解析成功，实际编译 RS10P-Tuning 通过。
- 环境检查 `ready=true`；本轮检查时串口列表为空，硬件状态明确为 `NOT_RUN`。
- Shell 语法检查、Python compileall 通过。差异空白检查允许仓库明确保留的 CRLF（`core.whitespace=cr-at-eol`）。

## 可复测命令

以下均为软件测试或编译，不执行烧录。工作区搬移后先调整首行路径；GUI 检查要求有效的桌面会话，也可在已安装 Xvfb 时使用 xvfb-run。

```bash
cd /home/zjy/PICO/pico-firmware
cmake -S firmware/PICO_CAN/tests -B /tmp/pico-host-merge -G Ninja
cmake --build /tmp/pico-host-merge -j4
ctest --test-dir /tmp/pico-host-merge --output-on-failure
python3 -m unittest discover -s tools/pico_workbench/ui/tests
python3 -m unittest discover -s tools/pico_workbench/scripts/linux -p test_tools.py
python3 tools/pico_workbench/ui/package_cli.py self-test
python3 tools/pico_workbench/scripts/linux/validate_firmware_matrix.py --output /tmp/pico-arm-matrix
bash tools/pico_workbench/scripts/linux/build.sh All
git -c core.whitespace=cr-at-eol diff --check
```

## 未完成的验证，不作保证

本轮**没有烧录、没有使能电机、没有执行实物 CAN 通信或电机运动**；ST-LINK/OpenOCD 实际烧录、USB 权限、设备协议响应、实物限流、异常停机、负载和温升需要接板逐项验收。上游的反馈跳变及停止后不稳定等历史问题仍然保留，不因合并而宣称解决。

未安装 PyInstaller，**没有完成冻结 GUI/CLI、完整离线工具包的打包与搬移端到端验证**，也没有运行远端 CI 或发布新包。Windows 厂商 EXE/Wine 辅助工具未验证。不能把历史 Ubuntu 24.04 包改名后当作 Ubuntu 22.04 包。

使用说明见 [Ubuntu 22.04 指南](../Ubuntu_22.04.md)。
