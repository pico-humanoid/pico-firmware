"""Chinese explanations for PICO experiment logs. Does not drive the experiment."""
from contextlib import contextmanager
from pathlib import Path
import csv
import json
import re

from log_model import EVENT_NAMES, FIELD_NAMES, format_value, parse_record

FRAMES = {
    'TX_SUBMIT': '已提交发送，尚未证明上总线或收到应答',
    'TX_DONE': 'CAN 控制器报告发送完成，不能代替目标设备的业务回复',
    'TX_TIMEOUT': '等待 CAN 发送完成超时',
    'RX': '收到 CAN 报文；是否为本次请求的有效回复还需校验',
    'RX_REMOTE': '收到远程请求帧；它没有数据载荷',
    'SERIAL_SUBMITTED': '电脑已将请求写入适配器串口，不能据此确认 CAN 发送完成',
}

REASONS = {
    'TRACKING':'正在跟踪目标', 'PREPARING':'正在准备实验', 'PREPARING_POSITION':'正在准备位置实验',
    'BOTH_MOTORS':'双机实验', 'WAIT_MANUAL_ARM':'等待手动启动', 'SYNC_TRACKING':'正在跟踪同步轨迹',
    'SYNC_SETTLING':'等待同步轨迹终点稳定', 'LOW_SPEED_TEST':'低速转动实验',
    'ZERO_CURRENT_TEST':'零电流使能实验', 'STOPPED_ECHO_TEST':'停机写回对照',
    'TX_TIMEOUT':'等待发送完成超时', 'CAN_PROTOCOL_ERROR':'CAN 协议错误',
    'NONE':'未报告异常', 'USER_STOP':'操作者请求停机', 'MANUAL_STOP':'操作者请求停机',
    'BOOT_STOP':'启动时先请求停机', 'AUTO_STOP':'达到实验运行时限', 'GROUP_AUTO_STOP':'双机达到运行时限',
    'HOST_TIMEOUT':'电脑心跳超时', 'FEEDBACK_TIMEOUT':'电机运行反馈超时',
    'TELEMETRY_TIMEOUT':'位置、电流或速度采样超时', 'PEER_STOP':'另一台触发，联动请求停机',
    'MOTOR_FAULT':'电机报告故障', 'SUSPECTED_OBSTRUCTION':'疑似受阻或堵转', 'NO_MOTION':'未确认实际转动',
    'CAN_LINK_ERROR':'CAN 链路或控制器统计异常', 'BUS_OFF':'CAN 控制器进入总线关闭状态',
    'CAN_TX_TIMEOUT':'CAN 发送完成超时', 'CAN_TX_EVENT_LOST':'CAN 发送完成事件丢失',
    'CAN_TX_EVENT_UNKNOWN':'CAN 发送完成事件无法匹配', 'CAN_TX_REJECTED':'控制器拒绝发送请求',
    'CAN_SUBMIT_FAILED':'提交 CAN 请求失败', 'CAN_SUBMIT_REJECTED':'提交 CAN 请求被拒绝',
    'UART_LINK_ERROR':'开发板与电脑之间的串口异常', 'STOP_UNCONFIRMED':'停机未确认',
    'MOTOR_NOT_STOPPED':'电机未报告已停机', 'STOPPED_TARGET_CLEAR_FAILED':'停机后清除目标未通过',
    'STOPPED_TARGET_NEUTRALIZE_FAILED':'停机后中和目标未通过', 'CURRENT_LIMIT':'电流触发保护阈值',
    'SPEED_LIMIT':'速度触发保护阈值', 'DISPLACEMENT_LIMIT':'位移触发保护阈值',
    'DISPLACEMENT_OVER_8_DEG':'位移超过 8°', 'POSITION_SAMPLE_JUMP':'位置采样跳变',
    'POSITION_UNSTABLE':'位置采样不稳定', 'STOPPED_POSITION_UNSTABLE':'停机状态下位置不稳定',
    'POSITION_MOVED_WHILE_STOPPED':'停机期间检测到位置变化',
    'ORIGIN_MOVED_BEFORE_ENABLE':'使能前起点位置发生变化', 'ORIGIN_MOVED_BEFORE_STREAM':'下发轨迹前起点发生变化',
    'INVALID_ORIGIN':'起点数据无效', 'INVALID_START_POSITION':'起点位置无效',
    'INVALID_TELEMETRY':'采样数据无效', 'INVALID_MOTION_TELEMETRY':'运动采样数据无效',
    'INVALID_FEEDBACK_MODE':'反馈中的运行模式无效', 'INVALID_PARAMETER_VALUE':'参数值无效',
    'REPLY_TIMEOUT':'等待电机回复超时', 'DIAGNOSTIC_REPLY_TIMEOUT':'诊断读回超时',
    'PARAMETER_MISMATCH':'参数写入值和读回值不一致', 'MODE_READBACK_MISMATCH':'运行模式读回不一致',
    'ZERO_READBACK_MISMATCH':'零电流目标读回不一致', 'SPEED_PARAMETER_READBACK_MISMATCH':'速度模式参数读回不一致',
    'SPEED_TARGET_READBACK_MISMATCH':'目标速度读回不一致', 'POSITION_PARAMETER_MISMATCH':'位置模式参数读回不一致',
    'POSITION_TARGET_MISMATCH':'目标位置读回不一致', 'PARAMETER_READ_FAILED':'参数读取失败',
    'PARAMETER_READ_REJECTED':'参数读取请求被拒绝', 'UID_CHANGED':'电机 UID 变化', 'UID_INVALID':'电机 UID 无效',
    'CSP_NOT_SELECTED':'电机不处于 CSP 位置模式', 'UNKNOWN_RUN_MODE':'未识别运行模式',
    'WRITE_INTERLOCK_FAILED':'写入前的保护条件未满足', 'UNEXPECTED_MOTOR_MODE':'反馈模式与预期不符',
    'STAGE_TIMEOUT':'当前阶段超时', 'STAGE_RESPONSE_TIMEOUT':'当前阶段等待回复超时',
    'TOTAL_TIMEOUT':'实验总时长超时', 'WAYPOINT_TIMEOUT':'未能在期限内到达轨迹点',
    'FINAL_SETTLE_TIMEOUT':'末端稳定等待超时', 'TRACKING_ERROR_OVER_2_DEG':'跟踪误差超过 2° 并触发保护',
    'TRACKING_QUALITY_FAILED':'跟踪质量检查未过', 'TARGET_SCHEDULER_OVERRUN':'轨迹目标未能按时调度',
    'UNEXPECTED_DISPLACEMENT':'报告了异常位移', 'UNEXPECTED_SPEED':'报告了异常速度',
    'STALE_HOST_COMMAND':'电脑指令已过期', 'STALE_CAN_FRAME':'CAN 报文已过期', 'STALE_RX_QUEUE':'接收队列数据过期',
    'GROUP_START_REJECTED':'双机启动条件未满足', 'SEE_PER_MOTOR_STATE':'请看各电机的单独状态',
    'POSITION_COMPLETE':'位置轨迹已执行完', 'BOTH_POSITION_COMPLETE':'两台电机的位置轨迹已执行完',
    'SYNC_TRAJECTORY_COMPLETE':'同步轨迹已执行完', 'BOTH_SYNC_TRAJECTORY_COMPLETE':'两台电机的同步轨迹已执行完',
    'EXPECTED_FEEDBACK_TIMEOUT_BOTH_STOPPED':'预期的反馈超时已触发，两台电机均确认停机',
    'TIMER_EXPIRED':'达到设定时限', 'READ_ONLY_BASELINE':'进行只读基线采样', 'ECHO_REQUESTED':'请求执行写回对照',
    'READBACK_CONSISTENT':'参数读回一致', 'READBACK_MISMATCH':'参数读回不一致',
}
STATES = {
    'READ_START_POSITION':'读取起点位置',
    'READY':'准备就绪，等待启动', 'WAIT_MANUAL_ARM':'等待手动启动', 'STOPPING':'正在请求停机并等待回复',
    'DONE':'流程结束，请查看结果和停机确认', 'RUNNING':'运行中', 'ENABLED':'电机已使能',
    'WAIT_ENABLED':'等待使能反馈', 'READ_BASELINE':'读取初始参数', 'BASELINE':'采集初始值',
    'CONFIRM_STOP':'核对停机状态', 'ARM_CONFIRM_STOP':'启动前核对停机',
    'READ_UID':'读取电机 UID', 'READ_VERSION':'读取版本', 'READ_PARAMETERS':'读取诊断参数',
    'MONITOR':'持续读取诊断数据', 'READ_ORIGIN':'读取本次起点位置',
    'SET_CURRENT_MODE':'设置电流模式', 'SET_ZERO':'写入零电流目标', 'VERIFY_ZERO':'读回核对零电流目标',
    'VERIFY_MODE':'核对运行模式', 'PREPARING':'准备参数', 'PREPARING_POSITION':'准备位置模式参数',
    'SETUP_WRITE':'写入运行参数', 'SETUP_READ':'读回运行参数', 'POSTCHECK':'启动后复核参数',
    'APPLY_WRITE':'写入新目标', 'APPLY_READ':'读回新目标', 'CLEAR_TARGET':'清除或中和目标',
    'CLEAR_SPEED_TARGET':'将目标速度清零', 'VERIFY_CLEARED_TARGET':'读回核对目标是否已清理',
    'POSITION_WRITE':'写入位置参数', 'POSITION_READ':'读回位置参数', 'CHECK_START_POSITION':'核对起点位置',
    'POSITION_POSTCHECK':'使能后检查位置参数', 'SET_POSITION_TARGET':'写入目标位置',
    'VERIFY_POSITION_TARGET':'读回目标位置', 'POSITION_MOVING':'执行位置轨迹',
    'READ_STOP_POSITION':'读取停机位置', 'HOLD_STOP_POSITION':'把位置目标更新为停机位置',
    'VERIFY_STOP_TARGET':'读回停机位置目标', 'SPEED_SETUP_WRITE':'写入速度模式参数',
    'SPEED_SETUP_READ':'读回速度模式参数', 'SPEED_POSTCHECK':'使能后检查速度参数',
    'SET_SPEED_TARGET':'写入目标速度', 'VERIFY_SPEED_TARGET':'读回目标速度',
    'SYNC_TRACKING':'按共同时间轴跟踪轨迹', 'SYNC_SETTLING':'等待轨迹终点稳定',
    'ECHO_CONFIRM_STOP':'写回对照前核对停机', 'ECHO_READ_MODE':'写回对照前核对模式',
    'ECHO_READ_ACTUAL':'读取写回前的实测位置', 'ECHO_WRITE_CURRENT_POSITION':'将当前实测位置写为目标',
    'ECHO_READBACK':'读回写入的目标位置', 'ECHO_READ_ACTUAL_AFTER':'读取写回后的实测位置',
}
TAGS = {
    'HEALTH':'CAN 健康统计', 'PC_CAN_HEALTH':'CAN 双向测试统计', 'LISTEN_HEALTH':'CAN 只听统计',
    'PERIODIC_HEALTH':'循环发送统计', 'MULTI_HEALTH':'各 CAN 通道健康统计', 'MULTI_RESULT':'该 CAN 通道的板端结果',
    'MULTI_OTHER':'非预期协议报文', 'MULTI_READY':'多通道测试就绪', 'DEVICE_HEALTH':'设备查询统计',
    'CAN_FAULT_DETAIL':'CAN 故障寄存器及计数', 'CAN_DIAG':'CAN 外设诊断', 'RX_EDGE_LATCH':'接收引脚跳变诊断',
    'BMS':'电池 BMS 数据', 'POWER':'电源板数据', 'MOTOR':'电机只读数据',
    'CONTROL_BACKEND':'电机控制协议实现', 'FAULT_CONFIG':'保护实验的故障注入配置',
    'FAULT_INJECT':'保护实验故意丢弃反馈', 'FAULT_DETECTED':'板端报告已检测到故障',
    'TUNE_ACCEPTED':'板端受理新目标；请查看回读序号是否跟上', 'TUNE_SAMPLE':'位置、速度及电流采样',
    'SYNC_POSITION_SAMPLE':'同步轨迹采样', 'SYNC_POSITION_SEGMENT':'同步轨迹段进度',
    'POSITION_WAYPOINT':'单机已完成一个轨迹点', 'DUAL_POSITION_WAYPOINT':'双机实验中的单台轨迹点进度',
    'DIAG_VALUE':'停机诊断参数', 'DIAG_ECHO':'停机写回对照', 'DIAG_ECHO_RESULT':'停机写回对照结果',
    'DIAG_UID':'诊断读到的电机 UID', 'DIAG_VERSION':'诊断读到的固件版本', 'TUNE_UID':'跟踪实验电机 UID',
    'TUNE_ORIGIN':'跟踪实验起点', 'SPEED_LIMITS':'低速实验参数及保护阈值', 'SESSION_OK':'串口会话建立',
    'MOTOR_CONFIG':'电机只读配置', 'MOTOR_CAN_PINS':'电机 CAN 引脚配置', 'TX':'发送和接收引脚配置',
    'Baseline':'停机诊断的基础读取配置', 'SYNC_POSITION_ORIGIN':'同步轨迹的实测起点',
    'LIMIT_ACCEPTED':'板端受理限流设置，请结合后续读回', 'DIAG_VERIFY_ACCEPTED':'板端受理停机写回对照请求',
    'PIN_SAMPLE':'引脚采样结果', 'PIN_TRACE':'引脚电平观测', 'FDCAN':'CAN 控制器配置',
    'QUERY':'发起一笔设备只读查询', 'DUAL':'BMS 与电源板轮询配置',
    'mode':'实验运行模式', 'queries':'只读查询列表', 'hardware':'板端硬件配置', 'protocol':'设备协议配置',
    'STOP':'板端报告停止请求或停止查询，请结合上下文', 'TX_SKIPPED':'此轮未提交发送',
    'BUS_OFF':'CAN 总线关闭', 'INVALID':'数据无效', 'RESULT':'板端报告实验结果',
}
BOOL_FIELDS = {
    'stop_confirmed':'停机已确认', 'stop_unconfirmed':'停机未确认', 'target_cleared':'停机后目标已清理',
    'enable_confirmed':'已确认使能', 'motion_confirmed':'已观察到实际运动', 'position_valid':'位置有效',
    'uid_stable':'UID 一致', 'error':'本条状态报告错误', 'cancelled':'操作者已取消',
    'progress_valid':'双机进度差有效', 'neutralize_failed':'停机后中和目标失败', 'echo_allowed':'允许停机写回对照',
    'board_pass':'板端检查通过', 'automatic_hardware_pass':'自动判定硬件通过',
}
FIELDS = {
    **FIELD_NAMES, 'id':'ID', 't_ms':'板端时间（ms）', 'elapsed_ms':'已运行（ms）',
    'duration_ms':'设定时长（ms）', 'iq_mA':'Iq 电流（A）', 'peak_iq_mA':'峰值 Iq（A）',
    'limit_mA':'设定限流（A）', 'speed_limit_mrad_s':'设定限速（rad/s）',
    'error_mdeg':'位置误差（°）', 'command_angle_mdeg':'电脑要求相对角度（°）',
    'target_angle_mdeg':'板端目标相对角度（°）', 'actual_angle_mdeg':'实测相对角度（°）',
    'velocity_mrad_s':'实测速度（rad/s）', 'command_velocity_mrad_s':'电脑要求速度（rad/s）',
    'target_velocity_mrad_s':'板端速度目标（rad/s）', 'reference_urad':'参考位置（rad）',
    'actual_urad':'实测位置（rad）', 'delta_urad':'相对起点位移（rad）',
    'error_urad':'跟踪误差（rad）', 'target_delta_urad':'目标位移（rad）',
    'arrival_error_urad':'到位误差（rad）', 'tracking_peak_urad':'峰值跟踪误差（rad）',
    'tracking_rms_urad':'均方根跟踪误差（rad）', 'tracking_samples':'跟踪采样数',
    'delta_mrad':'相对起点位移（rad）', 'target_delta_mrad':'相对起点目标位移（rad）',
    'max_arrival_error_mrad':'最大到位误差（rad）', 'max_return_error_mrad':'最大回起点误差（rad）',
    'stable_span_urad':'稳定窗口内位置波动范围（rad）', 'stable_velocity_mrad_s':'稳定窗口速度（rad/s）',
    'position_step_speed_mrad_s':'相邻采样估计速度（rad/s）', 'position_mean_speed_mrad_s':'窗口平均估计速度（rad/s）',
    'stable_elapsed_ms':'稳定采样用时（ms）', 'stable_samples':'稳定窗口采样数', 'uid_samples':'UID 读取次数',
    'iq_samples':'Iq 采样数', 'velocity_samples':'速度采样数', 'position_samples':'位置采样数', 'feedbacks':'运行反馈数',
    'command_iq_mA':'电脑要求 Iq（A）', 'iq_target_mA':'板端目标 Iq（A）', 'uart_rx':'串口收到的字节数',
    'pairs':'成对下发次数', 'waypoints_completed':'已完成轨迹点数', 'max_lateness_ms':'最大调度延迟（ms）',
    'max_pair_skew_ms':'一对指令的最大时间差（ms）', 'progress_gap_ppm':'双机归一化进度差（ppm）',
    'max_progress_gap_ppm':'最大双机归一化进度差（ppm）', 'progress_at_ms':'进度观测时间（ms）',
    'uart_tx_high_water':'串口发送队列最高占用', 'target':'目标', 'attempt':'查询尝试次数', 'tx_id':'发送 CAN ID',

    'accepted_seq':'板端受理序号', 'applied_seq':'电机读回确认序号', 'cycles_completed':'已完成轮数',
    'segments_completed':'已完成轨迹段数', 'completed':'已完成数', 'total':'计划总数',
    'cycle':'轮次', 'leg':'段次', 'phase':'阶段', 'rx':'已接收帧', 'rx_unique':'不重复有效请求数',
    'tx_timed_out':'发送超时累计', 'rx_queue_dropped':'软件接收队列丢弃累计', 'rx_read_failed':'读取接收帧失败累计',
    'rx_edge_observations':'观测到的 RX 跳变次数（非精确边沿计数）', 'lec':'最近 CAN 错误码 LEC',
    'psr':'CAN 协议状态寄存器', 'uart_errors':'串口错误计数', 'uart_error':'串口错误位掩码',
    'tx_pending':'待发缓冲区位掩码', 'tx_cancelled':'取消发送', 'tx_transmitted':'已发送缓冲区位掩码',
    'can_bitrate':'CAN 位速率', 'bitrate':'CAN 位速率（bit/s）', 'channel':'通道',
    'name':'参数名', 'value':'数值', 'param':'参数功能码', 'index':'参数索引',
    'uid':'电机 UID', 'mode':'运行模式', 'model':'配置型号',
    'sent':'电脑已提交帧数', 'valid_replies':'有效回复数', 'missing':'缺少的序号', 'duplicates':'重复的序号',
    'other_frames':'其他报文数', 'decoder_discarded_bytes':'解码丢弃的字节数',
    'decoder_unsupported_frames':'解码不支持的帧数', 'decoder_pending_bytes':'结束时剩余未解码字节数',
    'errors':'错误明细', 'requests':'请求数', 'matched':'匹配回复数', 'reply_span_s':'有效回复覆盖时长（s）',
    'message':'说明', 'pass':'本项验收结果', 'capture_only':'只采集', 'sequence':'序号',
}
# Separate from the word "matched" in a diagnostic readback. A successful readback
# does not imply an actual movement test or an overall hardware pass.
CAN_ERROR_CODES = {
    '0':'无错误', '1':'位填充错误', '2':'帧格式错误', '3':'未收到 ACK',
    '4':'发送隐性位时检测到位错误', '5':'发送显性位时检测到位错误', '6':'CRC 错误',
    '7':'距离上次读取没有新上报的协议事件',
}
OUTCOMES = {'PASS':'本项通过', 'FAIL':'本项未通过', 'ERROR':'实验报告异常',
            'STOPPED':'流程已结束，请检查停机确认', 'MATCH':'写入与读回一致',
            'CONSISTENT':'读回一致', 'MISMATCH':'读回不一致'}
COMMANDS = {
    'SESSION':'建立电脑与开发板的控制会话', 'KEEP':'发送心跳', 'STOP':'电脑请求停机，等待反馈确认',
    'ARM':'请求开始跟踪', 'ARM2':'请求开始双机跟踪', 'SET':'更新目标', 'SET2':'更新双机目标',
    'SETSPEED':'更新目标速度', 'LIMIT':'设置运行限流', 'VERIFY':'请求停机写回对照',
    'ENABLE':'请求使能', 'RUN':'请求开始实验', 'POSITION':'请求位置实验', 'SPEED':'请求低速实验',
}

LEGEND = '''先看「结果」「停机确认」「原因」三项。只读采集结束表示记录完成；需要另行验收。

[板端状态] state 是当前阶段，reason 是本条报文给出的原因；DONE 只表示流程走完。
[实验结果] PASS/FAIL 只针对当前实验或子项。STOPPED 仍要看 stop_confirmed。
[电脑发送] 指电脑写入串口，尚不能证明电机已接收、执行或停机。
[提交发送] TX_SUBMIT；[发送完成] TX_DONE；[接收报文] RX：这是三个不同的事件。
[保护实验] FAULT_INJECT 表示测试主动漏掉反馈；FAULT_DETECTED 表示板端报告已检测到。
[健康统计] tx_done 是发送完成计数，TEC/REC 是 CAN 发送/接收错误计数，LEC 是最近协议错误码；7 表示自上次读取以来未观测到新的协议事件，不能据此判断总线正常。
[跟踪采样] 受理序号 accepted_seq 表示板端收到了目标；applied_seq 表示目标已读回确认。
实测位置/速度与目标的偏差才反映跟踪效果。限流值是设定上限，Iq 是电机反馈电流。
[停机诊断] UID 用于区分电机；写回对照的结果只代表停机条件下参数是否一致。
[双向验收] 有效回复需通过本实验的 ID、序号和载荷检查；收到其他帧不能算通过。
停机确认=否表示这条记录未确认停机。流程结束时仍未确认，应使用实物断电措施。

保留同目录的原始日志以及适配器原始字节文件。中文副本按数据来源分段，从原文解析；板端时间与电脑时间不混排。
'''
TAG_RE = re.compile(r'([A-Za-z][A-Za-z0-9_]*)(?=[=,;:\s]|$)')
FIELD_RE = re.compile(r'(?:^|[,;\s]+)([A-Za-z_]\w*)=')


def values_of(body):
    matches = list(FIELD_RE.finditer(body))
    return {m[1]: body[m.end():matches[i+1].start() if i+1<len(matches) else len(body)].rstrip(' ,;')
            for i,m in enumerate(matches)}


def coded(mapping, code):
    return f'{mapping[code]}（{code}）' if code in mapping else str(code)


def field_text(key, value):
    if key in BOOL_FIELDS:
        label = BOOL_FIELDS[key]
        value = {'True':'是','False':'否','1':'是','0':'否','true':'是','false':'否'}.get(str(value), value)
        return f'{label}={value}'
    if key in ('state','reason','result'):
        names, label = {'state':(STATES,'阶段'),'reason':(REASONS,'原因'),'result':(OUTCOMES,'结果')}[key]
        if isinstance(value, str):
            code, suffix, detail = value.partition(';')
            value = coded(names, code.strip()) + (suffix + detail if suffix else '')
        return f'{label}={value}'
    if key=='pass':return '本项验收：通过' if value is True else '本项验收：未通过' if value is False else f'验收={value}'
    if key=='lec':return f'{FIELDS[key]}={coded(CAN_ERROR_CODES, str(value))}'
    if key=='mode' and isinstance(value, str):
        code, sep, detail = value.partition(';')
        value = coded({'POS':'位置跟踪','SPD':'速度跟踪','INTERNAL_LOOPBACK':'内部回环',
                       'EXTERNAL_NORMAL':'外部正常模式','BUS_MONITORING':'总线只听模式'}, code) + sep + detail
    if key in FIELDS:
        if key.endswith(('_mA','_mdeg','_mrad','_mrad_s','_urad')):
            try:value = f'{int(value)/(1000000 if key.endswith("_urad") else 1000):g}'
            except (TypeError,ValueError):pass
        else:
            value, unit = format_value(key, value)
            if unit:value += ' '+unit
        return f'{FIELDS[key]}={value}'
    return f'{key}={str(value)}'


def describe(line, *, compact=False):
    line = line.strip().removeprefix('开发板：').strip()
    if line.startswith('> '):
        command = line[2:].split()
        if not command:return None
        return f'[电脑发送] {coded(COMMANDS,command[0])}'
    if line.startswith('#'):
        body = line[1:].strip()
        match = TAG_RE.match(body)
        if not match:return None
        tag = match[1]
        vals = values_of(body)
        if tag == 'RESULT' and 'RESULT' in vals:vals['result']=vals.pop('RESULT')
        name = TAGS.get(tag)
        if not name:
            if body.startswith('PICO ') or tag.startswith(('PICO_', 'CAN_','CAN1_', 'CAN2_', 'CAN3_')) and body[len(tag):].startswith('=1'):
                name = '固件启动及实验配置'
            elif tag.endswith('_STATE'):name = '板端状态'
            elif tag.endswith('_RESULT'):name = '实验结果'
            elif tag.endswith('_COMMAND_READY'):name = '板端已准备接收电脑命令'
            elif tag.endswith(('_FATAL','_INIT_ERROR')) or tag in ('ERROR','FATAL'):name = '固件报告初始化或运行错误'
            elif tag.endswith('_REJECTED'):name = '板端拒绝当前操作'
            elif tag.endswith('_PHASE'):name = '板端进入实验阶段'
            elif tag.endswith('_START'):name = '板端报告实验开始'
            else:return None
        if compact:
            trimmed = {k:v for k,v in vals.items() if k in ('state','reason','result','id','stop_confirmed',
                        'target_cleared','accepted_seq','applied_seq','replies','actual_angle_mdeg','velocity_mrad_s',
                        'iq_mA','tx_done','rx','tec','rec','lec','name','value','cycles_completed')}
            if trimmed:vals = trimmed
        pieces = [field_text(k,v) for k,v in vals.items()]
        result = f'[{name}] {tag}' + (' · ' + '；'.join(pieces) if pieces else '')
        if tag.endswith('_RESULT') and vals.get('stop_confirmed') == '0':result += '。结束时未确认停机。'
        return result
    if ',' not in line and not line.startswith('{'):return None
    if line.startswith('{'):
        try:item = json.loads(line)
        except ValueError:return None
        if isinstance(item, dict) and 'command' in item:
            details = describe('> ' + str(item['command']))
            return details + (' · ' + str(item.get('time', item.get('at',''))) if details else '') if details else None
        if not isinstance(item,dict) or 'event' not in item:return None
    rec = parse_record(line,1)
    if not rec or rec.event not in FRAMES:return None
    scope = f'{rec.channel} ' if rec.channel else ''
    timing = (' · 时间 '+rec.time if rec.time and rec.display_time == rec.time else
              f' · 相对时间 {rec.display_time} s' if rec.time else '')
    data = f' · {rec.data}' if rec.data else ''
    return f'[{EVENT_NAMES.get(rec.event,rec.event)}] {rec.event}：{FRAMES[rec.event]} · {scope}{rec.format} ID={rec.identifier}{timing}{data}'


def display_line(line):
    """Show Chinese next to the original, leaving transport data untouched."""
    text = describe(line, compact=True)
    return text + '\n  原文：' + line if text else line


def export_notes(output, sources, *, result=None, status=None, name='PICO 实验'):
    with output.open('w',encoding='utf-8-sig',newline='\n') as report:
        report.write(f'{name} · 中文日志说明\n\n' + LEGEND)
        if status:report.write(f'\n[采集状态] {status}\n')
        if result and isinstance(result,dict):
            report.write('\n--- 结果摘要 ---\n')
            if result.get('capture_only'):
                report.write('本次仅采集，没有自动判定设备通过。\n')
            for key,value in result.items():
                if key in ('result_line','result') and isinstance(value,str):
                    report.write((describe(value) or field_text('result',value))+'\n')
                elif key in ('last_state','result') and isinstance(value,dict) and value:
                    report.write(('最后一次状态' if key=='last_state' else '板端结果')+'：'+'；'.join(field_text(k,v) for k,v in value.items())+'\n')
                elif key in (set(BOOL_FIELDS)|{'pass','sent','valid_replies','missing','duplicates','invalid','other_frames',
                              'decoder_discarded_bytes','decoder_unsupported_frames','decoder_pending_bytes','message',
                              'requests','matched','reply_span_s','reason','errors'}) and not (key=='pass' and result.get('capture_only')):
                    report.write(field_text(key,value)+'\n')
        for source in sources:
            if not source.is_file():continue
            report.write(f'\n--- {source.name} ---\n')
            with source.open(encoding='utf-8-sig',errors='replace') as data:
                if source.name=='frames.csv':
                    for row in csv.DictReader(data):
                        if row.get('meaning'):
                            report.write(f"{row.get('pc_utc','')} · {row.get('origin_inferred','')} · ID={row.get('id','')} · {row['meaning']}\n")
                    continue
                keeps=untranslated=0
                for n,line in enumerate(data,1):
                    if '"command": "KEEP ' in line:
                        keeps+=1
                        continue
                    text = describe(line)
                    if text:
                        report.write(f'{n:>6}  {text}\n')
                    elif line.strip() and not line.startswith(('t_ms,event,','elapsed_ms,event,')):
                        untranslated+=1
                if keeps:report.write(f'另有 {keeps} 条周期心跳，完整记录见 {source.name}。\n')
                if untranslated:report.write(f'另有 {untranslated} 行未生成中文释义（如启动说明或原始数据），请查看原文件。\n')
    return output


@contextmanager
def capture_notes(folder, notify, name, *, final=None):
    """Write only after the original files and serial session have closed."""
    status=None
    try:
        yield
    except Exception as exc:
        status='采集或实验中断：'+str(exc)
        raise
    finally:
        try:
            result_file=folder/'result.json'
            result=json.loads(result_file.read_text(encoding='utf-8-sig')) if result_file.is_file() else None
            if final is not None:result=final if result is None else result
            path=export_notes(folder/'中文日志说明.log',
                              [folder/n for n in ('board.log','commands.jsonl','pc-frames.jsonl','frames.csv')],
                              status=status,result=result,name=name)
        except (OSError,ValueError) as exc:
            notify('中文说明保存失败，原始日志仍在：'+str(exc))
        else:
            notify('中文日志说明：'+str(path))


def show_legend(parent):
    import tkinter as tk
    from tkinter import scrolledtext
    previous=parent.grab_current()
    dialog=tk.Toplevel(parent)
    dialog.title('PICO · 中文日志标志说明')
    dialog.transient(parent)
    dialog.geometry('840x620')
    box=scrolledtext.ScrolledText(dialog, wrap='word',padx=14,pady=10)
    box.pack(fill='both',expand=True)
    box.insert('end', LEGEND+'\n--- 常见状态 ---\n'+'\n'.join(f'{k}：{v}' for k,v in STATES.items())+
               '\n\n--- 常见停机及失败原因 ---\n'+'\n'.join(f'{k}：{v}' for k,v in REASONS.items()))
    box.configure(state='disabled')

    def close(_event=None):
        dialog.destroy()
        if previous and previous.winfo_exists():
            previous.grab_set()

    dialog.protocol('WM_DELETE_WINDOW',close)
    dialog.bind('<Escape>',close)
    if previous:
        dialog.wait_visibility()
        dialog.grab_set()
    dialog.focus_set()