import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import platform_tools as tools
class LinuxToolTests(unittest.TestCase):
 def test_linux_reset_has_serial_and_no_implicit_program(self):
  with patch.object(tools,'WINDOWS',False),patch.object(tools,'tool',side_effect=lambda n:'/usr/bin/openocd' if n=='openocd' else None):
   cmd=tools.reset_command('ABC0123');self.assertIn('adapter serial ABC0123',cmd);self.assertIn('init; reset run; shutdown',cmd)
   self.assertFalse(any('program ' in part for part in cmd))
   with self.assertRaises(ValueError):tools.reset_command('ABC;reset')
 def test_linux_flash_quotes_paths_and_verifies(self):
  with tempfile.TemporaryDirectory(prefix='PICO test ') as d,patch.object(tools,'WINDOWS',False),patch.object(tools,'tool',side_effect=lambda n:'/usr/bin/openocd' if n=='openocd' else None):
   path=Path(d)/'firmware name.elf';path.touch();cmd=tools.flash_command('ABC0123',path)
   self.assertEqual(cmd[-1],'program {'+path.resolve().as_posix()+'} verify reset exit')
 def test_probe_selection_is_explicit(self):
  ports=[SimpleNamespace(vid=0x0483,pid=0x374B,serial_number='ONE'),SimpleNamespace(vid=0x1234,pid=0x374B,serial_number='OTHER')]
  with patch('serial.tools.list_ports.comports',return_value=ports):self.assertEqual(tools.stlink_serials(),['ONE'])
if __name__=='__main__':unittest.main()
