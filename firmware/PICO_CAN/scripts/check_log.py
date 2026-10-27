"""Check a real board CSV capture; no third-party Python packages required."""
import argparse
import csv
import io
import json
from pathlib import Path


def check(text, external=False):
    errors = []
    events = {name: [] for name in ("TX_SUBMIT", "TX_DONE", "RX")}
    rx_id = 0x321 if external else 0x123
    summary = None
    for line in text.splitlines():
        if line.startswith("# RESULT="):
            summary = dict(item.split("=", 1) for item in line[2:].split() if "=" in item)
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines or lines[0] != "t_ms,event,format,id,dlc,data":
        return {"pass": False, "errors": ["Missing CSV header. Open capture and reset the board."]}
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        try:
            kind = row["event"]
            if kind not in events:
                errors.append("Unknown event: " + kind)
                continue
            raw = bytes.fromhex(row["data"])
            if len(raw) != 8 or int(row["dlc"]) != 8 or row["format"] != "STD":
                raise ValueError("Expected an 8-byte standard frame")
            if int(row["id"], 0) != (rx_id if kind == "RX" else 0x123):
                raise ValueError("Unexpected CAN identifier")
            tail = bytes.fromhex("88 77 66 55 44 33 22" if external and kind == "RX" else "22 33 44 55 66 77 88")
            if raw[1:] != tail or raw[0] >= 100:
                raise ValueError("Unexpected payload")
            events[kind].append((raw[0], int(row["t_ms"])))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    counts = {}
    for kind, frames in events.items():
        seq = [value for value, _ in frames]
        missing = sorted(set(range(100)) - set(seq))
        duplicates = sorted({value for value in seq if seq.count(value) > 1})
        counts[kind] = {"count": len(seq), "missing": missing, "duplicates": duplicates}
        if len(seq) != 100 or missing or duplicates:
            errors.append(f"{kind}: expected each sequence 0..99 exactly once")
    submitted = events["TX_SUBMIT"]
    if len(submitted) == 100 and any(b[1] - a[1] < 100 for a, b in zip(submitted, submitted[1:])):
        errors.append("TX_SUBMIT spacing is shorter than 100 ms")
    if summary is None or summary.get("RESULT") != "PASS":
        errors.append("Missing board PASS summary")
    else:
        expected = {"tx_submit":100,"tx_done":100,"rx_unique":100,"rx_missing":0,"rx_duplicate":0,
                    "rx_invalid":0,"tx_submit_failed":0,"rx_fifo_lost_events":0,"rx_queue_dropped":0,
                    "rx_read_failed":0,"tx_event_lost_events":0,"bus_off_events":0,"fatal":0,"tec":0,"rec":0}
        for name, value in expected.items():
            if summary.get(name) != str(value):
                errors.append("Unexpected summary field: " + name)
    return {"pass": not errors, "mode":"External" if external else "Loopback", "events":counts, "errors":errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--external", action="store_true")
    args = parser.parse_args()
    result = check(args.log.read_text(encoding="utf-8-sig"), args.external)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["pass"] else 1)
