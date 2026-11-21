"""Robot14 v1 binary link. No Tk, reset, flash, or CAN access in this module.

Session tokens reject accidental stale/cross-firmware commands, NOT an auth layer.
The board remains the authoritative safety/phase owner. Host acceptance != motion.
"""
import csv
import math
import json
import queue
import secrets
import struct
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HELLO, ENABLE, SET, PING, STOP, DISABLE, SELECT = range(1, 8)
INFO, ACK, STATE, NODE = 0x81, 0x82, 0x90, 0x91
SIGNATURE = 0x14A20C02
HEADER = struct.Struct('<2sBBHII')
INFO_DATA = struct.Struct('<I12sIIHH')
NODE_DATA = struct.Struct('<8Biiih5hHHIIH')
STATE_DATA = struct.Struct('<IBH7I15I')
PHASES = ('IDLE', 'STOP_WAIT', 'MODE_WRITE', 'MODE_QUERY', 'MODE_WAIT',
          'WD_WRITE', 'WD_QUERY', 'WD_WAIT', 'ZERO', 'ENABLE', 'ENABLE_WAIT', 'ACTIVE', 'FAULT')
ZERO = (0, 0, 0, 0, 0)
CAPS = ((-12.57, 12.57), (-1, 1), (-1, 1), (0, 5), (0, 1))


def topology(motor_id):
    if not 1 <= motor_id <= 14:
        raise ValueError('电机 ID 必须为 1–14')
    return (2 if motor_id <= 7 else 3), ('RS00' if motor_id in (1, 2, 3, 8, 9, 10) else 'RS10P')


def crc(data):
    value = 0xffff
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xffff
    return value


def packet(kind, seq=0, token=0, data=b''):
    if len(data) > 160:
        raise ValueError('超长 Robot14 帧')
    raw = HEADER.pack(b'R4', 1, kind, len(data), seq, token) + data
    return raw + struct.pack('<H', crc(raw))


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.bad = 0
        self.started = 0

    def feed(self, raw, now=None):
        now = time.monotonic() if now is None else now
        if self.buffer and now - self.started > .05:
            self.buffer.clear()
            self.bad += 1
        if not self.buffer:
            self.started = now
        self.buffer.extend(raw)
        frames = []
        while len(self.buffer) >= 2:
            if self.buffer[:2] != b'R4' or (len(self.buffer) >= 3 and self.buffer[2] != 1):
                del self.buffer[0]
                continue
            if len(self.buffer) < 14:
                break
            _, _, kind, size, seq, token = HEADER.unpack_from(self.buffer)
            if size > 160:
                self.bad += 1
                del self.buffer[0]
                continue
            total = size + 16
            if len(self.buffer) < total:
                break
            if crc(self.buffer[:total - 2]) != struct.unpack_from('<H', self.buffer, total - 2)[0]:
                self.bad += 1
                del self.buffer[0]
                continue
            frames.append((kind, seq, token, bytes(self.buffer[14:total - 2])))
            del self.buffer[:total]
            self.started = now
        return frames


def target(values):
    if len(values) != 5:
        raise ValueError('需要 p / v / τ / Kp / Kd 五项')
    floats = tuple(float(v) for v in values)
    if any(not math.isfinite(v) or not lo <= v <= hi for v, (lo, hi) in zip(floats, CAPS)):
        raise ValueError('超出整机调试限幅：p ±12.57 rad，v ±1 rad/s，τ ±1 Nm，Kp 0–5，Kd 0–1')
    return tuple(round(v * 1000) for v in floats)


def batch(targets):
    mask = sum(1 << (i - 1) for i in targets)
    return struct.pack('<H', mask) + b''.join(struct.pack('<5h', *targets[i]) for i in sorted(targets))


def decode_node(data, stamp, now):
    if len(data) != NODE_DATA.size:
        raise ValueError('Robot14 节点数据长度不匹配')
    a = NODE_DATA.unpack(data)
    motor_id, bus, model, phase, flags, mode, faults, _ = a[:8]
    expected_bus, expected_model = topology(motor_id)
    if bus != expected_bus or model != (0 if expected_model == 'RS00' else 1) or phase >= len(PHASES):
        raise ValueError('Robot14 固定拓扑 / 状态不匹配')
    return dict(id=motor_id, bus=bus, model=expected_model, phase=PHASES[phase], flags=flags,
                mode=mode, faults=faults, p=a[8]/1000, v=a[9]/1000, t=a[10]/1000,
                temp=a[11]/10, target=tuple(a[12:17]), fb_age=a[17], p_age=a[18],
                fault_word=a[19], warning_word=a[20], v_age=a[21], stamp=stamp, received=now)


def fresh(node, now, active=False):
    if not node or now - node['received'] > .3:
        return False
    if active:
        return node['phase'] == 'ACTIVE' and node['flags'] & 4 and node['fb_age'] + (now-node['received'])*1000 <= 100
    return node['flags'] & 3 == 3 and node['p_age'] + (now-node['received'])*1000 <= 300 and node['v_age'] + (now-node['received'])*1000 <= 300


class Controller:
    """Deterministic serial-owner state machine; caller must use only one thread."""
    def __init__(self, now, nonce=None):
        self.nonce = nonce or secrets.randbits(32) or 1
        self.token = 0
        self.seq = 0
        self.started = self.last_rx = self.ui_ms = now
        self.next_hello = self.next_ping = self.next_set = now
        self.nodes = {}
        self.targets = {}
        self.pending = {}
        self.deadlines = {}
        self.stopping = {}
        self.outbox = []
        self.events = []
        self.latched = False
        self.info = None

    @property
    def owns(self):
        return bool(self.targets or self.pending or self.stopping)

    def send(self, kind, data=b'', track=None, now=0):
        self.seq = (self.seq + 1) & 0xffffffff or 1
        self.outbox.append(packet(kind, self.seq, self.token, data))
        if track is not None:
            self.pending[self.seq] = (kind, track, now)
        return self.seq

    def stop(self, reason):
        # Remove unsent ordinary packets as well as pending UI targets.
        self.outbox.clear()
        self.targets.clear()
        self.pending.clear()
        self.deadlines.clear()
        self.stopping.clear()
        self.latched = True
        self.send(STOP)
        self.events.append(('message', reason + '；已请求全部锁存停机，等待板端确认。'))

    def enable(self, motor_id, duration, now):
        topology(motor_id)
        n = self.nodes.get(motor_id)
        if not self.token or self.latched or not fresh(n, now) or n['phase'] != 'IDLE' or abs(n['v']) > .1:
            raise ValueError('必须连接匹配固件，电机处于 IDLE、有新鲜静止读数且未锁存停机')
        if motor_id in self.deadlines or motor_id in self.stopping:
            raise ValueError('该电机已有请求，须等待停机确认')
        duration = float(duration)
        if not math.isfinite(duration) or not 1 <= duration <= 60:
            raise ValueError('本次使能时长必须为 1–60 秒；到时自动请求该电机停机')
        self.deadlines[motor_id] = now + duration
        self.send(ENABLE, bytes([motor_id]), motor_id, now)

    def enable_many(self, motor_ids, duration, now):
        """Queue one ENABLE per motor; return (queued, skipped).

        The firmware has no broadcast enable: every ID still passes the same
        IDLE / fresh static reading / lease checks as enable(). Motors that do
        not qualify are skipped and reported, not force-enabled.
        """
        queued, skipped = [], []
        for motor_id in motor_ids:
            try:
                self.enable(motor_id, duration, now)
                queued.append(motor_id)
            except (ValueError, TypeError) as exc:
                skipped.append((motor_id, str(exc)))
        return queued, skipped

    def apply(self, motor_id, values, now):
        values = target(values)
        n = self.nodes.get(motor_id)
        if self.latched or motor_id not in self.targets or not fresh(n, now, active=True):
            raise ValueError('仅能对已确认 ACTIVE、反馈新鲜且由本窗口使能的电机应用目标')
        p, v, torque, kp, kd = (v/1000 for v in values)
        if abs(torque) + kp*abs(p-n['p']) + kd*abs(v-n['v']) > 1.95:
            raise ValueError('预计阻抗力矩过大；请降低误差 / Kp / Kd / 前馈，板端另有 2 Nm 保护')
        self.targets[motor_id] = values
        self.next_set = now
        self.events.append(('message', f'ID{motor_id} 已提交新目标；以表格中的板端目标回显为准。'))

    def disable(self, motor_id, now):
        # A pending ENABLE may already be executing. Uncertain ownership -> stop all.
        if any(mid == motor_id for _, mid, _ in self.pending.values()):
            self.stop('使能 / 停机请求尚未确认时操作停止')
            return
        if motor_id not in self.targets:
            raise ValueError('该电机不由本窗口控制')
        del self.targets[motor_id]
        self.deadlines.pop(motor_id, None)
        self.stopping[motor_id] = now
        self.send(DISABLE, bytes([motor_id]), motor_id, now)

    def receive(self, frame, now):
        kind, stamp, token, data = frame
        if kind == INFO:
            if len(data) != INFO_DATA.size:
                raise ValueError('Robot14 INFO 长度不匹配')
            nonce, uid, clock, signature, lease, watchdog = INFO_DATA.unpack(data)
            if nonce != self.nonce:
                return
            if not token or (clock, signature, lease, watchdog) != (160000000, SIGNATURE, 100, 200):
                raise ValueError('固件版本 / 160MHz / 拓扑保护签名不匹配，请编译烧录本次 Robot14 固件')
            if self.token and token != self.token:
                raise ValueError('板端会话改变，可能复位；禁止恢复旧目标')
            self.token = token
            self.info = dict(uid=uid.hex(), clock=clock, signature=signature)
            self.events.append(('info', self.info))
        elif not self.token or token != self.token:
            return
        elif kind == NODE:
            n = decode_node(data, stamp, now)
            self.nodes[n['id']] = n
            if n['phase'] == 'IDLE':
                self.stopping.pop(n['id'], None)
            self.events.append(('node', n.copy()))
        elif kind == STATE:
            if len(data) != STATE_DATA.size:
                raise ValueError('Robot14 STATE 长度不匹配')
            a = STATE_DATA.unpack(data)
            health = dict(stamp=a[0], latched=bool(a[1]), stop_pending=a[2], rejected=a[3],
                          overruns=a[4], bad_frames=a[5], bms_valid=a[6], power_valid=a[7],
                          bms_mv=a[8], power_mv=a[9], can=(a[10:15], a[15:20], a[20:25]))
            if health['latched']:
                self.latched = True
                self.targets.clear()
                self.pending.clear()
                self.stopping.clear()
                self.deadlines.clear()
                self.outbox.clear()
            self.events.append(('state', health))
        elif kind == ACK:
            if len(data) != 3:
                raise ValueError('Robot14 ACK 长度不匹配')
            cmd, rejected, motor_id = data
            req = self.pending.pop(stamp, None)
            if req and req[:2] != (cmd, motor_id):
                raise ValueError('Robot14 应答与请求不匹配')
            if rejected:
                if req:
                    self.deadlines.pop(motor_id, None)
                # An ENABLE reject might concern an already physically running motor.
                if cmd in (SET, DISABLE) or self.owns:
                    self.stop('板端拒绝请求，停止其余受控电机')
                self.events.append(('message', f'板端拒绝命令 {cmd} / ID{motor_id}，请检查反馈和状态。'))
            elif req and cmd == ENABLE and not self.latched:
                self.targets[motor_id] = ZERO
                self.events.append(('message', f'ID{motor_id} 使能请求已接收，零力矩握手中；等待 ACTIVE。'))
            elif req:
                self.events.append(('message', f'ID{motor_id} 停机请求已接收；等待 IDLE 实际确认。'))
        self.last_rx = now

    def step(self, now):
        if self.token and now-self.last_rx > 1.0:
            raise OSError('板端遥测中断超过1秒，连接关闭；禁止自动恢复旧目标')
        if self.owns and now-self.ui_ms > .2:
            self.stop('界面心跳超时')
        if self.owns and now-self.last_rx > .5:
            self.stop('板端遥测超时')
        if any(now-sent > .3 for _, _, sent in self.pending.values()):
            self.stop('控制请求 ACK 超时')
        if any(now-sent > .65 for sent in self.stopping.values()):
            self.stop('选中电机停机未确认')
        for motor_id in list(self.targets):
            if now >= self.deadlines[motor_id]:
                self.disable(motor_id, now)
        if not self.token:
            if now-self.started > 3:
                raise ValueError('3秒内未收到匹配 Robot14 INFO；旧 ASCII / 单双机调参固件不能使用此窗口')
            if now >= self.next_hello:
                self.outbox.append(packet(HELLO, token=self.nonce))
                self.next_hello = now + .25
            return
        if now >= self.next_ping:
            self.send(PING)
            self.next_ping = now + .04
        if self.targets and not self.latched and now >= self.next_set:
            self.send(SET, batch(self.targets))
            self.next_set = now + .02


@dataclass(frozen=True)
class Action:
    name: str
    args: tuple = ()


class Worker:
    """One serial owner. UI never shares mutable model objects or calls serial."""
    def __init__(self, port, log_root, serial_factory=None):
        self.port = port
        self.log_root = Path(log_root)
        self.serial_factory = serial_factory
        self.actions = queue.Queue()
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.close_event = threading.Event()
        self.ui_ms = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True, name='Robot14Serial')

    def start(self):
        self.thread.start()

    def submit(self, name, *args):
        if name == 'stop':
            self.stop_event.set()
        else:
            self.actions.put(Action(name, args))

    def alive(self):
        self.ui_ms = time.monotonic()

    def close(self):
        self.close_event.set()

    def run(self):
        dev = None
        core = Controller(time.monotonic())
        confirmed = False
        closing = None
        needed_stop = False
        try:
            folder = self.log_root / ('robot14-tuning-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            folder.mkdir(parents=True)
            self.events.put(('folder', str(folder)))
            if self.serial_factory:
                dev = self.serial_factory()
            else:
                sys.path.insert(0, str(Path(__file__).parent/'vendor'))
                import serial
                dev = serial.Serial(port=None, baudrate=115200, timeout=.005, write_timeout=.025)
                dev.dtr = False
                dev.rts = False
                dev.port = self.port
                dev.open()  # No explicit DTR/RTS pulse, reset or programmer call.
            parser = Parser()
            with (folder/'nodes.csv').open('w', newline='', encoding='utf-8-sig') as output:
                writer = csv.writer(output)
                writer.writerow(('host_monotonic', 'board_ms', 'id', 'bus', 'model', 'phase', 'flags',
                                 'p_rad', 'v_rad_s', 'torque_Nm', 'temp_C', 'fb_age_ms', 'p_age_ms',
                                 'v_age_ms', 'cmd_p_mrad', 'cmd_v_mrad_s', 'cmd_t_mNm', 'cmd_kp_milli',
                                 'cmd_kd_milli', 'fault_bits', 'fault_word', 'warning_word'))
                with (folder/'wire.bin').open('wb') as rawlog, (folder/'commands.jsonl').open('w', encoding='utf-8') as commands:
                    while True:
                        now = time.monotonic()
                        core.ui_ms = self.ui_ms
                        if self.stop_event.is_set():
                            self.stop_event.clear()
                            while not self.actions.empty():
                                try: self.actions.get_nowait()
                                except queue.Empty: break
                            core.stop('操作者请求全部锁存停机')
                        if self.close_event.is_set() and closing is None:
                            closing = now
                            needed_stop = core.owns or core.latched
                            if core.owns:
                                core.stop('关闭连接')
                        # Bound work so incoming UI events cannot starve feedback/STOP.
                        for _ in range(16):
                            if closing is not None or self.stop_event.is_set(): break
                            try: a = self.actions.get_nowait()
                            except queue.Empty: break
                            try:
                                if a.name == 'enable': core.enable(*a.args, now)
                                elif a.name == 'enable_all':
                                    queued, skipped = core.enable_many(a.args[0], a.args[1], now)
                                    if queued:
                                        core.events.append(('message',
                                            '全部使能请求已入队：ID' + '、'.join(map(str, queued)) +
                                            f'（零力矩，{a.args[1]:g} 秒；以表格 ACTIVE 为准）'))
                                    for mid, why in skipped:
                                        core.events.append(('message', f'ID{mid} 未入队：{why}'))
                                elif a.name == 'apply': core.apply(*a.args, now)
                                elif a.name == 'disable': core.disable(*a.args, now)
                                elif a.name == 'select' and core.token: core.send(SELECT, bytes([a.args[0]]))
                            except (ValueError, TypeError) as exc:
                                core.events.append(('message', str(exc)))
                        data = dev.read(2048)
                        if data:
                            rawlog.write(data)
                            for frame in parser.feed(data, now): core.receive(frame, now)
                        if closing is None:
                            core.step(now)
                        for wire in core.outbox:
                            commands.write(json.dumps({'host_monotonic':now, 'type':wire[3], 'wire_hex':wire.hex()})+'\n')
                            if dev.write(wire) != len(wire):
                                raise OSError('串口未完整写入；连接中止')
                        core.outbox.clear()
                        for kind, value in core.events:
                            self.events.put((kind, value))
                            if kind == 'info':
                                (folder/'session.json').write_text(json.dumps(dict(value, port=self.port, host_nonce=core.nonce, protocol=1), indent=2), encoding='utf-8')
                            if kind == 'node':
                                n = value
                                writer.writerow((n['received'], n['stamp'], n['id'], n['bus'], n['model'],
                                                 n['phase'], n['flags'], n['p'], n['v'], n['t'], n['temp'],
                                                 n['fb_age'], n['p_age'], n['v_age'], *n['target'],
                                                 n['faults'], n['fault_word'], n['warning_word']))
                            if kind == 'state':
                                confirmed = value['latched'] and value['stop_pending'] == 0
                        core.events.clear()
                        if closing is not None and (not needed_stop or confirmed or now-closing > .7):
                            break
        except Exception as exc:
            # Best effort only; board leases/watchdog remain independent of host I/O.
            if dev is not None and core.owns:
                try: dev.write(packet(STOP))
                except Exception: pass
            self.events.put(('error', str(exc)))
        finally:
            if dev is not None:
                try: dev.close()
                except Exception: pass
            self.events.put(('closed', '全部停机已确认' if confirmed else
                             '连接已关闭；无本窗口受控电机' if not core.owns and not needed_stop and not core.latched else
                             '连接已关闭；物理停机未确认，请检查急停 / 供电，勿认为电机已停稳'))
