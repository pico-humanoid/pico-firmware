#!/usr/bin/env python3
"""Bounded USB-CAN-A reads and explicitly authorized ONE board baud write.
No automatic power cycle, rate scan, write retry or output control.
"""
import argparse
import datetime
import json
from pathlib import Path
import time
from usb_can_power_probe import adapter_config, extract_frames, version_query
from usb_can_power_read import requests, packet, decode


def baud_write(board_id):
    if not 0 <= board_id <= 255:
        raise ValueError('invalid board ID')
    return b'\xaa\xe8' + (0x08000000 | board_id).to_bytes(4, 'little') + bytes.fromhex('01 60 00 00 02 00 00 00') + b'\x55'


def matches(frame, board_id, kind, index):
    can_id, extended, remote, dlc, data = frame
    return (extended and not remote and dlc == 8 and
            ((can_id >> 16) & 255) == board_id and
            ((can_id >> 24) & 31) == kind and
            (index is None or int.from_bytes(data[:2], 'little') == index))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', default='/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0')
    ap.add_argument('--can-baud', type=int, choices=[1000000, 500000], required=True)
    ap.add_argument('--board-id', type=lambda s: int(s, 0), default=0xAA)
    ap.add_argument('--cycles', type=int, default=3)
    ap.add_argument('--write-500k', action='store_true')
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    if not 0 <= args.board_id <= 255 or not 1 <= args.cycles <= 100:
        ap.error('invalid board ID or cycles')
    if args.write_500k and (args.can_baud != 1000000 or args.cycles < 2):
        ap.error('write requires 1M source and at least two successful read cycles')
    print('ADAPTER_CONFIG', adapter_config(args.can_baud).hex(' '))
    if args.write_500k:
        print('ONE_BOARD_WRITE', baud_write(args.board_id).hex(' '))
    if not args.execute:
        print('DRY RUN; no device opened')
        return 0
    import serial
    folder = Path(__file__).resolve().parents[1] / 'logs/usb-can'
    folder.mkdir(parents=True, exist_ok=True)
    name = folder / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-baud-validation.jsonl')
    plan = [('version', version_query(args.board_id), 5, None)] + [
        (label, packet(args.board_id, kind, data), reply_kind, index)
        for label, kind, data, reply_kind, index in requests(args.board_id)]
    submitted = matched = 0
    codes = []
    first_reply = last_reply = None
    start = time.monotonic()
    with name.open('x') as log:
        def record(event, **fields):
            row = dict(time=datetime.datetime.now().astimezone().isoformat(),
                       elapsed_s=round(time.monotonic()-start, 6), event=event, **fields)
            text = json.dumps(row, ensure_ascii=False, allow_nan=False)
            log.write(text+'\n'); log.flush()
            if event not in ('rx_raw', 'can'):
                print(text, flush=True)
        record('start', can_baud=args.can_baud, cycles=args.cycles, write_500k=args.write_500k,
               port=args.port, note='UART submit is NOT a CAN Tx completion')
        write_attempted = False
        try:
            with serial.Serial(args.port, 2000000, timeout=0.02, write_timeout=1, exclusive=True) as port:
                def send(purpose, raw):
                    record('serial_write_intent', purpose=purpose, raw=raw.hex(' '))
                    n = port.write(raw)
                    if n != len(raw):
                        raise IOError('partial serial write; delivery uncertain; no automatic retry')
                    port.flush()
                    record('serial_submitted', purpose=purpose, raw=raw.hex(' '))
                buffer = bytearray()
                def receive(seconds, expected=None):
                    deadline = time.monotonic()+seconds
                    while time.monotonic() < deadline:
                        chunk = port.read(max(1, min(port.in_waiting, 4096)))
                        if not chunk:
                            continue
                        record('rx_raw', raw=chunk.hex(' '))
                        buffer.extend(chunk)
                        found = None
                        for f in extract_frames(buffer):
                            cid, ext, remote, dlc, data = f
                            record('can', id=f'0x{cid:08X}', extended=ext, remote=remote, dlc=dlc, data=data.hex(' '))
                            if expected and matches(f, args.board_id, *expected):
                                found = f
                            if write_attempted and matches(f, args.board_id, 3, None):
                                record('type03_candidate', note='shared status, not unique write ACK')
                        if found is not None:
                            return found
                    return None
                port.reset_input_buffer()
                send('adapter_configuration_only', adapter_config(args.can_baud))
                receive(0.3)
                for cycle in range(args.cycles):
                    for label, raw, kind, index in plan:
                        receive(0.01)  # Log pre-existing traffic; do not match it to a new query.
                        if buffer:
                            record('discard_prequery_partial', raw=buffer.hex(' ')); buffer.clear()
                        sent_at = time.monotonic()
                        send(label, raw); submitted += 1
                        f = receive(0.7, (kind, index))
                        if f is None:
                            record('read_timeout', cycle=cycle+1, query=label)
                            record('summary', result='READ_FAILED_NO_WRITE', submitted=submitted, matched=matched)
                            return 2
                        if kind == 5:
                            value = f[4].rstrip(b'\0')
                            if not value or not all(32 <= b < 127 for b in value):
                                raise ValueError('invalid version payload')
                            decoded = dict(version=value.decode('ascii'))
                        else:
                            decoded = decode(kind, f[4])
                        if index == 0x6001:
                            codes.append(f[4][4])
                            if args.can_baud == 500000 and f[4][4] != 2:
                                raise ValueError('500K link response but Can_baud is not 2')
                            if args.can_baud == 1000000 and f[4][4] not in (1, 2):
                                raise ValueError('unexpected Can_baud code at source link')
                        matched += 1
                        now = time.monotonic()
                        first_reply = now if first_reply is None else first_reply
                        last_reply = now
                        record('read_reply', cycle=cycle+1, query=label, **decoded)
                        receive(max(0, 0.2-(time.monotonic()-sent_at)))
                record('read_window', submitted=submitted, matched=matched,
                       reply_span_s=round(last_reply-first_reply, 6), can_baud_codes=codes,
                       note='No controller error counters available through this serial protocol')
                if args.write_500k:
                    if codes and all(c == 2 for c in codes):
                        record('summary', result='TARGET_ALREADY_REPORTED_NO_REDUNDANT_WRITE',
                               next='manual board power cycle then 500K validation')
                        return 0
                    if not codes or not all(c == 1 for c in codes):
                        raise ValueError('source parameter changed; refuse write')
                    write_attempted = True  # Consume before serial write; never retry, including exceptions.
                    send('ONE_board_Can_baud_write_code2', baud_write(args.board_id))
                    receive(0.8)
                    send('postwrite_read_6001', packet(args.board_id, 7, bytes.fromhex('01 60 00 00 00 00 00 00')))
                    f = receive(1.0, (7, 0x6001))
                    record('postwrite_readback', received=f is not None,
                           code=f[4][4] if f else None, note='not proof of persistence or 500K communication')
                    record('summary', result='WRITE_SERIAL_SUBMITTED_MIGRATION_NOT_YET_VERIFIED',
                           next='manual board power cycle then 500K validation', board_write_attempts=1)
                else:
                    record('summary', result='READ_WINDOW_OK', submitted=submitted, matched=matched,
                           can_baud=args.can_baud, reply_span_s=round(last_reply-first_reply, 6))
        except Exception as exc:
            record('error', message=str(exc), write_attempted=write_attempted,
                   note='No automatic write retry; inspect delivery before further action')
            return 3
        finally:
            print('Log:', name, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
