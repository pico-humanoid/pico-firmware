#!/usr/bin/env python3
"""Read documented power-board status and readable parameters via USB-CAN-A.
Never sends type01 (control), type08 (write), or write-only RDF 0x6003.
Sources: docs/manuals/电源板使用说明V1.5_20260507.txt.
"""
import argparse
import datetime
import json
import math
from pathlib import Path
import struct
import time
from usb_can_power_probe import adapter_config, extract_frames

PARAMETERS = {
    0x6001: ('Can_baud', 'uint8'),
    0x6002: ('Com_baud', 'uint8'),
    0x6004: ('remoteCtrl', 'uint8'),
    0x6005: ('fanspeedCtrl', 'uint8'),
    0x6006: ('POWER_ID', 'uint8'),
    0x6007: ('soundEffect', 'uint8'),
    0x8001: ('currocpt', 'float'),
    0x8003: ('sdT', 'float'),
    0x8004: ('arTime', 'float'),
}


def requests(board_id):
    if not 0 <= board_id <= 255:
        raise ValueError('board ID must be 0..255')
    result = [('status03', 2, bytes(8), 3, None),
              ('status04', 2, b'\xca' + bytes(7), 4, None)]
    result += [(name, 7, index.to_bytes(2, 'little') + bytes(6), 7, index)
               for index, (name, _) in PARAMETERS.items()]
    return result


def packet(board_id, kind, data):
    if not 0 <= board_id <= 255 or len(data) != 8 or kind not in (2, 7):
        raise ValueError('only allow listed eight-byte read requests')
    if kind == 7 and int.from_bytes(data[:2], 'little') not in PARAMETERS:
        raise ValueError('parameter not in read allowlist')
    if kind == 2 and data not in (bytes(8), b'\xca' + bytes(7)):
        raise ValueError('unsupported status request')
    return b'\xaa\xe8' + ((kind << 24) | board_id).to_bytes(4, 'little') + data + b'\x55'


def decode(kind, data):
    if kind == 7:
        index = int.from_bytes(data[:2], 'little')
        if index not in PARAMETERS:
            return {'unrecognized_index': f'0x{index:04X}'}
        name, dtype = PARAMETERS[index]
        raw = data[4:8]
        result = dict(index=f'0x{index:04X}', name=name, raw_value=raw.hex(' '), value_u32_le=int.from_bytes(raw, 'little'))
        if dtype == 'uint8':
            result['value_u8'] = raw[0]
            result['upper_bytes_nonzero'] = any(raw[1:])
        else:
            value = struct.unpack('<f', raw)[0]
            result['value_float32_le_candidate'] = value if math.isfinite(value) else str(value)
        return result
    # Status byte order is not explicitly specified by this manual.
    result = {'status_byte_order': 'UNCONFIRMED', 'raw': data.hex(' ')}
    if kind == 3:
        result['temperature_c'] = data[4]
        result['fault_switch_bytes_raw'] = data[5:8].hex(' ')
        for order in ('big', 'little'):
            result[order + '_candidate'] = dict(battery_v=int.from_bytes(data[:2], order) / 100,
                                                motor_v=int.from_bytes(data[2:4], order) / 100)
    elif kind == 4:
        for order in ('big', 'little'):
            result[order + '_candidate_A_AL_AR_LL_LR'] = [int.from_bytes(data[i:i+2], order) / 100 for i in range(0, 8, 2)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--board-id', type=lambda s: int(s, 0), default=0xAA)
    parser.add_argument('--serial-baud', type=int, default=2000000)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    plan = requests(args.board_id)
    for label, kind, data, _, _ in plan:
        print(label, packet(args.board_id, kind, data).hex(' '))
    if not args.execute:
        print('DRY RUN; add --execute to send these read-only queries.')
        return 0
    import serial
    folder = Path(__file__).resolve().parents[1] / 'logs' / 'usb-can'
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-read.jsonl')
    results = {}
    with filename.open('x') as log:
        def record(event, **fields):
            entry = dict(time=datetime.datetime.now().astimezone().isoformat(), event=event, **fields)
            text = json.dumps(entry, ensure_ascii=False, allow_nan=False)
            print(text)
            log.write(text + '\n')
            log.flush()
        record('start', port=args.port, serial_baud=args.serial_baud, can_baud=1000000, board_id=args.board_id)
        with serial.Serial(args.port, args.serial_baud, timeout=0.05, write_timeout=1, exclusive=True) as port:
            def send(purpose, payload):
                if port.write(payload) != len(payload):
                    raise IOError('partial write')
                port.flush()
                record('tx', purpose=purpose, raw=payload.hex(' '))
            port.reset_input_buffer()
            send('adapter_config_only', adapter_config())
            time.sleep(0.3)
            pending = port.read(port.in_waiting) if port.in_waiting else b''
            if pending:
                record('rx_before_queries', raw=pending.hex(' '))
            buffer = bytearray()
            for label, kind, data, reply_kind, index in plan:
                send(label, packet(args.board_id, kind, data))
                deadline = time.monotonic() + 1
                matched = False
                while time.monotonic() < deadline:
                    chunk = port.read(max(1, min(4096, port.in_waiting)))
                    if not chunk:
                        continue
                    record('rx', raw=chunk.hex(' '))
                    buffer.extend(chunk)
                    for can_id, extended, remote, dlc, payload in extract_frames(buffer):
                        record('can', id=f'0x{can_id:08X}', extended=extended, remote=remote, dlc=dlc, data=payload.hex(' '))
                        if not extended or remote or dlc != 8 or ((can_id >> 16) & 255) != args.board_id:
                            continue
                        actual_kind = (can_id >> 24) & 31
                        if actual_kind != reply_kind or (index is not None and int.from_bytes(payload[:2], 'little') != index):
                            continue
                        decoded = decode(actual_kind, payload)
                        results[label] = decoded
                        matched = True
                        record('read_reply', query=label, **decoded)
                if not matched:
                    record('timeout', query=label)
            if buffer:
                record('unparsed_tail', raw=buffer.hex(' '))
        record('summary', received=len(results), expected=len(plan), results=results)
    print('Log:', filename)
    return 0 if len(results) == len(plan) else 2


if __name__ == '__main__':
    raise SystemExit(main())
