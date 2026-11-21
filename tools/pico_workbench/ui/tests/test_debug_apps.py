import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog
import debug_apps

class VendorLauncherTests(unittest.TestCase):
    def test_paths_with_spaces_are_launched_as_one_argument(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(catalog,'STATE',Path(folder)):
            exe=Path(folder)/'vendor tool.exe';exe.write_bytes(b'MZ')
            debug_apps.save({'waveshare':str(exe),'robstride':''})
            with patch.object(debug_apps.tools,'WINDOWS',True),patch.object(debug_apps.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(debug_apps.tools,'environment',return_value={}),patch.object(debug_apps.tools,'spawn') as spawn:
                self.assertEqual(debug_apps.launch('waveshare'),str(exe))
                self.assertEqual(spawn.call_args.args[0],[str(exe)])
                self.assertEqual(spawn.call_args.kwargs['cwd'],str(exe.parent))
    def test_missing_app_never_starts_another_process(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(catalog,'STATE',Path(folder)):
            catalog.write(debug_apps.settings_path(),{'waveshare':str(Path(folder)/'missing.exe')})
            with patch.object(debug_apps.tools,'spawn') as spawn,self.assertRaisesRegex(ValueError,'未找到'):
                debug_apps.launch('waveshare')
            spawn.assert_not_called()
    def test_invalid_path_does_not_overwrite_saved_settings(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(catalog,'STATE',Path(folder)):
            debug_apps.save({'waveshare':'','robstride':''})
            before=debug_apps.settings_path().read_bytes()
            with self.assertRaises(ValueError):debug_apps.save({'waveshare':str(Path(folder)/'missing.exe')})
            self.assertEqual(debug_apps.settings_path().read_bytes(),before)

if __name__=='__main__':unittest.main()
