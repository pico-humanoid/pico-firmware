# PICO-Firmware 固件设计

本仓库是 [PICO-Humanoid](https://github.com/pico-humanoid/pico-humanoid.github.io "访问项目主入口") 负责固件设计部分的子项目，主要涵盖电机 CAN 通讯、MCU 程序等内容。

## 电机 CAN 通讯

- [RobStride 电机控制库](https://github.com/RobStride/RobStrideSPC "进入GitHub仓库")：基于 STM32 HAL 的电机 CAN 通讯控制库
- 12路电机 CAN 在分电板集总后接入 MCU 主板，MCU 上的**引脚配置应当与主板设计相吻合**

## MCU 程序

- MCU 型号：建议 `STM32F407ZGT6`
    - [参考商品](https://item.jd.com/10148987370623.html?spmTag=YTAyMTguYjAwMjQ1NS5jMDAwMDM5OTEucHJvZHVjdF9uYW1lJTQwMTc5MTg4NjI5MTkzMSUyMzE4NDIwNjEwNiUyMzcxNTczOTgwMQ)
- 建议使用 **CubeMX + VSCode-STM32 插件** 开发，可参考[工具链指南](https://github.com/pico-humanoid/.github/blob/main/docs/toolchain-guide.md "跳转到“toolchain-guide.md”")
- 建议将 CubeMX 生成的项目文件夹放含有本 `.git` 的路径下