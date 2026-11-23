from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiment_log import capture_notes, describe, export_notes
from log_model import parse_record


class ExperimentLogTests(unittest.TestCase):
    def test_distinguishes_submit_completion_and_reply(self):
        self.assertIn('尚未证明上总线', describe('12,TX_SUBMIT,EXT,0x123,1,01'))
        self.assertIn('不能代替目标设备', describe('15,TX_DONE,FDCAN3,EXT,DATA,0x123,1,01'))
        self.assertIn('还需校验', describe('17,RX,FDCAN3,EXT,DATA,0x321,1,01'))
        self.assertIn('不能据此确认 CAN 发送完成', describe('{"event":"serial_submitted","id":"0x321"}'))

    def test_tuning_preserves_actual_and_target_units(self):
        text = describe('# TUNE_SAMPLE,t_ms=1500,id=2,mode=POS,accepted_seq=8,applied_seq=7,'
                        'command_angle_mdeg=-2000,actual_angle_mdeg=-1250,iq_mA=250,limit_mA=500,velocity_mrad_s=300')
        for piece in ('板端受理序号=8', '读回确认序号=7', '电脑要求相对角度（°）=-2',
                      '实测相对角度（°）=-1.25', 'Iq 电流（A）=0.25', '设定限流（A）=0.5', '实测速度（rad/s）=0.3'):
            self.assertIn(piece, text)

    def test_zero_error_flags_not_marked_as_failure(self):
        normal = '# ENABLE_STATE,t_ms=50,state=STOPPING,stop_confirmed=0,stop_unconfirmed=0,error=0'
        self.assertEqual(parse_record(normal, 1).level, 'normal')
        self.assertEqual(parse_record(normal.replace('error=0', 'error=1'), 2).level, 'error')
        self.assertEqual(parse_record(normal.replace('stop_unconfirmed=0', 'stop_unconfirmed=1'), 3).level, 'warning')
        self.assertIn('结束时未确认停机', describe('# TUNE_RESULT,result=ERROR,reason=HOST_TIMEOUT,stop_confirmed=0'))

    def test_archives_even_on_interruption_without_touching_raw(self):
        original = b'# HEALTH,t_ms=12,lec=7,rx=0\r\n'
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = folder / 'board.log'
            messages = []
            with self.assertRaisesRegex(RuntimeError, 'serial closed'):
                with capture_notes(folder, messages.append, 'CAN 测试'), raw.open('wb') as file:
                    file.write(original)
                    raise RuntimeError('serial closed')
            self.assertEqual(raw.read_bytes(), original)
            notes = (folder / '中文日志说明.log').read_text(encoding='utf-8-sig')
            self.assertIn('采集或实验中断', notes)
            self.assertIn('CAN 健康统计', notes)
            self.assertTrue(messages[0].startswith('中文日志说明：'))

    def test_capture_only_does_not_display_fail(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / 'report.log'
            export_notes(path, (), result={'capture_only': True, 'pass': False, 'message': '采集完成'})
            report = path.read_text(encoding='utf-8-sig')
            self.assertIn('本次仅采集', report)
            self.assertNotIn('本项验收：未通过', report)
