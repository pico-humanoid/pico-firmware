"""VS Code build entry matching the selected native desktop experiment."""
import sys
import time
from engine import Manager


def main(mode=None):
    manager = Manager()
    job = manager.start("build", mode or sys.argv[1])
    cursor = 0
    try:
        while True:
            snapshot = job.snapshot(True, cursor)
            for line in snapshot["lines"]:
                print(line["text"], flush=True)
            cursor = snapshot["sequence"]
            if snapshot["status"] != "running":
                return 0 if snapshot["status"] == "pass" else 1
            time.sleep(0.15)
    except KeyboardInterrupt:
        manager.stop(job.id)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
