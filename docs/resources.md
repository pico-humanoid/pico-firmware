# 项目资料与学习入口

已有资料由固件侧先查阅并记录版本。协议阅读、外设配置和实验操作对应[开发计划](firmware-development.md)，项目专有约束按[协作清单](collaboration/README.md)沟通。

## 项目内资料

- [PICO-Humanoid 项目主页](https://pico-humanoid.github.io/)
- [机械设计仓库](https://github.com/pico-humanoid/pico-mechanism)：当前 14 自由度结构、关节名称和 RS-10P / RS-00 型号。
- [电气设计仓库](https://github.com/pico-humanoid/pico-electronics)：主板、电源与设备资料。
- [供电方案](https://github.com/pico-humanoid/pico-electronics/blob/main/power/供电方案.md) · [电池方案](https://github.com/pico-humanoid/pico-electronics/blob/main/power/电池方案.md)
- [电源板使用说明 V1.5](https://github.com/pico-humanoid/pico-electronics/blob/main/datasheet/电源板使用说明V1.5_20260507.pdf) · [嘉佰达 CAN 协议](https://github.com/pico-humanoid/pico-electronics/blob/main/datasheet/嘉佰达CAN通讯协议定义.docx)

## 官方手册与工具

- [RobStride 电机控制库](https://github.com/RobStride/RobStrideSPC) · [RobStride 产品资料](https://github.com/RobStride/Product_Information)：核对各型号协议、参数范围和 HAL 适配。
- [STM32G474RE 数据手册](https://www.st.com/resource/en/datasheet/stm32g474re.pdf)：核对外设、复用功能与电气参数。
- [NUCLEO-G474RE 板卡手册](https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf)：核对排针、ST-LINK 和板上连接。
- [SN65HVD230 数据手册](https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf)：核对收发器供电、接口与使用条件。
- [Waveshare USB-CAN-A 官方使用说明](https://www.waveshare.net/wiki/USB-CAN-A)：驱动、配置工具、接线、参数设置及收发测试。

[返回仓库首页](../README.md)
