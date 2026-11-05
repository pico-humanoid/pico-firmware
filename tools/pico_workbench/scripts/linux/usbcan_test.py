"""Waveshare/USBCAN V2.12 serial adapter: independent 100-frame PC-side test.

Protocol follows Waveshare's official USB-CAN-A Linux C demo (settings 0x12,
variable-length standard data frames). It is not the SocketCAN/slcan protocol.
"""
import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
import serial
from ports import choose_port

ROOT = Path(__file__).resolve().parents[2]


def settings_packet():
    packet = bytearray([0xAA, 0x55, 0x12, 0x01, 0x01] + [0] * 8 + [0x00, 0x01] + [0] * 4)
    packet.append(sum(packet[2:]) & 0xFF)
    return bytes(packet)


def data_packet(identifier, payload):
    if not 0 <= identifier <= 0x7FF or not 0 <= len(payload) <= 8:
        raise ValueError("需要经典 CAN 标准帧，最多 8 字节")
    return bytes([0xAA, 0xC0 | len(payload), identifier & 0xFF, identifier >> 8]) + bytes(payload) + b"\x55"


@dataclass
class Frame:
    identifier: int
    data: bytes
    extended: bool = False
    remote: bool = False


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.malformed = 0

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            if self.buffer[0] != 0xAA:
                del self.buffer[0]
                self.malformed += 1
                continue
            if len(self.buffer) < 2:
                break
            info = self.buffer[1]
            if info == 0x55:
                if len(self.buffer) < 20:
                    break
                if sum(self.buffer[2:19]) & 0xFF != self.buffer[19]:
                    self.malformed += 1
                del self.buffer[:20]
                continue
            if info & 0xC0 != 0xC0 or info & 0x0F > 8:
                del self.buffer[0]
                self.malformed += 1
                continue
            extended, remote = bool(info & 0x20), bool(info & 0x10)
            id_len, dlc = (4 if extended else 2), info & 0x0F
            data_len = 0 if remote else dlc
            size = 3 + id_len + data_len
            if len(self.buffer) < size:
                break
            if self.buffer[size - 1] != 0x55:
                del self.buffer[0]
                self.malformed += 1
                continue
            ident = int.from_bytes(self.buffer[2:2 + id_len], "little")
            frames.append(Frame(ident, bytes(self.buffer[2 + id_len:size - 1]), extended, remote))
            del self.buffer[:size]
        return frames


def assess(frames, sent, malformed=0):
    tail = bytes.fromhex("22 33 44 55 66 77 88")
    sequence, invalid, other = [], 0, 0
    for item in frames:
        if item.identifier != 0x123:
            other += 1
        elif item.extended or item.remote or len(item.data) != 8 or item.data[0] >= 100 or item.data[1:] != tail:
            invalid += 1
        else:
            sequence.append(item.data[0])
    missing = sorted(set(range(100)) - set(sequence))
    duplicates = sorted({v for v in sequence if sequence.count(v) > 1})
    passed = sent == 100 and len(sequence) == 100 and not (missing or duplicates or invalid or other or malformed)
    return {"pass": passed, "tx_count": sent, "rx_valid": len(sequence), "rx_missing": missing,
            "rx_duplicates": duplicates, "rx_invalid": invalid, "rx_other": other, "serial_malformed": malformed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--delay", type=float, default=5, help="配置适配器后、开始发测试帧前的等待秒数")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if args.timeout < 11 or args.delay < 0:
        parser.error("timeout 至少 11 秒，delay 不小于零")
    port = choose_port("usbcan", args.port)
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    path = logs / ("linux_usbcan_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".csv")
    decoder, frames, sent = Decoder(), [], 0
    with serial.Serial(port, args.baud, timeout=0.01, write_timeout=1, exclusive=True) as dev, path.open("w", newline="", encoding="utf-8") as output:
        dev.reset_input_buffer()
        dev.write(settings_packet())
        dev.flush()
        print(f"USB-CAN {port}：串口 {args.baud}，CAN 1 Mbps，经典 CAN 标准帧、正常模式。", flush=True)
        print(f"{args.delay:g} 秒后开始发送，请先确保板端已烧录 External，日志已打开并已按 RESET。", flush=True)
        time.sleep(args.delay)
        dev.reset_input_buffer()
        writer = csv.writer(output)
        writer.writerow(["elapsed_ms", "event", "format", "id", "dlc", "data"])
        start, next_send = time.monotonic(), time.monotonic()
        while time.monotonic() - start < args.timeout:
            if sent < 100 and time.monotonic() >= next_send:
                payload = bytes([sent]) + bytes.fromhex("88 77 66 55 44 33 22")
                dev.write(data_packet(0x321, payload))
                dev.flush()
                writer.writerow([round((time.monotonic() - start) * 1000), "TX_SUBMIT", "STD", "0x321", 8, payload.hex(" ").upper()])
                sent += 1
                next_send = time.monotonic() + 0.1
            for frame in decoder.feed(dev.read(dev.in_waiting or 1)):
                frames.append(frame)
                writer.writerow([round((time.monotonic() - start) * 1000), "RX_REMOTE" if frame.remote else "RX", "EXT" if frame.extended else "STD", f"0x{frame.identifier:X}", len(frame.data), frame.data.hex(" ").upper()])
                print(f"RX 0x{frame.identifier:03X} {frame.data.hex(' ').upper()}", flush=True)
            output.flush()
    result = assess(frames, sent, decoder.malformed + bool(decoder.buffer))
    path.with_suffix(".check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"日志：{path}\n电脑端检查：{'PASS' if result['pass'] else 'FAIL'}。另核对开发板日志的 RESULT。")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, serial.SerialException) as exc:
        print(f"USB-CAN 无法测试：{exc}")
        raise SystemExit(2)
