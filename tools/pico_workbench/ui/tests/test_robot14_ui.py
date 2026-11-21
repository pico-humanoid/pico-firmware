import time
import tkinter as tk
from unittest.mock import Mock, patch
import unittest

import robot14_model as model
from robot14_tuning import Robot14Panel
from test_robot14_model import node, state


class Robot14UiTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw()
        self.portpatch=patch('robot14_tuning.ports',return_value=[]);self.portpatch.start()
        self.panel=Robot14Panel(self.root)
        self.panel.window.withdraw()

    def tearDown(self):
        if not self.panel.closed:self.panel.destroy()
        self.portpatch.stop()
        self.root.destroy()

    def test_safe_layout(self):
        p=self.panel
        self.assertEqual(len(p.table.get_children()),14)
        for mid in range(1,15):
            values=p.table.item(str(mid),'values')
            bus,model_name=model.topology(mid)
            self.assertEqual(values[:3],(str(mid),f'CAN{bus}',model_name))
        self.assertIsNone(p.worker)
        self.assertFalse(p.operator.get())
        for button in (p.enable_button,p.enable_all_button,p.apply_button,p.disable_button,p.stop_button):
            self.assertEqual(str(button['state']),'disabled')

    def test_edit_and_selection_do_not_apply(self):
        p=self.panel;p.worker=Mock();p.connected=True
        for value in p.values:value.set('0.2')
        self.assertFalse(p.worker.submit.called)
        p.motor.set('14');p.selected()
        self.assertEqual([v.get() for v in p.values],['0']*5)
        p.worker.submit.assert_called_once_with('select',14)

    def test_telemetry_stale_and_fault_rendering(self):
        p=self.panel;now=time.monotonic();p.connected=True
        p.event('node',model.decode_node(node(1,11)[3],100,now));p.update_table(now)
        self.assertIn('ACTIVE',p.table.item('1','values')[3])
        self.assertEqual(p.table.item('1','values')[4],'0.000')
        p.update_table(now+.31)
        self.assertIn('过期',p.table.item('1','values')[3])
        self.assertEqual(p.table.item('1','values')[4],'—')
        p.draw(now)
        self.assertTrue(p.scope.find_all())

    def test_enable_requires_hardware_checkbox(self):
        p=self.panel;p.worker=Mock()
        with patch('robot14_tuning.messagebox.showwarning') as warn:
            p.enable();warn.assert_called_once()
        self.assertFalse(p.worker.submit.called)

    def test_reset_requires_confirmation(self):
        p=self.panel
        with patch('robot14_tuning.messagebox.askyesno',return_value=False):
            p.reset_mcu()
        self.assertFalse(p.resetting)
        with patch('robot14_tuning.messagebox.askyesno',return_value=True), \
             patch('robot14_tuning.threading.Thread') as th:
            p.reset_mcu()
        self.assertTrue(p.resetting)
        th.return_value.start.assert_called_once()

    def test_enable_all_requires_safety_and_queues_ready(self):
        p=self.panel;p.worker=Mock();now=time.monotonic()
        for mid in (1,2): p.event('node',model.decode_node(node(mid)[3],100,now))
        with patch('robot14_tuning.messagebox.showwarning') as warn:
            p.enable_all();warn.assert_called_once()
        self.assertFalse(p.worker.submit.called)
        p.operator.set(True)
        with patch('robot14_tuning.messagebox.askyesno',return_value=True) as ask:
            p.enable_all()
        self.assertIn('ID1',ask.call_args.args[1]);self.assertIn('ID2',ask.call_args.args[1])
        p.worker.submit.assert_called_once_with('enable_all',[1,2],10.0)

    def test_explicit_confirmation_zero_enable(self):
        p=self.panel;p.worker=Mock();p.operator.set(True);p.motor.set('14')
        with patch('robot14_tuning.messagebox.askyesno',return_value=True) as ask:
            p.enable();self.assertIn('CAN3 / RS10P / ID14',ask.call_args.args[1])
        p.worker.submit.assert_called_once_with('enable',14,10.0)

    def test_health_invalid_is_not_zero_volts(self):
        p=self.panel
        c=model.Controller(0,nonce=1);c.token=123;c.receive(state(),0)
        p.event('state',c.events[-1][1])
        self.assertIn('无有效电压',p.health_text.get())
        self.assertNotIn('0.00 V',p.health_text.get())

    def test_error_survives_close(self):
        p=self.panel;p.event('error','固件不匹配');p.event('closed','已关闭')
        self.assertIn('固件不匹配',p.status.get())

    def test_old_window_frontdoor_and_desktop_route(self):
        from native import Desktop
        with patch.object(self.root,'after',return_value=None):
            d=Desktop(self.root)
        d.refresh_profiles('Robot14')
        p=d.open_motor_enable('tuning');p.window.withdraw()
        self.assertIsInstance(p,Robot14Panel);self.assertIsNone(p.worker)
        p.destroy()
        from motor_tuning import TuningPanel
        old=TuningPanel(self.root);old.window.withdraw()
        old.open_robot14()
        child=old.robot14_panel;child.window.withdraw()
        self.assertIsInstance(child,Robot14Panel)
        child.destroy();old.destroy()


if __name__=='__main__':unittest.main()
