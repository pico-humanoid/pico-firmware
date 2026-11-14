import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog
import workspace
import platform_tools as tools
from motor_enable import validate_banner,parse_state

class EnableExperimentTests(unittest.TestCase):
    def test_profiles_bind_single_target_and_correct_workspace(self):
        for mode,ident,model in [('RS00-Enable-CAN1',2,'RS00'),('RS10P-Enable-CAN1',1,'RS10P')]:
            p=catalog.profile(mode)
            self.assertEqual(p['cmake_options']['PICO_ENABLE_MOTOR_ID'],ident)
            self.assertEqual(p['cmake_options']['PICO_ENABLE_MODEL'],model)
            self.assertIn('-DPICO_APP=MotorEnable',tools.build_commands(mode)[0])
            _,entry=workspace.prepare(mode);self.assertEqual(entry.name,'motor_enable_app.c')
    def test_wrong_target_model_channel_and_old_firmware_cannot_arm(self):
        p=catalog.profile('RS00-Enable-CAN1')
        banner='# PICO_MOTOR_ENABLE=1; channel=FDCAN1 bitrate=1000000 model=RS00 motor_id=2 host_id=253'
        self.assertTrue(validate_banner(banner,p))
        for wrong in [banner.replace('motor_id=2','motor_id=1'),banner.replace('RS00','RS10P'),banner.replace('FDCAN1','FDCAN3'),banner.replace('1000000','500000')]:
            with self.assertRaises(ValueError):validate_banner(wrong,p)
        self.assertFalse(validate_banner('# PICO device-read v1; READ ONLY MOTOR',p))
    def test_state_requires_explicit_confirmation_fields(self):
        state=parse_state('# ENABLE_STATE,state=READY,id=2,enable_confirmed=0,stop_confirmed=1,error=0')
        self.assertEqual(state['state'],'READY');self.assertEqual(state['enable_confirmed'],'0')
        self.assertIsNone(parse_state('1000,TX_DONE,FDCAN1,EXT,DATA,0x0300FD02,8,00 00 00 00 00 00 00 00'))

if __name__=='__main__':unittest.main()
