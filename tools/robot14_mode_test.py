#!/usr/bin/env python3
"""Robot14 逐台使能 + 力矩/位置/速度反馈检查（空载、小幅度、一次一台）。

安全边界：
- 只使用 Robot14 二进制会话的公开命令（SELECT/ENABLE/SET/DISABLE/STOP）；
- 每台使能时长 15 s，位置 ±0.05 rad、速度 ±0.2 rad/s、力矩 ±0.1 N·m（带 Kd 阻尼）；
- 任一阶段出现 FAULT/锁存/遥测中断/超预期位移立即停止；
- 不修改 ID、零点、波特率，不发送保存命令，不使能第二台。

用法：
    python3 tools/robot14_mode_test.py --port /dev/ttyACM0 --ids 1-7
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

from robot14_model import Controller, Parser, SELECT, fresh  # noqa: E402

ENABLE_SECONDS = 15.0
MAX_TRAVEL = 0.8       # rad from the position at enable
MAX_SPEED = 1.5        # rad/s


def parse_ids(text):
    out = []
    for part in text.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-')
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def mean(values):
    return sum(values) / len(values) if values else float('nan')


class Rig:
    def __init__(self, port, outdir):
        import serial
        self.folder = Path(outdir)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.dev = serial.Serial(port=None, baudrate=115200, timeout=.005,
                                 write_timeout=.025)
        self.dev.dtr = False
        self.dev.rts = False
        self.dev.port = port
        self.dev.open()
        self.core = Controller(time.monotonic())
        self.parser = Parser()
        self.csvfile = (self.folder / 'samples.csv').open('w', newline='', encoding='utf-8')
        self.writer = csv.writer(self.csvfile)
        self.writer.writerow(('t', 'id', 'label', 'phase', 'p', 'v', 't', 'temp',
                              'cmd_p', 'cmd_v', 'cmd_t', 'cmd_kp', 'cmd_kd',
                              'flags', 'fb_age'))
        self.cmdlog = (self.folder / 'commands.jsonl').open('w', encoding='utf-8')
        self.raw = (self.folder / 'wire.bin').open('wb')
        self.states = []
        self.cmd = (0.0, 0.0, 0.0, 0.0, 0.0)
        self.label = 'idle'
        self.current_id = None
        self.torque = 0.15
        self.vel_ff = 0.0
        self.started = time.monotonic()
        self.last_sample = 0.0
        self.phase = {}
        self.abort_reason = None

    def close(self):
        try:
            self.dev.close()
        finally:
            self.csvfile.close()
            self.cmdlog.close()
            self.raw.close()

    def now(self):
        return time.monotonic()

    def pump(self):
        now = self.now()
        self.core.ui_ms = now
        data = self.dev.read(4096)
        if data:
            self.raw.write(data)
            for frame in self.parser.feed(data, now):
                self.core.receive(frame, now)
        self.core.step(now)
        for kind, value in self.core.events:
            if kind == 'state':
                self.states.append(value)
                if value['latched']:
                    self.abort_reason = 'board latched stop'
        self.core.events.clear()
        for wire in self.core.outbox:
            self.cmdlog.write(json.dumps({'t': now - self.started, 'type': wire[3],
                                          'hex': wire.hex()}) + '\n')
            self.dev.write(wire)
        self.core.outbox.clear()
        self.sample(now)
        return now

    def node(self):
        return self.core.nodes.get(self.current_id) if self.current_id else None

    def sample(self, now):
        n = self.node()
        if not n or now - self.last_sample < .05:
            return
        self.last_sample = now
        self.writer.writerow((round(now - self.started, 3), n['id'], self.label,
                              n['phase'], round(n['p'], 4), round(n['v'], 4),
                              round(n['t'], 4), n['temp'], *self.cmd,
                              n['flags'], n['fb_age']))
        self.phase.setdefault(self.label, []).append(
            (n['p'], n['v'], n['t'], n['temp']))

    def wait(self, predicate, timeout, what):
        deadline = self.now() + timeout
        while self.now() < deadline:
            now = self.pump()
            if self.abort_reason:
                raise RuntimeError(self.abort_reason)
            if self.core.latched:
                raise RuntimeError('board latched stop')
            if predicate(now):
                return True
        raise TimeoutError(what)

    def hold(self, label, cmd, seconds, guard=None):
        self.label, self.cmd = label, cmd
        self.core.apply(self.current_id, cmd, self.now())
        end = self.now() + seconds
        while self.now() < end:
            now = self.pump()
            if self.abort_reason:
                raise RuntimeError(self.abort_reason)
            if self.core.latched:
                raise RuntimeError('board latched stop')
            n = self.node()
            if not n:
                raise RuntimeError('节点遥测丢失')
            if n['phase'] == 'FAULT':
                raise RuntimeError('motor phase FAULT')
            if guard is not None and abs(n['p'] - guard) > MAX_TRAVEL:
                raise RuntimeError('位移超出预期 %.2f rad' % MAX_TRAVEL)
            if abs(n['v']) > MAX_SPEED:
                raise RuntimeError('速度超出预期 %.2f rad/s' % MAX_SPEED)

    def wait_token(self):
        self.wait(lambda n: bool(self.core.token), 4.0, '未收到 Robot14 INFO')
        self.wait(lambda n: any(fresh(x, n) and x['phase'] == 'IDLE'
                                for x in self.core.nodes.values()), 4.0,
                  '未收到新鲜 IDLE 反馈')

    def run_motor(self, motor_id):
        self.current_id = motor_id
        core = self.core
        self.wait(lambda n: (core.nodes.get(motor_id) is not None and
                             fresh(core.nodes[motor_id], n) and
                             core.nodes[motor_id]['phase'] == 'IDLE' and
                             abs(core.nodes[motor_id]['v']) <= .1),
                  6.0, 'ID%d 无新鲜静止 IDLE 反馈' % motor_id)
        core.send(SELECT, bytes([motor_id]))
        p0 = core.nodes[motor_id]['p']
        t_enable = self.now()
        core.enable(motor_id, ENABLE_SECONDS, self.now())
        try:
            self.wait(lambda n: core.nodes.get(motor_id, {}).get('phase') == 'ACTIVE',
                      5.0, 'ID%d 未进入 ACTIVE' % motor_id)
        except Exception:
            self.best_effort_disable()
            raise
        enable_s = self.now() - t_enable
        self.phase.clear()

        self.hold('zero', (p0, 0, 0, 0, 0), .4, guard=p0)
        self.hold('torque+', (p0, 0, self.torque, 0, .8), .7, guard=p0)
        self.hold('torque-', (p0, 0, -self.torque, 0, .8), .7, guard=p0)
        self.hold('zero2', (p0, 0, 0, 0, 0), .4, guard=p0)
        pos = self.node()['p']
        self.hold('pos+', (pos + .15, 0, 0, 2.5, .2), 1.5, guard=p0)
        self.hold('pos-', (pos, 0, 0, 2.5, .2), 1.5, guard=p0)
        self.hold('zero3', (pos, 0, 0, 0, 0), .8, guard=p0)
        self.hold('vel+', (pos, .30, self.vel_ff, 0, 1.0), 1.5, guard=p0)
        self.hold('vel-', (pos, -.30, -self.vel_ff, 0, 1.0), 1.5, guard=p0)
        self.hold('zero4', (pos, 0, 0, 0, 0), .4, guard=p0)
        core.disable(motor_id, self.now())
        self.wait(lambda n: core.nodes.get(motor_id, {}).get('phase') == 'IDLE',
                  4.0, 'ID%d 未回到 IDLE' % motor_id)

        def tail(label):
            return self.phase.get(label, [])[-10:]

        def stat(label, idx):
            return [r[idx] for r in self.phase.get(label, [])]

        def tail_mean(label, idx):
            return mean([r[idx] for r in tail(label)])

        torque_up, torque_dn = stat('torque+', 2), stat('torque-', 2)
        torque_up_peak = max(torque_up) if torque_up else 0.0
        torque_dn_peak = min(torque_dn) if torque_dn else 0.0
        vel_up, vel_dn = stat('vel+', 1), stat('vel-', 1)
        pos_up, pos_dn = stat('pos+', 0), stat('pos-', 0)
        temp = stat('zero', 3) + stat('torque+', 3) + stat('vel+', 3)
        rec = {
            'id': motor_id, 'enable_s': round(enable_s, 3), 'p0': round(p0, 4),
            'torque_up_t': round(torque_up_peak, 4),
            'torque_dn_t': round(torque_dn_peak, 4),
            'torque_up_v': round(tail_mean('torque+', 1), 4),
            'torque_dn_v': round(tail_mean('torque-', 1), 4),
            'vel_up': round(tail_mean('vel+', 1), 4),
            'vel_dn': round(tail_mean('vel-', 1), 4),
            'pos_cmd': round(pos + .15, 4),
            'pos_reached': round(pos_up[-1], 4) if pos_up else None,
            'pos_err': round(abs(pos_up[-1] - (pos + .15)), 4) if pos_up else None,
            'pos_back': round(pos_dn[-1], 4) if pos_dn else None,
            'pos_back_err': round(abs(pos_dn[-1] - pos), 4) if pos_dn else None,
            'temp_max': round(max(temp), 1) if temp else None,
            'faults': core.nodes.get(motor_id, {}).get('faults', 0),
            'stopped': core.nodes.get(motor_id, {}).get('phase') == 'IDLE',
            'samples': {k: len(v) for k, v in self.phase.items()},
        }
        rec['pass'] = bool(
            rec['stopped'] and rec['faults'] == 0 and
            rec['pos_err'] is not None and rec['pos_err'] < .08 and
            rec['pos_back_err'] is not None and rec['pos_back_err'] < .08 and
            rec['torque_up_t'] > .3 and rec['torque_dn_t'] < -.3 and
            rec['torque_up_v'] > .02 and rec['torque_dn_v'] < -.02 and
            abs(rec['vel_up'] - .3) < .1 and abs(rec['vel_dn'] + .3) < .1)
        return rec

    def best_effort_disable(self):
        try:
            if self.current_id in self.core.targets:
                self.core.disable(self.current_id, self.now())
                end = self.now() + 2.0
                while self.now() < end:
                    self.pump()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--ids', default='1-7')
    ap.add_argument('--torque', type=float, default=0.15)
    ap.add_argument('--vel-ff', type=float, default=0.0)
    ap.add_argument('--out', default='')
    args = ap.parse_args()
    ids = parse_ids(args.ids)
    folder = Path(args.out) if args.out else (
        ROOT / 'logs' / datetime.now().strftime('%Y-%m-%d') /
        ('robot14-mode-' + datetime.now().strftime('%H%M%S_%f')))
    if not 0 < args.torque <= 0.8:
        raise SystemExit('torque 必须在 (0, 0.8] N·m 内')
    if not 0 <= args.vel_ff <= 0.5:
        raise SystemExit('vel-ff 必须在 [0, 0.5] N·m 内')
    rig = Rig(args.port, folder)
    rig.torque = args.torque
    rig.vel_ff = args.vel_ff
    results = []
    aborted = None
    try:
        rig.wait_token()
        for motor_id in ids:
            rec = rig.run_motor(motor_id)
            results.append(rec)
            print('ID%d: enable=%.2fs pos_err=%s vel=%s/%s pass=%s' % (
                motor_id, rec['enable_s'], rec['pos_err'], rec['vel_up'],
                rec['vel_dn'], rec['pass']))
    except Exception as exc:
        aborted = str(exc)
        print('ABORT:', exc)
        try:
            rig.core.stop('脚本异常中止')
            end = rig.now() + 1.0
            while rig.now() < end:
                rig.pump()
        except Exception:
            pass
    finally:
        try:
            (rig.folder / 'result.json').write_text(
                json.dumps({'ids': ids, 'results': results, 'abort': aborted,
                            'latched': rig.core.latched},
                           ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        rig.close()
        print('证据目录:', rig.folder)


if __name__ == '__main__':
    main()
