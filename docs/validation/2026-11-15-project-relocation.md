# PICO 工程迁移验证（2026-11-15）

## 位置与兼容

- 原位置：`/home/zjy/PICO`
- 新实际位置：`/home/zjy/Systems and Control/PICO`
- 主工程：`/home/zjy/Systems and Control/PICO/pico-firmware`
- 原路径保留为指向新目录的符号链接；只有一份实际工程。暂不要删除此链接。
- VS Code 工作区：`/home/zjy/Systems and Control/PICO/PICO.code-workspace`（相对路径配置），已发送打开请求。
- 备份：`/home/zjy/Systems and Control/PICO-migration-backup-20261115_193010`。

## 已完成

整体移动 PICO，保留 main 副本及附件；更新 18 个实验工作区、活动说明文档、VS Code 工程路径和相关缓存。旧 CMake 构建目录 37 个移入备份，避免复用包含旧绝对路径的缓存；在新路径重新构建。

移动后、编辑配置前的 4901 个原文件校验通过；后续核对原文件均可在新目录或构建备份中找到，427 个历史日志归档校验不变。保留历史日志中的原始路径，由兼容链接支持访问。

Git 分支 `zjy`，HEAD `42640a39769950131aa314969ba7df46333c7c44`；保留原有未提交修改，没有提交、推送、重置。

## 新路径验证

- 主机 CMake 配置、编译及 CTest：49/49。
- UI 单元测试：127/127。
- Linux 工具测试：7/7。
- CLI self-test：通过。
- ARM RS10P-Position-Diag 及 Loopback / External：编译通过。
- ARM 完整配置矩阵：49/49，失败 0。
- 环境检查：退出码 0；硬件验证 NOT_RUN。

验证日志和矩阵结果持久保存在上述备份的 `verification` 子目录。未烧录、复位、使能电机；软件测试不能替代硬件实测。

## GPT/Codex 路径同步：还需退出后执行一次

运行中的桌面应用会将内存中的旧路径写回配置，不能将在线修改配置视为完成。SQLite 项目和会话工作目录已更新过，但当前界面的项目缓存仍可能是旧路径；兼容链接保证仍访问同一份工程。

完全退出 GPT/Codex 桌面应用后，在系统终端运行：

```bash
python3 "/home/zjy/Systems and Control/PICO/同步GPT工程路径.py"
```

再重新打开应用。脚本检测到桌面应用仍运行会拒绝修改。脚本先备份，再同步本机项目状态与 SQLite 工作目录，不修改历史对话文本、不自动重启、不移除兼容链接。最终界面路径需重开应用后确认。

## 工作台启动

```bash
bash "/home/zjy/Systems and Control/PICO/pico-firmware/tools/pico_workbench/ui/start.sh"
```

路径包含空格，终端中使用完整引号。
