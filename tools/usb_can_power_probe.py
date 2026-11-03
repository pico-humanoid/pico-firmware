#!/usr/bin/env python3
"""Waveshare USB-CAN-A: one read-only power-board version query.

Protocol sources: docs/manuals/USB-CAN-A二次开发协议.txt and
电源板使用说明V1.5_20260507.txt. Configures the ADAPTER, not the board.
No baud scan, retries, output commands, or board parameter writes.
"""
import argparse
import datetime
import json
from pathlib import Path
import time


def adapter_config(can_baud=1000000):
    # Variable length protocol, selected CAN bitrate, extended frames, accept all,
    # normal mode, disable automatic retransmission.
    if can_baud not in (1000000, 500000):
        raise ValueError('only 1M and 500K profiles are allowed')
    # Adapter code 3=500K; BOARD Can_baud code 2=500K. Do not mix them.
    code = 1 if can_baud == 1000000 else 3
    p = bytearray([0xAA, 0x55, 0x12, code, 2] + [0] * 8 + [0, 1] + [0] * 4)
    p.append(sum(p[2:]) & 0xFF)
    return bytes(p)


def version_query(board_id):
    if not 0 <= board_id <= 255:
        raise ValueError('board ID must be 0..255')
    can_id = 0x05000000 | board_id
    return b'\xaa\xe8' + can_id.to_bytes(4, 'little') + bytes(8) + b'\x55'


def extract_frames(buffer):
    frames = []
    while buffer:
        if buffer[0] != 0xAA:
            del buffer[0]
            continue
        if len(buffer) < 2:
            break
        kind = buffer[1]
        if kind & 0xC0 != 0xC0 or kind & 15 > 8:
            del buffer[0]
            continue
        extended, remote, dlc = bool(kind & 32), bool(kind & 16), kind & 15
        id_size = 4 if extended else 2
        length = 2 + id_size + (0 if remote else dlc) + 1
        if len(buffer) < length:
            break
        if buffer[length - 1] != 0x55:
            del buffer[0]
            continue
        can_id = int.from_bytes(buffer[2:2 + id_size], 'little')
        if can_id > (0x1FFFFFFF if extended else 0x7FF):
            del buffer[0]
            continue
        data = bytes(buffer[2 + id_size:length - 1])
        frames.append((can_id, extended, remote, dlc, data))
        del buffer[:length]
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--serial-baud', type=int, default=2000000)
    parser.add_argument('--board-id', type=lambda s: int(s, 0), default=0xAA)
    parser.add_argument('--execute', action='store_true', help='actually open serial and send')
    parser.add_argument('--log-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'logs' / 'usb-can')
    args = parser.parse_args()
    config, query = adapter_config(), version_query(args.board_id)
    print(f'Port={args.port}, UART={args.serial_baud}, CAN=1Mbps, board=0x{args.board_id:02X}')
    print('ADAPTER_CONFIG:', config.hex(' '))
    print('VERSION_QUERY: ', query.hex(' '))
    if not args.execute:
        print('DRY RUN: nothing opened/sent; add --execute to run.')
        return 0
    import serial
    args.log_dir.mkdir(parents=True, exist_ok=True)
    filename = args.log_dir / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.jsonl')
    matched = False
    with filename.open('x') as log:
        def record(event, **fields):
            entry = dict(time=datetime.datetime.now().astimezone().isoformat(), event=event, **fields)
            log.write(json.dumps(entry, ensure_ascii=False) + '\n')
            log.flush()
            print(json.dumps(entry, ensure_ascii=False))
        record('start', port=args.port, serial_baud=args.serial_baud, can_baud=1000000, board_id=args.board_id)
        with serial.Serial(args.port, args.serial_baud, timeout=0.1, write_timeout=1, exclusive=True) as port:
            def send(label, payload):
                written = port.write(payload)
                if written != len(payload):
                    raise IOError('partial serial write')
                port.flush()
                record('tx', purpose=label, raw=payload.hex(' '))
            port.reset_input_buffer()
            send('adapter configuration (NOT board parameters)', config)
            time.sleep(0.3)
            # Preserve any adapter acknowledgment or unsolicited CAN frames.
            pending = port.read(port.in_waiting) if port.in_waiting else b''
            if pending:
                record('rx_before_query', raw=pending.hex(' '))
            send('single version query', query)
            buffer = bytearray()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                chunk = port.read(max(1, min(port.in_waiting, 4096)))
                if not chunk:
                    continue
                record('rx', raw=chunk.hex(' '))
                buffer.extend(chunk)
                for can_id, extended, remote, dlc, data in extract_frames(buffer):
                    record('can', id=f'0x{can_id:08X}', extended=extended, remote=remote, dlc=dlc, data=data.hex(' '))
                    # Reject an echoed request: board source occupies bits16..23.
                    if extended and not remote and dlc == 8 and can_id >> 24 == 5 and (can_id >> 16) & 255 == args.board_id:
                        version = data.rstrip(b'\0')
                        if version and all(32 <= b < 127 for b in version):
                            matched = True
                            record('version_reply', version=version.decode('ascii'))
            if buffer:
                record('unparsed_tail', raw=buffer.hex(' '))
        record('result', version_reply_received=matched)
    print('Log:', filename)
    if not matched:
        print('No matching version reply. Serial write alone does NOT prove CAN success.')
    return 0 if matched else 2


if __name__ == '__main__':
    raise SystemExit(main())
