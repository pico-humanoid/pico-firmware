"""Guard the selected experiment's firmware and transport routing."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog
import engine
import platform_tools as tools
from native import Desktop

class ExternalCAN3Tests(unittest.TestCase):
    def test_build_uses_can3_project_and_app(self):
        with patch.object(tools,'tool',side_effect=lambda name:'/tools/'+name):
            config,_=tools.build_commands('External')
        self.assertEqual(catalog.profile('External')['cmake_options']['PICO_APP'],'Can3Bench')
        self.assertIn('-DPICO_APP=Can3Bench',config)
        self.assertEqual(Path(config[config.index('-S')+1]),tools.ROOT/'projects/pico-firmware/firmware/PICO_CAN')
        self.assertNotEqual(tools.image_for('External'),tools.ROOT/'build/External/PICO_CAN.elf')
    def test_test_button_opens_at_window_without_legacy_sender(self):
        desktop=Desktop.__new__(Desktop)
        desktop.root=object();desktop.tip=Mock();desktop.manager=Mock()
        desktop.profile=lambda:catalog.profile('External');desktop.mode_id=lambda:'External'
        with patch('can_pc_test.PCTest') as window:
            desktop.start('usbcan')
            window.assert_called_once_with(desktop.root)
            self.assertEqual(window.return_value.profile,'External')
        desktop.manager.start.assert_not_called()
    def test_legacy_transport_cannot_send_on_can3_profile(self):
        with self.assertRaisesRegex(ValueError,'灵足AT'):
            engine.Manager()._do_usbcan(engine.Job('usbcan','External','TEST'))
    def test_board_capture_does_not_use_old_standard_frame_verdict(self):
        manager=engine.Manager();job=engine.Job('board','External','TEST')
        with patch.object(manager,'_do_stream',return_value={'capture_only':True}) as stream:
            self.assertEqual(manager._do_board(job),{'capture_only':True})
            stream.assert_called_once_with(job)

if __name__=='__main__':unittest.main()
