#!/usr/bin/env python3
"""Robot14 只读反馈探针（不使能、不写参数、不复位）。

用法：
    python3 tools/robot14_feedback_probe.py --port /dev/ttyACM0 --seconds 20

只发送 HELLO / PING，接收 INFO / NODE / STATE，输出每台电机的反馈新鲜度、
位置/速度/温度/故障字，以及 CAN1/2/3 计数。原始字节与逐节点 CSV 会保存在
logs/<日期>/robot14-probe-*/ 下，便于复核。

安全边界：本脚本没有使能、目标、写入、停机命令路径；不能替代硬件急停。
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'pico_workbench' / 'ui'))
sys.path.insert(0, str(ROOT / 'tools' / 'pico_workbench' / 'ui' / 'vendor'))

from robot14_model import Controller, Parser, INFO, PHASES  # noqa: E402

DEBUG = 0x8F
REASONS = ('UNKNOWN', 'FEEDBACK_AGE', 'COMMAND_AGE', 'EFFORT', 'HANDSHAKE',
           'MOTOR_FAULT', 'SET_REJECT', 'TRANSPORT', 'REQUEST', 'CAN_FATAL',
           'NEW_SESSION', 'HOST_LEASE')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--seconds', type=float, default=20.0)
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    import serial

    folder = Path(args.out) if args.out else (
        ROOT / 'logs' / datetime.now().strftime('%Y-%m-%d') /
        ('robot14-probe-' + datetime.now().strftime('%H%M%S_%f')))
    folder.mkdir(parents=True, exist_ok=True)

    dev = serial.Serial(port=None, baudrate=115200, timeout=.005, write_timeout=.025)
    dev.dtr = False
    dev.rts = False
    dev.port = args.port
    dev.open()  # 与工作台一致：打开时不脉冲 DTR/RTS、不复位

    core = Controller(time.monotonic())
    parser = Parser()
    info = None
    nodes = {}
    last_state = None
    counts = {}
    debug_frames = []
    started = time.monotonic()
    try:
        with (folder / 'wire.bin').open('wb') as rawlog, \
             (folder / 'nodes.csv').open('w', newline='', encoding='utf-8') as csvout, \
             (folder / 'commands.jsonl').open('w', encoding='utf-8') as cmdlog:
            writer = csv.writer(csvout)
            writer.writerow(('host_ms', 'board_ms', 'id', 'bus', 'model', 'phase', 'flags',
                             'p_rad', 'v_rad_s', 'torque_Nm', 'temp_C', 'fb_age_ms',
                             'p_age_ms', 'v_age_ms', 'faults', 'fault_word', 'warning_word'))
            while time.monotonic() - started < args.seconds:
                now = time.monotonic()
                data = dev.read(4096)
                if data:
                    rawlog.write(data)
                    for frame in parser.feed(data, now):
                        if frame[0] == DEBUG:
                            debug_frames.append((frame[1], frame[3]))
                        core.receive(frame, now)
                core.step(now)
                for ev in core.events:
                    kind, value = ev
                    if kind == 'info':
                        info = value
                    elif kind == 'state':
                        last_state = value
                    elif kind == 'node':
                        n = value
                        nodes[n['id']] = n
                        counts[n['id']] = counts.get(n['id'], 0) + 1
                        writer.writerow((round(now - started, 3), n['stamp'], n['id'], n['bus'],
                                         n['model'], n['phase'], n['flags'], n['p'], n['v'],
                                         n['t'], n['temp'], n['fb_age'], n['p_age'], n['v_age'],
                                         n['faults'], n['fault_word'], n['warning_word']))
                core.events.clear()
                for wire in core.outbox:
                    cmdlog.write(json.dumps({'host_monotonic': now, 'type': wire[3],
                                             'wire_hex': wire.hex()}) + '\n')
                    dev.write(wire)
                core.outbox.clear()
                if not core.token and now - started > 3.0:
                    print('3 秒内未收到匹配 Robot14 INFO；板端可能是旧固件或串口不对。')
                    break
                if not info and parser.bad > 50:
                    print('收到大量无法解析字节，可能不是 Robot14 二进制会话。')
                    break
    finally:
        dev.close()

    print(json.dumps({'folder': str(folder), 'info': info, 'bad_frames': parser.bad,
                      'nodes': counts}, ensure_ascii=False, indent=2))
    print('\n每台电机最后一次遥测（— 表示未收到）：')
    header = ('ID', 'bus', 'model', 'phase', 'flags', 'p_rad', 'v_rad_s', 'tau_Nm', 'T_C',
              'p_age', 'v_age', 'fault', 'warn')
    print('{:>3} {:>3} {:>6} {:>12} {:>5} {:>9} {:>9} {:>8} {:>6} {:>6} {:>6} {:>6} {:>6}'.format(*header))
    for motor_id in range(1, 15):
        n = nodes.get(motor_id)
        if n is None:
            print('{:>3} {:>3} {:>6} {:>12}'.format(motor_id, 2 if motor_id <= 7 else 3,
                                                    'RS00' if motor_id in (1, 2, 3, 8, 9, 10) else 'RS10P',
                                                    '无遥测'))
            continue
        print('{:>3} {:>3} {:>6} {:>12} {:>5} {:>9.3f} {:>9.3f} {:>8.3f} {:>6.1f} {:>6} {:>6} {:>6} {:>6}'.format(
            n['id'], n['bus'], n['model'], n['phase'], n['flags'], n['p'], n['v'], n['t'],
            n['temp'], n['p_age'], n['v_age'], n['faults'], n['warning_word']))
    if last_state:
        can = last_state['can']
        print('\n板端 HEALTH：latched={} stop_pending={} rejected={} overruns={} bad={} '
              'BMS={}({}) 电源={}({})'.format(
                  last_state['latched'], last_state['stop_pending'], last_state['rejected'],
                  last_state['overruns'], last_state['bad_frames'],
                  '有效' if last_state['bms_valid'] else '无效', last_state['bms_mv'],
                  '有效' if last_state['power_valid'] else '无效', last_state['power_mv']))
        for i, label in enumerate(('CAN1', 'CAN2', 'CAN3')):
            print('  {} rx={} tx={} bus_off={}'.format(label, *can[i]))
    for stamp, d in debug_frames:
        if len(d) >= 10:
            reason = REASONS[d[1]] if d[1] < len(REASONS) else str(d[1])
            age = d[4] | d[5] << 8
            cmd_age = d[6] | d[7] << 8
            eff = d[8] | d[9] << 8
            eff = eff - 65536 if eff >= 32768 else eff
            phase = '—' if d[3] == 0xFF else PHASES[d[3]] if d[3] < len(PHASES) else str(d[3])
            kind = '停机' if d[0] == 1 else 'SET拒绝'
            print('板端调试帧 [%s] stamp=%d reason=%s motor=ID%d phase=%s fb_age=%d cmd_age=%d effort=%dmN·m' % (
                kind, stamp, reason, d[2], phase, age, cmd_age, eff))
    print('\n证据目录：' + str(folder))


if __name__ == '__main__':
    main()
