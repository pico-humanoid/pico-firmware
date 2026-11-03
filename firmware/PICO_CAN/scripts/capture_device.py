#!/usr/bin/env python3
"""Capture ST-LINK board logs, NOT the USB-CAN-A adapter protocol.

No bytes are written to the serial port. Successful capture is not a device PASS.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import time

import serial


def positive(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="ST-LINK VCP, not USB-CAN-A")
    parser.add_argument("--output", required=True, type=Path, help="new raw log file; never overwrite")
    parser.add_argument("--duration", type=positive, default=60.0, help="capture seconds (default 60)")
    parser.add_argument("--idle-timeout", type=positive, default=10.0, help="seconds without bytes (default 10)")
    parser.add_argument("--label", default="device-read", help="firmware/configuration label")
    args = parser.parse_args(argv)
    meta_path = Path(str(args.output) + ".json")
    if args.output.exists() or meta_path.exists():
        parser.error("output or metadata already exists; choose a new name")
    meta = {"port": args.port, "baud": 115200, "format": "8N1", "label": args.label,
            "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "capture_only_not_device_pass": True, "bytes": 0}
    exit_code = 1
    reason = "error"
    try:
        with args.output.open("xb") as output, meta_path.open("x", encoding="utf-8") as metadata:
            try:
                with serial.Serial(args.port, baudrate=115200, bytesize=serial.EIGHTBITS,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                   timeout=0.1, xonxoff=False, rtscts=False, dsrdtr=False) as port:
                    start = last_rx = time.monotonic()
                    print(f"READY {args.port}; reset the board now", flush=True)
                    while True:
                        now = time.monotonic()
                        if now - start >= args.duration:
                            reason, exit_code = "duration_complete", 0
                            break
                        if now - last_rx >= args.idle_timeout:
                            reason = "idle_timeout"
                            break
                        data = port.read(min(max(port.in_waiting, 1), 4096))
                        if data:
                            output.write(data)
                            output.flush()
                            meta["bytes"] += len(data)
                            last_rx = time.monotonic()
            except KeyboardInterrupt:
                reason, exit_code = "interrupted", 130
            except (serial.SerialException, OSError) as exc:
                meta["error"] = str(exc)
                reason = "serial_or_io_error"
            finally:
                meta["reason"] = reason
                meta["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                json.dump(meta, metadata, ensure_ascii=False, indent=2)
                metadata.write("\n")
    except OSError as exc:
        print(f"Cannot create capture files: {exc}", file=sys.stderr)
        return 1
    print(f"Capture {reason}: {meta['bytes']} bytes saved to {args.output}; NOT a device PASS")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
