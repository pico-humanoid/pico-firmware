#!/usr/bin/env python3
"""Robot14 七台同时使能 + 力矩/位置/速度整组测试（空载、小幅度）。

- 逐台显式使能，全部进入 ACTIVE 后开始；
- 每个阶段用一帧批量 SET 同时更新 7 台目标（板端逐台校验 ACTIVE/租约/2 N·m）；
- 任一电机 FAULT、板端锁存、位移 > 0.8 rad、速度 > 1.5 rad/s 立即中止；
- 不修改 ID、零点、波特率，不保存参数。

用法：
    python3 tools/robot14_multi_test.py --port /dev/ttyACM0 --torque 0.6 --vel-ff 0.15
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

from robot14_model import Controller, Parser, fresh, target  # noqa: E402

DURATION = 20.0
MAX_TRAVEL = 1.0
MAX_SPEED = 2.0


def parse_ids(text):
    out = []
    for part in text.split(','):
        a, b = (part.split('-') + [None])[:2] if '-' in part else (part, None)
        if b:
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


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
        self.cmd = {}
        self.label = 'idle'
        self.started = time.monotonic()
        self.last_sample = 0.0
        self.phase = {}
        self.abort_reason = None
        self.base = {}
        self.hits = {}

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
            elif kind == 'message':
                self.host_msg = value
                print('HOST:', value)
        self.core.events.clear()
        for wire in self.core.outbox:
            self.cmdlog.write(json.dumps({'t': now - self.started, 'type': wire[3],
                                          'hex': wire.hex()}) + '\n')
            self.dev.write(wire)
        self.core.outbox.clear()
        self.sample(now)
        return now

    def sample(self, now):
        if now - self.last_sample < .05:
            return
        self.last_sample = now
        for mid, n in sorted(self.core.nodes.items()):
            self.writer.writerow((round(now - self.started, 3), mid, self.label,
                                  n['phase'], round(n['p'], 4), round(n['v'], 4),
                                  round(n['t'], 4), n['temp'],
                                  *self.cmd.get(mid, (0, 0, 0, 0, 0)),
                                  n['flags'], n['fb_age']))
            self.phase.setdefault(self.label, {}).setdefault(mid, []).append(
                (n['p'], n['v'], n['t'], n['temp']))

    def wait(self, predicate, timeout, what):
        deadline = self.now() + timeout
        while self.now() < deadline:
            self.pump()
            if self.abort_reason:
                raise RuntimeError(self.abort_reason)
            if self.core.latched:
                raise RuntimeError('board latched stop')
            if predicate():
                return True
        raise TimeoutError(what)

    def set_all(self, builder):
        """builder(mid, node) -> (p, v, t, kp, kd) physical units."""
        payload = {}
        for mid in self.ids:
            n = self.core.nodes.get(mid)
            if not n:
                raise RuntimeError('ID%d 遥测缺失' % mid)
            payload[mid] = target(builder(mid, n))
        self.cmd = payload
        self.core.targets = dict(payload)
        self.core.next_set = 0.0

    def hold(self, label, seconds, builder):
        self.label = label
        self.set_all(builder)
        end = self.now() + seconds
        while self.now() < end:
            self.pump()
            if self.abort_reason:
                raise RuntimeError(self.abort_reason)
            if self.core.latched:
                raise RuntimeError('board latched stop')
            for mid in self.ids:
                n = self.core.nodes.get(mid)
                if not n:
                    continue
                if n['phase'] == 'FAULT':
                    raise RuntimeError('ID%d FAULT' % mid)
                over = (abs(n['p'] - self.base[mid]) > MAX_TRAVEL or
                        abs(n['v']) > MAX_SPEED)
                self.hits[mid] = self.hits.get(mid, 0) + 1 if over else 0
                if self.hits[mid] >= 10:
                    self.hits[mid] = 0
                    raise RuntimeError('ID%d 位移/速度持续超限' % mid)

    def wait_token(self):
        self.wait(lambda: bool(self.core.token), 4.0, '未收到 Robot14 INFO')
        self.wait(lambda: all(fresh(self.core.nodes.get(m), self.now()) and
                              self.core.nodes[m]['phase'] == 'IDLE'
                              for m in self.ids), 6.0, '7 台未全部报告新鲜 IDLE 反馈')

    def run(self, ids, torque, vel_ff, pos_step, hold_only=False, mode='all'):
        self.ids = ids
        core = self.core
        active_at = self.now()
        queued = []
        for mid in ids:
            try:
                self.wait(lambda: (core.nodes.get(mid) is not None and
                                   fresh(core.nodes[mid], self.now()) and
                                   core.nodes[mid]['phase'] == 'IDLE' and
                                   abs(core.nodes[mid]['v']) <= .1),
                          3.0, 'ID%d 无新鲜静止 IDLE 读数' % mid)
                core.enable(mid, DURATION, self.now())
                queued.append(mid)
            except Exception as exc:
                print('ID%d 未使能：%s' % (mid, exc))
        if not queued:
            raise RuntimeError('没有任何电机成功入队使能')
        self.ids = queued
        try:
            self.wait(lambda: all(core.nodes.get(m, {}).get('phase') == 'ACTIVE'
                                  and core.nodes[m]['flags'] & 4 for m in queued),
                      8.0, '并非全部进入 ACTIVE')
        except Exception:
            self.disable_all()
            raise
        enable_s = self.now() - active_at
        # ACTIVE 时的位置来自类型 2（±12.57）；IDLE 的 0x7019 是多圈累计值，
        # 可能超过命令范围，不能直接用于目标或位移判据。
        self.base = {m: core.nodes[m]['p'] for m in ids}
        print('全部 ACTIVE，用时 %.2fs' % enable_s)

        def zero(mid, n):
            return (n['p'], 0, 0, 0, 0)

        if hold_only:
            self.hold('zero', 8.0, zero)
            self.disable_all()
            self.wait(lambda: all(self.core.nodes.get(m, {}).get('phase') == 'IDLE'
                                  for m in ids), 5.0, '并非全部回到 IDLE')
            return enable_s

        def torq(sign):
            return lambda mid, n: (n['p'], 0, sign * torque, 0, .8)

        if mode in ('all', 'zero'):
            self.hold('zero', .5, zero)
        if mode in ('all', 'torque'):
            self.hold('torque+', .8, torq(+1))
            self.hold('torque-', .8, torq(-1))
            self.hold('zero2', .5, zero)
        if mode in ('all', 'position'):
            # Wait for the group to settle before sampling the position base;
            # a moving/stale base makes the board reject the position batch.
            try:
                self.wait(lambda: all(abs(self.core.nodes[m]['v']) <= .05
                                      for m in self.ids), 2.0, '未静止')
            except Exception:
                pass
            self.pos_base = {m: self.core.nodes[m]['p'] for m in self.ids}
            self.pos_dir = {m: (1 if self.pos_base[m] <= 11.5 else -1) for m in self.ids}
            self.hold('pos+', 1.5,
                      lambda mid, n: (self.pos_base[mid] +
                                      self.pos_dir[mid] * pos_step, 0, 0, 1.0, .2))
            self.hold('pos-', 1.5,
                      lambda mid, n: (self.pos_base[mid], 0, 0, 1.0, .2))
            self.hold('zero3', .5, zero)
        if mode in ('all', 'velocity'):
            self.pos_base = {m: self.core.nodes[m]['p'] for m in self.ids}
            self.hold('vel+', 1.5,
                      lambda mid, n: (self.pos_base[mid], .20, +vel_ff, 0, 1.0))
            self.hold('vel-', 1.5,
                      lambda mid, n: (self.pos_base[mid], -.20, -vel_ff, 0, 1.0))
            self.hold('zero4', .5, zero)
        self.disable_all()
        self.wait(lambda: all(self.core.nodes.get(m, {}).get('phase') == 'IDLE'
                              for m in ids), 5.0, '并非全部回到 IDLE')
        return enable_s

    def disable_all(self):
        for mid in list(getattr(self, 'ids', [])):
            try:
                if mid in self.core.targets:
                    self.core.disable(mid, self.now())
            except Exception:
                pass
        end = self.now() + 3.0
        while self.now() < end:
            self.pump()


def summarize(rig, ids, pos_step):
    out = {}
    ph = rig.phase
    pos_base = getattr(rig, 'pos_base', {})
    for mid in ids:
        def rows(label):
            return ph.get(label, {}).get(mid, [])
        def tail(label, n=10):
            return rows(label)[-n:]
        def mean(seq, i):
            vals = [r[i] for r in seq]
            return sum(vals) / len(vals) if vals else float('nan')
        tq = rows('torque+')
        tqn = rows('torque-')
        up = rows('pos+')
        dn = rows('pos-')
        rec = {
            'id': mid,
            'torque_up': round(max([r[2] for r in tq], default=0), 3),
            'torque_dn': round(min([r[2] for r in tqn], default=0), 3),
            'dp_torque_up': round((tq[-1][0] - tq[0][0]), 3) if tq else None,
            'dp_torque_dn': round((tqn[-1][0] - tqn[0][0]), 3) if tqn else None,
            'pos_err': round(abs(up[-1][0] - (pos_base[mid] +
                                                rig.pos_dir.get(mid, 1) * pos_step)), 3)
                       if up else None,
            'pos_back_err': round(abs(dn[-1][0] - pos_base[mid]), 3) if dn else None,
            'vel_up': round(mean(tail('vel+'), 1), 3),
            'vel_dn': round(mean(tail('vel-'), 1), 3),
            'temp_max': max([r[3] for r in rows('torque+') + rows('vel+')], default=None),
            'faults': rig.core.nodes.get(mid, {}).get('faults', 0),
            'phase': rig.core.nodes.get(mid, {}).get('phase'),
        }
        out[mid] = rec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--ids', default='1-7')
    ap.add_argument('--torque', type=float, default=0.6)
    ap.add_argument('--vel-ff', type=float, default=0.15)
    ap.add_argument('--pos-step', type=float, default=0.1)
    ap.add_argument('--hold-only', action='store_true')
    ap.add_argument('--mode', choices=('all', 'zero', 'torque', 'position', 'velocity'),
                    default='all')
    ap.add_argument('--out', default='')
    args = ap.parse_args()
    ids = parse_ids(args.ids)
    if not 0 < args.torque <= 0.8 or not 0 <= args.vel_ff <= 0.5:
        raise SystemExit('torque (0,0.8] / vel-ff [0,0.5]')
    folder = Path(args.out) if args.out else (
        ROOT / 'logs' / datetime.now().strftime('%Y-%m-%d') /
        ('robot14-multi-' + datetime.now().strftime('%H%M%S_%f')))
    rig = Rig(args.port, folder)
    result = {'ids': ids, 'abort': None, 'enable_s': None, 'motors': {}}
    try:
        rig.ids = ids
        rig.wait_token()
        result['enable_s'] = rig.run(ids, args.torque, args.vel_ff, args.pos_step,
                                     args.hold_only, args.mode)
        result['motors'] = summarize(rig, rig.ids, args.pos_step)
        for mid, r in result['motors'].items():
            print('ID%d: T %s/%s dP %s/%s pos_err %s back %s vel %s/%s temp %s phase %s' % (
                mid, r['torque_up'], r['torque_dn'], r['dp_torque_up'],
                r['dp_torque_dn'], r['pos_err'], r['pos_back_err'],
                r['vel_up'], r['vel_dn'], r['temp_max'], r['phase']))
    except Exception as exc:
        result['abort'] = str(exc)
        print('ABORT:', exc)
        try:
            if not rig.core.latched and rig.core.owns:
                rig.core.stop('整组测试异常中止')
                end = rig.now() + 1.0
                while rig.now() < end:
                    rig.pump()
        except Exception:
            pass
    finally:
        result['latched'] = rig.core.latched
        try:
            (rig.folder / 'result.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        rig.close()
        print('证据目录:', rig.folder)


if __name__ == '__main__':
    main()
