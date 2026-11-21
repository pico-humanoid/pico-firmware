# 程序入口与验证范围

- [固件App源码](../firmware/PICO_CAN/App/)：基础CAN、设备只读、单机启停/速度/位置、停机诊断、双机独立与共同时间轴、交互跟踪。
- [控制台与日志查看器](../tools/pico_workbench/ui/)：native.py、log_viewer.py。
- [交互跟踪](Motor_Tuning.md)：motor_tuning.py、tuning_scope.py；单机RS10P/RS00与双机Motors-Tuning。
- [官方控制库适配](RobStrideSPC_Adaptation.md)：固定提交、移植补丁、保护状态机与测试。
- [主机回归测试](../firmware/PICO_CAN/tests/)：含单/双机准备屏障、时长、回读与联动停机。

零电流使能与0.7A专用试验入口已退役，共用源文件及历史测试保留；不建议绕过当前控制台保护直接使用历史程序。完整Windows包使用Release附件，Ubuntu需对应平台运行环境。
