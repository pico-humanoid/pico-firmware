"""Compile the built-in experiments and local CAN routing matrix; never flash hardware."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys

WORKBENCH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKBENCH / "ui"))
import catalog
from runtime_paths import firmware_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    profiles = list(catalog._all_builtins())
    source = firmware_root()

    def add(name, options):
        profiles.append(dict(id=name, project_dir=str(source), cmake_options=options,
                             build_type="Debug", toolchain="cmake/gcc-arm-none-eabi.cmake"))

    for app in ("BMS", "Power", "Dual"):
        for channel in (1, 2, 3):
            add(f"{app}-CAN{channel}-merge", dict(PICO_APP=app, PICO_CAN_CHANNEL=channel,
                                                PICO_DEVICE_BITRATE=500000))
    for app in ("PinLoop", "Listen", "CanMultiBench", "MotorDualFault"):
        add(app + "-merge", dict(PICO_APP=app))
    for before, after in ((1000000, 500000), (500000, 1000000)):
        add(f"PowerBaud-{before}-to-{after}", dict(PICO_APP="PowerBaud",
            PICO_DEVICE_BITRATE=before, PICO_POWER_BAUD_TARGET=after))

    def build(profile):
        name = profile["id"]
        project = Path(profile["project_dir"])
        destination = folder / name
        command = ["cmake", "-U", "PICO_*", "-S", str(project), "-B", str(destination),
                   "-G", "Ninja", "-DCMAKE_TOOLCHAIN_FILE=" + str(project / profile["toolchain"]),
                   "-DCMAKE_BUILD_TYPE=" + profile["build_type"]]
        options = dict(profile["cmake_options"])
        if profile.get("base_mode") in ("Loopback", "External"):
            options["PICO_EXTERNAL_CAN"] = "ON" if profile["base_mode"] == "External" else "OFF"
        command.extend(f"-D{key}={value}" for key, value in options.items())
        with (folder / (name + ".log")).open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode == 0:
                result = subprocess.run(["cmake", "--build", str(destination), "-j", "3"],
                                        stdout=log, stderr=subprocess.STDOUT)
        print(name, "PASS" if result.returncode == 0 else "FAIL", flush=True)
        return dict(id=name, returncode=result.returncode, options=options)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(build, profiles))
    (folder / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    failures = sum(result["returncode"] != 0 for result in results)
    print("TOTAL", len(results), "FAIL", failures)
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
