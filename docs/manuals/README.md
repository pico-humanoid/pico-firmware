# 本地手册副本

下载日期：2026-11-01。资料保存在工程目录，不依赖 `/tmp`。来源与 SHA-256 详见 `download-manifest.json`。

## 原版资料

- [电源板使用说明 V1.5_20260507（PDF）](电源板使用说明V1.5_20260507.pdf)：电源板接线、CAN 查询/控制、状态回复与参数表。
- [嘉佰达 CAN 通讯协议定义（DOCX）](嘉佰达CAN通讯协议定义.docx)：BMS CAN 帧、查询、数据和 CRC 定义。
- [USB-CAN-A 官方使用说明（HTML 快照）](USB-CAN-A官方使用说明.html)：适配器接线、终端、配置工具及收发操作。
- [USB-CAN-A 二次开发协议（HTML 快照）](USB-CAN-A二次开发协议.html)：电脑串口与适配器之间的协议；不是电源板自身的 CAN 协议。

PDF 和 DOCX 的 SHA-256 与此前用于实现协议模块的版本完全相同。HTML 是下载当时的官网页面，网页样式、图片和相对链接未完整离线打包；查看插图和下载工具请使用官方在线页。

## 便于搜索的文本提取版

- [电源板文本](电源板使用说明V1.5_20260507.txt)
- [BMS 文本](嘉佰达CAN通讯协议定义.txt)
- [USB-CAN-A 使用说明文本](USB-CAN-A官方使用说明.txt)
- [USB-CAN-A 二次开发协议文本](USB-CAN-A二次开发协议.txt)

文本为机器提取，尤其表格可能丢失行列关系；字段、位定义和接线必须回查原件，不能只凭文本排版判断。

## 在线来源

- [电源板 PDF](https://github.com/pico-humanoid/pico-electronics/blob/main/datasheet/电源板使用说明V1.5_20260507.pdf)
- [BMS DOCX](https://github.com/pico-humanoid/pico-electronics/blob/main/datasheet/嘉佰达CAN通讯协议定义.docx)
- [Waveshare USB-CAN-A](https://www.waveshare.net/wiki/USB-CAN-A)
- [Waveshare 串行转换 CAN 协议](https://www.waveshare.net/wiki/二次开发—串行转换CAN协议的定义)

当前先测试 USB-CAN-A 与电源板：主要使用电源板 PDF 和适配器说明；若编写 Linux 端收发程序，还需要二次开发协议。此目录没有安装或运行任何厂商程序。

## 仓库发布范围

保留协议原件、官方页面快照、文本提取版，以及硬件接线文档引用的 UM2505 手册与文本。第三方资料的权利归原权利人；本目录的引用与来源记录不代表取得额外的再分发授权，正式对外发布前应核对适用许可。

调试时生成的页面截图、重复裁剪图及下载失败的 `try.bin` 等不随 Git 上传，原文件已放入本地忽略归档，没有删除。正式接线图保留在 `docs/hardware/`。构建和测试工具不依赖被归档的截图或临时下载文件。
