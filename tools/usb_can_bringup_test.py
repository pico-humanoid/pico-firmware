#!/usr/bin/env python3
"""Original G474 CAN bring-up test over Waveshare USB-CAN-A at 1M standard frames.

The firmware waits for a valid 0x321 standard data frame, then transmits 100
0x123 frames. This script sends 100 0x321 triggers (seq 0..99) and records every
0x123 reply. It only configures the adapter and sends the documented trigger
frames; no power-board/BMS parameter write is involved.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

from usb_can_power_probe import adapter_config, extract_frames


def adapter_config_1m_standard():
    p = bytearray(adapter_config(1000000))
    p[4] = 1  # Standard frames; normal mode, automatic retransmission disabled.
    p[-1] = sum(p[2:19]) & 0xFF
    return bytes(p)


def trigger_packet(seq):
    # 0x321, standard data frame, DLC8, tail expected by the external bring-up.
    return bytes((0xAA, 0xC8, 0x21, 0x03, seq & 0xFF,
                  0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x55))


def expected_reply(data):
    return len(data) == 8 and data[1:] == bytes((0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--serial-baud', type=int, default=2000000)
    parser.add_argument('--duration', type=float, default=16.0,
                        help='total listen/send window (default 16s)')
    parser.add_argument('--output', type=Path,
                        help='new JSONL path (default logs/usb-can/<timestamp>-bringup-1m.jsonl)')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    if not 0 < args.duration < 60:
        parser.error('--duration must be between 0 and 60 seconds')
    config = adapter_config_1m_standard()
    output = args.output
    if output is None:
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output = Path(__file__).resolve().parents[1] / 'logs' / 'usb-can' / f'{stamp}-bringup-1m.jsonl'
    print(f'Port={args.port} UART={args.serial_baud} CAN=1000000 fmt=STD duration={args.duration}s')
    print('ADAPTER_CONFIG:', config.hex(' '))
    if not args.execute:
        print('DRY RUN: nothing opened/sent; add --execute to run.')
        return 0
    if output.exists():
        parser.error('output already exists; choose a new path')

    import serial

    output.parent.mkdir(parents=True, exist_ok=True)
    unique_123 = set()
    frames_123 = invalid_123 = triggers_sent = 0
    frames_total = 0
    counts = {}
    first = last = None
    try:
        with output.open('x', encoding='utf-8') as log:
            def record(event, **fields):
                entry = dict(time=datetime.datetime.now().astimezone().isoformat(),
                             monotonic_s=round(time.monotonic(), 6), event=event, **fields)
                log.write(json.dumps(entry, ensure_ascii=False) + '\n')
                log.flush()
                return entry

            record('start', port=args.port, serial_baud=args.serial_baud, can_baud=1000000,
                   frame_format='STD', duration_s=args.duration,
                   note='original bring-up: 0x321 trigger -> 100x 0x123')
            with serial.Serial(args.port, args.serial_baud, timeout=0.02,
                               write_timeout=1, exclusive=True) as port:
                port.reset_input_buffer()
                port.write(config)
                port.flush()
                record('adapter_config', raw=config.hex(' '))
                buffer = bytearray()
                start = time.monotonic()
                next_trigger = start
                while time.monotonic() - start < args.duration:
                    now = time.monotonic()
                    if triggers_sent < 100 and now >= next_trigger:
                        packet = trigger_packet(triggers_sent)
                        if port.write(packet) != len(packet):
                            raise IOError('partial serial write; no retry')
                        port.flush()
                        record('trigger', seq=triggers_sent, raw=packet.hex(' '))
                        triggers_sent += 1
                        next_trigger += 0.1
                    chunk = port.read(max(1, min(port.in_waiting, 4096)))
                    if chunk:
                        record('rx_raw', raw=chunk.hex(' '))
                        buffer.extend(chunk)
                        for frame in extract_frames(buffer):
                            cid, extended, remote, dlc, data = frame
                            frames_total += 1
                            key = (cid, extended, remote, dlc)
                            counts[key] = counts.get(key, 0) + 1
                            t = time.monotonic()
                            first = t if first is None else first
                            last = t
                            record('can', id=f'0x{cid:03X}', extended=extended,
                                   remote=remote, dlc=dlc, data=data.hex(' '))
                            if cid == 0x123 and not extended and not remote and dlc == 8:
                                if expected_reply(data):
                                    frames_123 += 1
                                    unique_123.add(data[0])
                                else:
                                    invalid_123 += 1
                summary = dict(
                    result='BRINGUP_TX_OK' if frames_123 and len(unique_123) >= 100 else
                           'BRINGUP_PARTIAL' if frames_123 else 'NO_0x123_FRAMES',
                    triggers_sent=triggers_sent,
                    frames_total=frames_total,
                    frames_0x123=frames_123,
                    unique_0x123=len(unique_123),
                    invalid_0x123=invalid_123,
                    by_frame={f'0x{cid:03X}{"/EXT" if e else "/STD"}{"/RTR" if r else "/DATA"}/DLC{d}': n
                              for (cid, e, r, d), n in sorted(counts.items())},
                )
                record('summary', **summary)
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}')
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'Log saved: {output}')
    return 0 if summary['result'] == 'BRINGUP_TX_OK' else 1


if __name__ == '__main__':
    raise SystemExit(main())
