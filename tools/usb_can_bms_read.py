#!/usr/bin/env python3
"""Bounded, read-only JBD BMS queries through Waveshare USB-CAN-A.

Local sources: docs/manuals/嘉佰达CAN通讯协议定义.txt and
USB-CAN-A二次开发协议.txt. Only STD/RTR IDs 100/101/102/103/105;
no BMS writes, rate scan, retry, output control or wake-up commands.
"""
import argparse
import datetime
import json
from pathlib import Path
import time

from usb_can_power_probe import adapter_config, extract_frames

QUERY_IDS = (0x100, 0x101, 0x102, 0x103, 0x105)


def bms_adapter_config():
    p = bytearray(adapter_config(500000))
    p[4] = 1  # Standard frames; normal mode, automatic retransmission disabled.
    p[-1] = sum(p[2:19]) & 255
    return bytes(p)


def query_packet(can_id, dlc=8):
    if can_id not in QUERY_IDS or dlc not in (0, 8):
        raise ValueError('only allow listed read-only BMS RTR IDs and DLC 0/8')
    # RTR DLC describes requested reply length, not a request data payload.
    return bytes((0xAA, 0xD0 | dlc)) + can_id.to_bytes(2, 'little') + b'\x55'


def crc16(data):
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def decode_reply(frame, expected_id, crc_endian='big'):
    cid, extended, remote, dlc, data = frame
    if expected_id not in QUERY_IDS or cid != expected_id or extended or remote or dlc != 8 or len(data) != 8:
        raise ValueError('expected same-ID STD DATA DLC8 response')
    if crc_endian not in ('big', 'little'):
        raise ValueError('invalid CRC byte order')
    computed = crc16(data[:6])
    received = int.from_bytes(data[6:], crc_endian)
    if computed != received:
        opposite = 'little' if crc_endian == 'big' else 'big'
        raise ValueError(f'CRC mismatch: computed=0x{computed:04X}, received=0x{received:04X}; '
                         f'opposite_byte_order_matches={computed == int.from_bytes(data[6:], opposite)}; '
                         'no automatic byte-order change')
    a, b, c = (int.from_bytes(data[i:i+2], 'big') for i in (0, 2, 4))
    result = dict(crc_ok=True, crc_endian=crc_endian, crc16=f'0x{computed:04X}')
    if cid == 0x100:
        result.update(voltage_v=a / 100, current_a=(b if b < 32768 else b - 65536) / 100,
                      remaining_capacity_ah=c / 100)
    elif cid == 0x101:
        if c > 100:
            raise ValueError(f'SOC outside documented 0..100: {c}')
        result.update(full_capacity_ah=a / 100, cycles=b, soc_percent=c)
    elif cid == 0x102:
        result.update(balance_low=f'0x{a:04X}', balance_high=f'0x{b:04X}', protection=f'0x{c:04X}')
    elif cid == 0x103:
        result.update(mos_status_raw=f'0x{a:04X}', charge_mos_on=bool(a & 1),
                      discharge_mos_on=bool(a & 2), production_date_raw=f'0x{b:04X}',
                      software_version_raw=c)
    elif cid == 0x105:
        result.update(temperature_c=[(value - 2731) / 10 for value in (a, b, c)],
                      note='Sensor presence/plausibility requires independent confirmation')
    return result


class Session:
    def __init__(self, port, record, crc_endian):
        self.port, self.record, self.crc_endian = port, record, crc_endian
        self.buffer = bytearray()
        self.submitted = self.matched = self.invalid = 0
        self.by_id = {f'0x{cid:03X}': 0 for cid in QUERY_IDS}
        self.first = self.last = None

    def send(self, purpose, raw):
        self.record('serial_write_intent', purpose=purpose, raw=raw.hex(' '))
        if self.port.write(raw) != len(raw):
            raise IOError('partial serial write; delivery uncertain; no automatic retry')
        self.port.flush()
        self.record('serial_submitted', purpose=purpose, raw=raw.hex(' '))

    def receive(self, seconds, expected_id=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            chunk = self.port.read(max(1, min(self.port.in_waiting, 4096)))
            if not chunk:
                continue
            self.record('rx_raw', raw=chunk.hex(' '))
            self.buffer.extend(chunk)
            found = None
            for frame in extract_frames(self.buffer):
                cid, ext, remote, dlc, data = frame
                self.record('can', id=f'0x{cid:03X}', extended=ext, remote=remote,
                            dlc=dlc, data=data.hex(' '))
                if cid == expected_id and not ext and not remote and found is None:
                    found = frame
            if found is not None:
                return found
        return None

    def run(self, cycles, rtr_dlc, interval, timeout):
        self.port.reset_input_buffer()
        self.send('adapter_configuration_only', bms_adapter_config())
        self.receive(0.3)  # Preserve adapter acknowledgments/pre-existing traffic, do not match.
        for cycle in range(1, cycles + 1):
            for cid in QUERY_IDS:
                self.receive(0.01)
                if self.buffer:
                    self.record('discard_prequery_partial', raw=self.buffer.hex(' '))
                    self.buffer.clear()
                sent_at = time.monotonic()
                self.send(f'RTR_0x{cid:03X}', query_packet(cid, rtr_dlc))
                self.submitted += 1
                frame = self.receive(timeout, cid)
                if frame is None:
                    self.record('read_timeout', cycle=cycle, id=f'0x{cid:03X}')
                    return 'READ_TIMEOUT'
                try:
                    decoded = decode_reply(frame, cid, self.crc_endian)
                except ValueError as exc:
                    self.invalid += 1
                    self.record('invalid_reply', cycle=cycle, id=f'0x{cid:03X}', reason=str(exc))
                    return 'INVALID_REPLY'
                now = time.monotonic()
                self.first = now if self.first is None else self.first
                self.last = now
                self.matched += 1
                self.by_id[f'0x{cid:03X}'] += 1
                self.record('read_reply', cycle=cycle, id=f'0x{cid:03X}',
                            host_elapsed_since_send_ms=round((now - sent_at) * 1000, 3), **decoded)
                time.sleep(max(0, interval - (time.monotonic() - sent_at)))
        return 'READ_WINDOW_OK'

    def summary(self, result):
        span = self.last - self.first if self.first is not None else 0
        return dict(result=result, submitted=self.submitted, matched=self.matched,
                    invalid_replies=self.invalid, replies_by_id=self.by_id,
                    reply_span_s=round(span, 6),
                    stable_60s_window_pass=result == 'READ_WINDOW_OK' and span >= 60,
                    note='UART submit is not CAN TX_DONE; no TEC/REC telemetry. '
                         'No transaction sequence number; same-ID late reply attribution is limited.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', default='/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0')
    ap.add_argument('--serial-baud', type=int, choices=[2000000], default=2000000)
    ap.add_argument('--cycles', type=int, default=3)
    ap.add_argument('--rtr-dlc', type=int, choices=[0, 8], default=8)
    ap.add_argument('--crc-endian', choices=['big', 'little'], default='big')
    ap.add_argument('--interval', type=float, default=0.2, help='minimum seconds between queries')
    ap.add_argument('--timeout', type=float, default=0.7)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--log-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'logs/usb-can')
    args = ap.parse_args()
    if not 1 <= args.cycles <= 100 or not 0.2 <= args.interval <= 2 or not 0.1 <= args.timeout <= 3:
        ap.error('cycles must be 1..100; interval 0.2..2s; timeout 0.1..3s')
    print(f'Port={args.port}; UART=2000000; CAN=500000 STD RTR; '
          f'DLC={args.rtr_dlc}; CRC={args.crc_endian}; queries={args.cycles * 5}', flush=True)
    print('ADAPTER_CONFIG:', bms_adapter_config().hex(' '), flush=True)
    for cid in QUERY_IDS:
        print(f'RTR 0x{cid:03X}: {query_packet(cid, args.rtr_dlc).hex(" ")}', flush=True)
    if not args.execute:
        print('DRY RUN: no device opened or data sent; add --execute to run.')
        return 0
    args.log_dir.mkdir(parents=True, exist_ok=True)
    path = args.log_dir / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-bms-read.jsonl')
    print(f'LOG={path}', flush=True)
    start = time.monotonic()
    result, session, exit_code = 'ERROR', None, 3
    with path.open('x') as log:
        def record(event, **fields):
            row = dict(time=datetime.datetime.now().astimezone().isoformat(),
                       elapsed_s=round(time.monotonic() - start, 6), event=event, **fields)
            text = json.dumps(row, ensure_ascii=False, allow_nan=False)
            log.write(text + '\n')
            log.flush()
            if event not in ('rx_raw', 'can'):
                print(text, flush=True)
        record('start', port=args.port, serial_baud=args.serial_baud, can_baud=500000,
               frame_format='STD/RTR requests; STD/DATA replies', cycles=args.cycles,
               rtr_dlc=args.rtr_dlc, crc_endian=args.crc_endian, interval_s=args.interval,
               timeout_s=args.timeout, allowed_ids=[f'0x{x:03X}' for x in QUERY_IDS],
               bms_writes=0, note='Read-only; stop on first timeout/invalid reply; no retries.')
        try:
            import serial
            with serial.Serial(args.port, args.serial_baud, timeout=0.02,
                               write_timeout=1, exclusive=True) as port:
                session = Session(port, record, args.crc_endian)
                result = session.run(args.cycles, args.rtr_dlc, args.interval, args.timeout)
                exit_code = 0 if result == 'READ_WINDOW_OK' else 2
        except KeyboardInterrupt:
            result, exit_code = 'INTERRUPTED', 130
            record('interrupted')
        except Exception as exc:
            result, exit_code = 'ERROR', 3
            record('error', exception=type(exc).__name__, message=str(exc))
        record('summary', **(session.summary(result) if session else dict(
            result=result, submitted=0, matched=0, stable_60s_window_pass=False)))
    print(f'Log saved: {path}', flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
