#!/usr/bin/env python3
"""Passive 500K CAN listener for Waveshare USB-CAN-A. Never transmits a CAN frame.

Only the adapter configuration is written to the serial port; no RTR/data CAN
query is sent. Use it as an independent bus witness while the G474 is running:
  - if G474 RTR frames appear here, the G474 TX path reaches the bus;
  - if BMS DATA replies appear here but not in the G474 log, the G474 RX path is bad.

The adapter is configured for standard frames, normal mode (it ACKs valid bus
traffic), 500 kbit/s, automatic retransmission disabled. That ACK is intentional
for a witness test and is not a BMS query.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

from usb_can_bms_read import bms_adapter_config
from usb_can_power_probe import extract_frames


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--serial-baud', type=int, default=2000000)
    parser.add_argument('--duration', type=float, default=30.0)
    parser.add_argument('--output', type=Path,
                        help='new JSONL path (default logs/usb-can/<timestamp>-listen-500k.jsonl)')
    parser.add_argument('--execute', action='store_true',
                        help='actually open the serial port; without it, dry-run only')
    args = parser.parse_args(argv)

    if not 0 < args.duration < 3600:
        parser.error('--duration must be between 0 and 3600 seconds')
    config = bms_adapter_config()
    output = args.output
    if output is None:
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output = Path(__file__).resolve().parents[1] / 'logs' / 'usb-can' / f'{stamp}-listen-500k.jsonl'
    print(f'Port={args.port} UART={args.serial_baud} CAN=500000 duration={args.duration}s')
    print('ADAPTER_CONFIG (serial only, no CAN TX):', config.hex(' '))
    if not args.execute:
        print('DRY RUN: nothing opened/sent; add --execute to listen.')
        return 0
    if output.exists():
        parser.error('output already exists; choose a new path')

    import serial

    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    total = 0
    first = last = None
    try:
        with output.open('x', encoding='utf-8') as log:
            def record(event, **fields):
                entry = dict(time=datetime.datetime.now().astimezone().isoformat(),
                             monotonic_s=round(time.monotonic(), 6), event=event, **fields)
                log.write(json.dumps(entry, ensure_ascii=False) + '\n')
                log.flush()
                return entry

            record('start', port=args.port, serial_baud=args.serial_baud, can_baud=500000,
                   duration_s=args.duration, can_tx=0,
                   note='passive listener; adapter config only; no CAN query')
            with serial.Serial(args.port, args.serial_baud, timeout=0.1,
                               write_timeout=1, exclusive=True) as port:
                port.reset_input_buffer()
                port.write(config)
                port.flush()
                record('adapter_config', raw=config.hex(' '))
                buffer = bytearray()
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    chunk = port.read(max(1, min(port.in_waiting, 4096)))
                    if not chunk:
                        continue
                    record('rx_raw', raw=chunk.hex(' '))
                    buffer.extend(chunk)
                    for frame in extract_frames(buffer):
                        cid, extended, remote, dlc, data = frame
                        total += 1
                        key = (cid, extended, remote, dlc)
                        counts[key] = counts.get(key, 0) + 1
                        now = time.monotonic()
                        first = now if first is None else first
                        last = now
                        record('can', id=f'0x{cid:03X}', extended=extended,
                               remote=remote, dlc=dlc, data=data.hex(' '))
            summary = dict(
                result='FRAMES_SEEN' if total else 'NO_FRAMES',
                frames=total,
                can_tx=0,
                first_to_last_s=round(last - first, 6) if first and last else 0.0,
                by_id={f'0x{cid:03X}': sum(n for (i, e, r, d), n in counts.items() if i == cid)
                       for cid, e, r, d in counts},
                by_frame={f'0x{cid:03X}{"/EXT" if e else "/STD"}{"/RTR" if r else "/DATA"}'
                          f"/DLC{d}": n for (cid, e, r, d), n in sorted(counts.items())},
            )
            record('summary', **summary)
    except Exception as exc:  # keep the JSONL start/error evidence, then fail closed
        print(f'ERROR: {type(exc).__name__}: {exc}')
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'Log saved: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
