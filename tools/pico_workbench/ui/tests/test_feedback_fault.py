import unittest
import catalog
from motor_enable import FaultPanel,validate_banner,parse_state,group_state
import platform_tools as tools
import workspace

class FeedbackFaultTests(unittest.TestCase):
    def test_profiles_and_firmware_identity(self):
        for target in (1,2):
            p=catalog.profile(f'Motors-Fault-ID{target}')
            self.assertEqual(p['cmake_options']['PICO_FAULT_TARGET'],target)
            self.assertIn('-DPICO_APP=MotorDualFault',tools.build_commands(p['id'])[0])
            _,entry=workspace.prepare(p['id']);self.assertEqual(entry.name,'motor_dual_speed_app.c')
            banner='# PICO_MOTOR_DUAL_FAULT=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5'
            self.assertTrue(validate_banner(banner,p))
            with self.assertRaises(ValueError):validate_banner(banner.replace('DUAL_FAULT','DUAL_SPEED'),p)
            with self.assertRaises(ValueError):validate_banner(banner,catalog.profile('Motors-Speed-CAN1'))
        self.assertEqual(len(FaultPanel.profile_ids),2)
    def test_individual_timeout_does_not_mean_both_stopped(self):
        a=parse_state('# DUAL_FAULT_STATE,state=STOPPING,id=1,reason=FEEDBACK_TIMEOUT,stop_confirmed=0,error=1')
        b=parse_state('# DUAL_FAULT_STATE,state=DONE,id=2,reason=PEER_STOP,stop_confirmed=1,error=1')
        self.assertEqual(group_state({'1':a,'2':b})['stop_confirmed'],'0')
