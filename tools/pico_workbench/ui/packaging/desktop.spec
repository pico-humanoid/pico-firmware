import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(os.environ['PICO_SOURCE_ROOT'])
entry = Path(SPECPATH) / 'entry.py'
paths = [root / 'ui', root / 'ui/vendor', root / 'scripts', root / 'scripts/linux']
a = Analysis([str(entry)], pathex=[str(p) for p in paths], binaries=[], datas=[],
             hiddenimports=['native', 'package_cli', 'build_selected'] + collect_submodules('serial'),
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['numpy', 'matplotlib', 'IPython', 'pytest', 'conda', 'conda_pack'], noarchive=False)
pyz = PYZ(a.pure)
programs = []
for name, console in [('PICOConsole', False), ('PICOLogViewer', False), ('PICOCLI', True)]:
    programs.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name=name,
                        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
                        console=console, disable_windowed_traceback=False))
coll = COLLECT(*programs, a.binaries, a.datas, strip=False, upx=False, name='PICO-Workbench')
