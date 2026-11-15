"""Assemble relocatable Ubuntu 24.04 build/flash tools from verified CI inputs."""
import argparse,json,os,re,shutil,subprocess
from pathlib import Path

def bundle(package,arm):
 tools=package/'tools';tools.mkdir(exist_ok=True);bin_dir=tools/'bin';bin_dir.mkdir(exist_ok=True);libs=tools/'lib';libs.mkdir(exist_ok=True);licenses=tools/'licenses';licenses.mkdir(exist_ok=True)
 compiler=tools/'stm32cube/bundles/gnu-tools-for-stm32/14.3.rel1'
 shutil.copytree(arm,compiler,symlinks=True)
 binaries=[]
 for name in ['cmake','ctest','cpack','ninja','openocd']:
  source=Path('/usr/bin')/name;folder='cmake' if name in ('cmake','ctest','cpack') else name;target=tools/folder/'bin'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);binaries.append(source)
  script='#!/usr/bin/env bash\nset -euo pipefail\nroot="$(cd -- "$(dirname -- "$0")/.." && pwd)"\nexport LD_LIBRARY_PATH="$root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\nexec "$root/'+folder+'/bin/'+name+'" "$@"\n'
  (bin_dir/name).write_text(script,encoding='utf-8');(bin_dir/name).chmod(0o755)
 for p in Path('/usr/share').glob('cmake-*'):shutil.copytree(p,tools/'cmake/share'/p.name,symlinks=True)
 shutil.copytree('/usr/share/openocd/scripts',tools/'openocd/share/openocd/scripts',symlinks=True)
 # ldd includes the transitive host dependencies; retain the host glibc loader.
 packages={'cmake','ninja-build','openocd','fonts-noto-cjk'}
 for source in binaries+list((compiler/'bin').glob('arm-none-eabi-gcc'))+list((compiler/'libexec/gcc/arm-none-eabi').glob('*/cc1')):
  output=subprocess.run(['ldd',str(source)],capture_output=True,text=True).stdout
  for raw in re.findall(r'=>\s+(/\S+)',output):
   lib=Path(raw)
   if lib.name.startswith(('libc.so','libm.so','libpthread.so','libdl.so','librt.so')):continue
   if not (libs/lib.name).exists():shutil.copy2(lib,libs/lib.name)
   owner=subprocess.run(['dpkg-query','-S',str(lib)],capture_output=True,text=True).stdout.split(':',1)[0]
   if owner:packages.add(owner)
 for name in packages:
  source=Path('/usr/share/doc')/name/'copyright'
  if source.exists():shutil.copy2(source,licenses/(name+'.copyright'))
 fonts=tools/'fonts';fonts.mkdir();shutil.copy2('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',fonts/'NotoSansCJK-Regular.ttc')
 (fonts/'fonts.conf').write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir prefix="relative">.</dir></fontconfig>',encoding='utf-8')
 # Distribute the Ubuntu OpenOCD source and distro patch archive with the binary.
 sources=tools/'sources';sources.mkdir();subprocess.run(['apt-get','source','--download-only','openocd'],cwd=sources,check=True)
 (licenses/'SOURCE_URLS.txt').write_text('Arm GNU Toolchain 14.3.rel1 (original licenses retained): https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads\nOpenOCD: exact Ubuntu source and patches in ../sources/\nCMake: https://cmake.org/download/\nNinja: https://github.com/ninja-build/ninja\nNoto CJK: https://github.com/notofonts/noto-cjk\n',encoding='utf-8')
 versions={name:subprocess.run([str(bin_dir/name),'--version'],capture_output=True,text=True).stdout.splitlines()[:1] for name in ('cmake','ninja','openocd')}
 manifest=json.loads((package/'bundle.json').read_text());manifest.update(development_tools_bundled=True,programmer_backend='OpenOCD',toolchain='Arm GNU 14.3.rel1',tool_versions=versions,editors_bundled=False,usb_hardware_validation='not_run');(package/'bundle.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 print('Bundled Linux compiler, CMake, Ninja, OpenOCD, host libraries and CJK font',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('arm_toolchain',type=Path);a=p.parse_args();bundle(a.package.resolve(),a.arm_toolchain.resolve())
