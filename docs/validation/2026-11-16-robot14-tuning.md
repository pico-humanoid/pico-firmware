# 2026-11-16 Robot14 可视化调参与串口链路软件验证

## 结论与边界

本记录对应 Robot14 专用可视化窗口及配套固件二进制串口协议。Ubuntu 22.04.5 LTS / Python 3.10.12 环境下，软件回归与交叉编译通过。**没有打开真实串口、烧录、复位、发送真实 CAN 控制，也没有使能电机；不代表14台电机实机联调通过。**

前一阶段的[整机驱动验证记录](2026-11-16-robot14.md)保持历史状态，本次新增结果及固件哈希单独记录，不用本轮产物覆盖其证据。

## 本轮实现

- 专用 Robot14 窗口：固定14节点拓扑、反馈与目标回显、三条曲线、CAN1双设备状态及三路 CAN 统计、CSV导出。
- 默认只读连接，逐台显式确认使能与限时控制；MIT五参数草稿不自动发送。旧单/双机窗口保留，新增整机入口。
- 固件新增独立二进制协议、带接收时间戳的 UART 环形队列与低优先级发送任务。CAN owner不等待串口发送。
- 普通单节点停机等待实际反馈后回到IDLE；全局停机锁存，需要人工复位。ACK不当作机械停稳证明。
- 会话/序号/拓扑签名校验、批量目标整包校验、100ms命令租约、150ms主机租约，以及界面心跳、ACK/遥测超时处理。PING不替代电机目标续约。
- CAN1仍使用既有双设备共享读取实现，不替换为独立测试程序。整机保护及接线边界见[驱动说明](../Robot14_Driver.md)。

用户操作、准确协议布局及保护限制见[使用说明](../Robot14_Tuning.md)。协议签名为 `0x14A20C02`，NODE为46字节；旧ASCII Robot14与旧单/双机固件不兼容。

## 实际测试结果

- 固件主机测试 **55/55**：[日志](2026-11-16-robot14-tuning/host-tests.log)。包括原有应用回归、Robot14状态机/传输/配置、二进制协议与UART队列。
- Python模型、界面及工作台回归 **164/164**：[日志](2026-11-16-robot14-tuning/ui-tests.log)。包括28项Robot14模型/模拟串口测试、8项专用UI及入口测试，其余为既有界面回归。全程假串口；C与Python协议互通测试编译实际C编码器，非仅Python自回环。
- 工作台CLI自检 **PASS，32个配置**：[日志](2026-11-16-robot14-tuning/workbench-self-test.log)。包含专用窗口14行只读初始状态与入口检查。
- Linux协议/工具测试 **7/7**：[日志](2026-11-16-robot14-tuning/linux-tools-tests.log)。
- 交叉编译矩阵 **50/50**：[日志](2026-11-16-robot14-tuning/firmware-matrix.log)。包含旧应用、三路CAN变体与Robot14，未改为默认自动运行Robot14。
- Robot14筛选项 ASan/UBSan/LSan **6/6**：[日志](2026-11-16-robot14-tuning/sanitizer-tests.log)。初次沙箱执行受LSan ptrace限制，允许本地测试运行后通过；测试不访问硬件。
- Robot14 Debug构建通过：FLASH **56748 B**、RAM **40728 B**，见[构建日志](2026-11-16-robot14-tuning/robot14-debug-build.log)。
- Robot14 Release构建通过：FLASH **33936 B**、RAM **40728 B**，见[构建日志](2026-11-16-robot14-tuning/robot14-release-build.log)。以上为链接器静态占用，不是动态任务栈/堆峰值实测。

## 重点模拟覆盖

- CRC已知向量、分片、损坏与恢复、超长/超时帧、随机字节流；会话切换、重放及旧固件拒绝。
- 全14节点目标批量、100轮续约、整批拒绝不部分生效、握手只允许零目标、PING不续电机租约。
- 单节点停机、等待IDLE、重新显式使能、未确认停机/ACK超时升级；全局停机清空未发目标与队列中的UI请求。
- 只读连接/断开不主动控制、遥测中断关闭、使能时长到期、界面冻结、活动连接关闭、串口写失败与停止优先级。
- UART接收溢出/错误修复、时间戳、发送队列为控制应答预留空间；NODE字段比例、反馈年龄与BMS电压有效掩码。
- 所有UI构造测试均禁用自动连接，使用内存假串口或纯模型。

## 重跑入口

在工程根目录运行：

```bash
cmake -S firmware/PICO_CAN/tests -B /tmp/pico-multi/host -G Ninja
cmake --build /tmp/pico-multi/host -j6
ctest --test-dir /tmp/pico-multi/host --output-on-failure
PYTHONPATH=tools/pico_workbench/ui python3 -m unittest discover -s tools/pico_workbench/ui/tests
PYTHONPATH=tools/pico_workbench/ui python3 tools/pico_workbench/ui/package_cli.py self-test
python3 tools/pico_workbench/scripts/linux/test_tools.py
python3 tools/pico_workbench/scripts/linux/validate_firmware_matrix.py --output /tmp/pico-multi/matrix
bash firmware/PICO_CAN/scripts/build.sh Robot14
```

Tk测试需要有效本地图形显示；sanitizer需要允许LSan运行的环境。上述测试不以硬件连接作为前提。

## 产物与证据

- Debug当前产物：`firmware/PICO_CAN/build/Linux-Robot14/PICO_CAN.{elf,hex,bin}`。
- Release验证产物位于本机临时目录 `/tmp/pico-multi/Robot14-Release/`，不是永久归档文件。
- [固件 SHA-256](2026-11-16-robot14-tuning/firmware-sha256.txt)；[本轮关键源码 SHA-256](2026-11-16-robot14-tuning/source-sha256.txt)。哈希记录本轮文件，后续重编译/修改应更新验证记录。
- [日志目录](2026-11-16-robot14-tuning/)包含配置、构建、自检和回归原始输出。文件中的绝对路径为本机验证路径。

## 尚未验收

1. 实际UART吞吐/抖动、14电机同时反馈与控制、单台停机和全局停机的真实动作/耗时。
2. 电机看门狗真实超时行为、拔线、bus-off、MCU复位及电源故障下的实物保护。
3. 关节零位、方向、机械限位、负载整定，以及BMS/电源板自动动力互锁；GUI限幅不构成硬件安全保证。
4. Ubuntu冻结便携包未重打包，使用当前源码启动。完整CubeMX源码再生成仍未验证，不能直接Generate Code覆盖现有工程。
5. 构建/模拟测试不能说明输出轴角度连续性或此前个别电机跳变故障已解决；不要将反馈再次除以25。
