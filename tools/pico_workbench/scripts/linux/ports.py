"""Find the ST-LINK VCP and the previously used CH340 USB-CAN adapter."""
from serial.tools import list_ports


def choose_port(kind, explicit=None):
    if explicit:
        return explicit
    matches = []
    for port in list_ports.comports():
        if kind == "board" and port.vid == 0x0483 and port.pid in {0x3748, 0x374B, 0x374D, 0x374E, 0x374F, 0x3752, 0x3753, 0x3754}:
            matches.append(port.device)
        elif kind == "usbcan" and port.vid == 0x1A86 and port.pid == 0x7523:
            matches.append(port.device)
    if len(matches) != 1:
        listing = "; ".join(f"{p.device}: {p.description}" for p in list_ports.comports()) or "无串口"
        raise RuntimeError(f"需要恰好一个 {kind} 设备，当前找到 {len(matches)} 个。{listing}。可使用 --port 指定端口。")
    return matches[0]
