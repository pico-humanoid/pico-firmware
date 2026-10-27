# 历史板端日志索引

原工程 ZIP 中的 20 份 CSV 全部按原始字节保留。本索引记录文件名、大小与原有 RESULT；当前内部回环结果采用后续补充的最新日志。

- [工程日志目录](../../firmware/PICO_CAN/logs/)
- [2026-10-27 实测分析](2026-10-27.md)
- [原始工程、固件和采集工具](../../firmware/PICO_CAN/IMPORT.md)

最新 [board_20261027_171137.csv](../../logs/2026-10-27/board_20261027_171137.csv)已核对通过：模式为内部回环，提交发送、发送完成、接收各 100 条，RESULT=PASS。它作为当前主要结果单独归档；下表列出较早原工程 ZIP 中的历史记录。

| 文件 | 字节数 | 原有 RESULT |
| --- | --- | --- |
| [board_20261023_111123.csv](../../firmware/PICO_CAN/logs/board_20261023_111123.csv) | 233 | PASS |
| [board_20261023_111133.csv](../../firmware/PICO_CAN/logs/board_20261023_111133.csv) | 0 | 未记录 |
| [board_20261023_112302.csv](../../firmware/PICO_CAN/logs/board_20261023_112302.csv) | 2 | 未记录 |
| [board_20261023_112347.csv](../../firmware/PICO_CAN/logs/board_20261023_112347.csv) | 5407 | 未记录 |
| [board_20261023_112358.csv](../../firmware/PICO_CAN/logs/board_20261023_112358.csv) | 2940 | 未记录 |
| [board_20261023_112404.csv](../../firmware/PICO_CAN/logs/board_20261023_112404.csv) | 4409 | PASS |
| [board_20261023_112427.csv](../../firmware/PICO_CAN/logs/board_20261023_112427.csv) | 16493 | PASS |
| [board_20261023_120253.csv](../../firmware/PICO_CAN/logs/board_20261023_120253.csv) | 0 | 未记录 |
| [board_20261023_120302.csv](../../firmware/PICO_CAN/logs/board_20261023_120302.csv) | 0 | 未记录 |
| [board_20261023_120313.csv](../../firmware/PICO_CAN/logs/board_20261023_120313.csv) | 0 | 未记录 |
| [board_20261023_120330.csv](../../firmware/PICO_CAN/logs/board_20261023_120330.csv) | 0 | 未记录 |
| [board_20261023_120339.csv](../../firmware/PICO_CAN/logs/board_20261023_120339.csv) | 157 | 未记录 |
| [board_20261023_120615.csv](../../firmware/PICO_CAN/logs/board_20261023_120615.csv) | 157 | 未记录 |
| [board_20261023_120839.csv](../../firmware/PICO_CAN/logs/board_20261023_120839.csv) | 157 | 未记录 |
| [board_20261023_121154.csv](../../firmware/PICO_CAN/logs/board_20261023_121154.csv) | 157 | 未记录 |
| [board_20261023_121324.csv](../../firmware/PICO_CAN/logs/board_20261023_121324.csv) | 157 | 未记录 |
| [board_20261023_121625.csv](../../firmware/PICO_CAN/logs/board_20261023_121625.csv) | 10716 | FAIL |
| [board_20261027_162350.csv](../../firmware/PICO_CAN/logs/board_20261027_162350.csv) | 12347 | PASS |
| [board_20261027_164240.csv](../../firmware/PICO_CAN/logs/board_20261027_164240.csv) | 11516 | PASS |
| [board_20261027_164330.csv](../../firmware/PICO_CAN/logs/board_20261027_164330.csv) | 10678 | FAIL |

工程包内两份 `board_20261027_164240.csv`、`board_20261027_164330.csv` 与外层 [logs/2026-10-27](../../logs/2026-10-27/) 中的同名上传文件逐字节一致。
