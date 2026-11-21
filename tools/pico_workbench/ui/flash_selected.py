"""Explicit user-invoked flashing, sharing desktop tool and image selection."""
import argparse
import subprocess
import platform_tools as tools


def main(argv=None):
    parser = argparse.ArgumentParser(description="烧录选定实验；仅在显式调用时写入开发板。")
    parser.add_argument("profile", nargs="?", default="Loopback")
    parser.add_argument("serial", nargs="?")
    args = parser.parse_args(argv)
    tools.validate_mode(args.profile)
    image = tools.image_for(args.profile)
    if not image.is_file():
        parser.error("没有所选实验的固件，请先编译：" + str(image))
    serials = tools.stlink_serials()
    if args.serial:
        if args.serial not in serials:
            parser.error("指定的 ST-LINK 未连接或无法通过虚拟串口识别。")
        serial = args.serial
    elif len(serials) == 1:
        serial = serials[0]
    else:
        parser.error("需要唯一 ST-LINK；请连接开发板或显式指定已连接的序列号。")
    subprocess.run(tools.flash_command(serial, image), env=tools.environment(), check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
