import unittest
from unittest.mock import patch
import catalog
import motor_enable as m
import workspace
import platform_tools as tools
from trajectory_plot import TrajectoryData

BANNER='# PICO_MOTOR_SYNC_POSITION=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 host_id=253 trajectory=QUINTIC_V1 angle1_deg=5 angle2_deg=-3 cycles=5 segment_ms=2000 duration_ms=40000 target_period_ms=50 max_enable_ms=90000 host_timeout_ms=500 speed_limit_rad_s=0.2 current_limit_A=0.5 tracking_peak_deg=2 tracking_rms_deg=1 arrival_policy=POSITION_WINDOW_V3 tx_policy=BOUNDED_RETRY_V1 tx_deadline_ms=300'

class SyncPositionTests(unittest.TestCase):
    def test_profile_workspace_and_banner_contract(self):
        p=catalog.profile('Motors-Sync-Position')
        self.assertIn('-DPICO_APP=MotorSyncPosition',tools.build_commands(p['id'])[0])
        with patch.object(tools,'tool',return_value=None):_,entry=workspace.prepare(p['id'])
        self.assertEqual(entry.name,'motor_sync_position_app.c')
        self.assertTrue(m.validate_banner(BANNER,p))
        for old,new in [('cycles=5','cycles=10'),('target_period_ms=50','target_period_ms=500'),('segment_ms=2000','segment_ms=200'),('tracking_peak_deg=2','tracking_peak_deg=20'),('BOUNDED_RETRY_V1','SINGLE_ATTEMPT_V1'),('QUINTIC_V1','POSITION_WINDOW_V3'),('POSITION_WINDOW_V3','POSITION_WINDOW_V2')]:
            with self.assertRaises(ValueError):m.validate_banner(BANNER.replace(old,new),p)
        with self.assertRaises(ValueError):m.validate_banner(BANNER,catalog.profile('Motors-Independent-Position'))
    def test_reference_and_error_are_board_samples_with_own_origins(self):
        d=TrajectoryData();d.feed(BANNER)
        self.assertTrue(d.feed('# SYNC_POSITION_ORIGIN,id=1,position_urad=5000000'))
        self.assertEqual(d.origin[1],5)
        self.assertTrue(d.feed('# SYNC_POSITION_SAMPLE,t_ms=1000,id=1,reference_urad=87266,actual_urad=86000,error_urad=-1266'))
        self.assertAlmostEqual(d.points[1,'reference'][-1][1],5,places=3)
        self.assertLess(d.points[1,'error'][-1][1],0)
        self.assertFalse(d.feed('# SYNC_POSITION_SAMPLE,t_ms=nan,id=1,reference_urad=0,error_urad=0'))
        self.assertEqual(len(d.points[1,'error']),1)
        d.feed(BANNER);self.assertFalse(d.rows())
    def test_two_states_required_for_group_ready_and_stopped(self):
        a=m.parse_state('# SYNC_POSITION_STATE,state=READY,id=1,error=0,stop_confirmed=1')
        self.assertEqual(m.group_state({'1':a})['state'],'WAIT_BOTH')
        self.assertEqual(m.group_state({'1':a,'2':dict(a,id='2')})['stop_confirmed'],'1')
