import unittest
import catalog
from motor_enable import PositionPanel,validate_banner,parse_state
import platform_tools as tools
import workspace

class PositionCycleTests(unittest.TestCase):
    def test_profiles_bind_model_id_and_position_firmware(self):
        for model,ident in [('RS10P',1),('RS00',2)]:
            profile=catalog.profile(model+'-Position-Cycles')
            self.assertEqual(profile['cmake_options']['PICO_ENABLE_MOTOR_ID'],ident)
            self.assertIn('-DPICO_APP=MotorPosition',tools.build_commands(profile['id'])[0])
            _,entry=workspace.prepare(profile['id']);self.assertEqual(entry.name,'motor_position_app.c')
            banner=f'# PICO_MOTOR_POSITION=1; channel=FDCAN1 bitrate=1000000 model={model} motor_id={ident} max_enable_ms=90000 host_timeout_ms=500 cycles=10 angle_deg=5 current_limit_A=0.5 speed_limit_rad_s=0.2 dwell_ms=500 arrival_policy=POSITION_WINDOW_V3'
            self.assertTrue(validate_banner(banner,profile))
            for wrong in [banner.replace('angle_deg=5','angle_deg=50'),banner.replace('cycles=10','cycles=100'),banner.replace('90000','900000'),banner.replace('POSITION_WINDOW_V3','POSITION_WINDOW_V2'),banner.replace('POSITION','SPEED')]:
                with self.assertRaises(ValueError):validate_banner(wrong,profile)
            with self.assertRaises(ValueError):validate_banner(banner,catalog.profile(model+'-Speed-CAN1'))
    def test_progress_is_not_a_pass(self):
        state=parse_state('# POSITION_STATE,state=POSITION_MOVING,cycles_completed=9,waypoints_completed=39,stop_confirmed=0')
        self.assertEqual(state['waypoints_completed'],'39');self.assertEqual(state['stop_confirmed'],'0')
        self.assertEqual(PositionPanel.command,'RUN')
