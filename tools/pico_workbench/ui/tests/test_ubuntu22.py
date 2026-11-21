"""Regression coverage for a clean Ubuntu 22.04 checkout (Python 3.10/CMake 3.22)."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
sys.path.insert(0, str(UI / 'packaging'))
import catalog
import platform_tools as tools
from runtime_paths import firmware_root
import build_distribution as distribution
import install_arm_toolchain as installer
import portable_export
import flash_selected


class Ubuntu22Tests(unittest.TestCase):
    def test_checkout_exposes_real_firmware_and_all_experiments(self):
        firmware = firmware_root()
        self.assertTrue((firmware / 'App/motor_tuning_app.c').is_file())
        for profile in catalog._all_builtins():
            self.assertTrue((Path(profile['project_dir']) / 'CMakeLists.txt').is_file(), profile['id'])
        for app in ('BMS', 'Power', 'Dual'):
            names = {'BMS': 'BMS-Read-500K', 'Power': 'Power-Read-500K', 'Dual': 'Dual-Read-500K'}
            for channel in (1, 2, 3):
                ident = names[app] + ('-CAN' + str(channel) if channel != 3 else '')
                self.assertEqual(catalog.profile(ident)['cmake_options']['PICO_CAN_CHANNEL'], channel)

    def test_exported_layout_takes_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'
            firmware = root / 'projects/pico-firmware/firmware/PICO_CAN'
            firmware.mkdir(parents=True)
            (firmware / 'CMakeLists.txt').touch()
            self.assertEqual(firmware_root(root), firmware)

    def test_cmake_322_configuration_clears_old_app_settings(self):
        with patch.object(tools, 'tool', side_effect=lambda name: '/usr/bin/' + name):
            config, build = tools.build_commands('Motors-Tuning')
        self.assertNotIn('--fresh', config)
        self.assertEqual(config[config.index('-U') + 1], 'PICO_*')
        self.assertIn('-DPICO_APP=MotorTuning', config)
        self.assertIn('-DPICO_TUNE_COUNT=2', config)
        self.assertEqual(build[1], '--build')

    def test_streaming_hash_works_on_python_310(self):
        data = b'Ubuntu 22.04\0' * 100000
        for module in (distribution, installer, portable_export):
            self.assertEqual(module.sha256_stream(io.BytesIO(data)), hashlib.sha256(data).hexdigest())

    def test_archive_roundtrip_and_actual_host_label(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / 'package'
            package.mkdir()
            (package / '测试.txt').write_text('Ubuntu22', encoding='utf-8')
            archive = distribution.archive(package)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertTrue(Path(str(archive) + '.sha256').read_text().startswith(digest))
        if sys.platform == 'linux':
            if 'VERSION_ID="22.04"' in Path('/etc/os-release').read_text():
                self.assertEqual(distribution.linux_platform(), 'Ubuntu-22.04-x86_64')

    def test_flash_refuses_ambiguous_or_wrong_probe(self):
        with patch.object(tools, 'validate_mode'), patch.object(tools, 'image_for') as image, patch.object(tools, 'stlink_serials', return_value=['ONE', 'TWO']), patch.object(flash_selected.subprocess, 'run') as run:
            image.return_value.is_file.return_value = True
            for args in (['Motors-Tuning'], ['Motors-Tuning', 'OTHER']):
                with self.assertRaises(SystemExit), patch('sys.stderr', new=io.StringIO()):
                    flash_selected.main(args)
            run.assert_not_called()

    def test_flash_uses_selected_image_and_explicit_serial(self):
        image = Path('/tmp/selected firmware.elf')
        with patch.object(tools, 'validate_mode'), patch.object(tools, 'image_for', return_value=image), patch.object(Path, 'is_file', return_value=True), patch.object(tools, 'stlink_serials', return_value=['ONE']), patch.object(tools, 'flash_command', return_value=['openocd', 'explicit']) as command, patch.object(tools, 'environment', return_value={}), patch.object(flash_selected.subprocess, 'run') as run:
            self.assertEqual(flash_selected.main(['Motors-Tuning', 'ONE']), 0)
            command.assert_called_once_with('ONE', image)
            run.assert_called_once_with(['openocd', 'explicit'], env={}, check=True)


if __name__ == '__main__':
    unittest.main()
