from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def edit(p, pairs):
    text = p.read_text(encoding="utf-8")
    for old, new, count in pairs:
        if text.count(old) != count:
            raise ValueError(f"{p.name}: unexpected STM32 project layout: {old!r}")
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")


def build(source, output):
    with tempfile.TemporaryDirectory(prefix="pico-fsm7-") as temp:
        work = Path(temp)
        project = work / "project"
        build_dir = work / "build"
        project.mkdir()
        for directory in ("Core", "Drivers", "cmake"):
            shutil.copytree(source / directory, project / directory)
        for name in ("CMakeLists.txt", "startup_stm32g474xx.s", "STM32G474xx_FLASH.ld"):
            shutil.copy2(source / name, project / name)
        shutil.copytree(HERE / "firmware-src", project / "App" / "mf7")
        edit(project / "CMakeLists.txt", [(
            'if(PICO_APP STREQUAL "BoardFsm")',
            '''if(PICO_APP STREQUAL "Fsm7")
    target_sources(PICO_CAN PRIVATE App/mf7/mf7_control.c App/mf7/mf7_app.c App/mf7/mf7_can.c
        App/mf7/upstream/Modules/motor_network.c App/mf7/upstream/Peripheral/rs_motor.c)
    target_include_directories(PICO_CAN PRIVATE App/mf7 App/mf7/upstream)
    target_compile_definitions(PICO_CAN PRIVATE PICO_MOTOR_FSM7=1)
    message(STATUS "PICO real motors: CAN2 / 1 Mbps / seven motors")
elseif(PICO_APP STREQUAL "BoardFsm")''', 1)])
        edit(project / "Core/Src/fdcan.c", [(
            "defined(PICO_CAN_MULTI_TEST) || defined(PICO_CAN_PERIODIC_TX)",
            "defined(PICO_CAN_MULTI_TEST) || defined(PICO_CAN_PERIODIC_TX) || defined(PICO_MOTOR_FSM7)", 2)])
        edit(project / "Core/Src/main.c", [
            ('#if defined(PICO_BOARD_FSM)\n#include "board_fsm_app.h"',
             '#if defined(PICO_MOTOR_FSM7)\n#include "mf7_app.h"\n#elif defined(PICO_BOARD_FSM)\n#include "board_fsm_app.h"', 1),
            ('#if defined(PICO_BOARD_FSM)\n  /* Board FSM',
             '#if defined(PICO_MOTOR_FSM7)\n  /* Mf7App_Init configures CAN2 only. */\n#elif defined(PICO_BOARD_FSM)\n  /* Board FSM', 1),
            ('#if defined(PICO_BOARD_FSM)\n  BoardFsmApp_Init',
             '#if defined(PICO_MOTOR_FSM7)\n  Mf7App_Init(&hlpuart1);\n#elif defined(PICO_BOARD_FSM)\n  BoardFsmApp_Init', 1),
            ('#if defined(PICO_BOARD_FSM)\n    BoardFsmApp_Step',
             '#if defined(PICO_MOTOR_FSM7)\n    Mf7App_Step();\n#elif defined(PICO_BOARD_FSM)\n    BoardFsmApp_Step', 1)])
        edit(project / "Core/Src/stm32g4xx_it.c", [
            ('#if defined(PICO_BOARD_FSM)\n#include "board_fsm_app.h"',
             '#if defined(PICO_MOTOR_FSM7)\n#include "mf7_app.h"\nvoid LPUART1_IRQHandler(void) { Mf7App_UartIrq(); }\n'
             '#elif defined(PICO_BOARD_FSM)\n#include "board_fsm_app.h"', 1)])
        env = os.environ.copy()
        if os.name == "nt":
            bundles = Path(env["LOCALAPPDATA"]) / "stm32cube" / "bundles"
            bins = []
            for tool in ("cmake", "ninja", "gnu-tools-for-stm32"):
                versions = sorted((bundles / tool).glob("*/bin"), reverse=True)
                if versions:
                    bins.append(str(versions[0]))
            env["PATH"] = os.pathsep.join(bins + [env["PATH"]])
        subprocess.run(["cmake", "-S", str(project), "-B", str(build_dir), "-G", "Ninja",
            f"-DCMAKE_TOOLCHAIN_FILE={project / 'cmake/gcc-arm-none-eabi.cmake'}",
            "-DCMAKE_BUILD_TYPE=Release", "-DPICO_APP=Fsm7"], check=True, env=env)
        subprocess.run(["cmake", "--build", str(build_dir)], check=True, env=env)
        output.mkdir(parents=True, exist_ok=True)
        for ext in ("elf", "hex", "bin"):
            shutil.copy2(build_dir / f"PICO_CAN.{ext}", output / f"PICO_MotorFsm7.{ext}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the standalone CAN2 seven-motor FSM. Does not flash.")
    parser.add_argument("--source", type=Path,
        default=HERE.parent / "projects/pico-firmware/firmware/PICO_CAN")
    parser.add_argument("--out", type=Path, default=HERE.parent / "firmware-images")
    args = parser.parse_args()
    build(args.source.resolve(), args.out.resolve())
