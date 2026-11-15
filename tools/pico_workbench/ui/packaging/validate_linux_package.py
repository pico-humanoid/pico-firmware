"""Run the packaged programs after relocation; no serial ports or hardware opened."""
import argparse,json,os,shutil,subprocess,tempfile,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('package',type=Path);a=p.parse_args();original=a.package.resolve()
 with tempfile.TemporaryDirectory(prefix='PICO relocation ',dir=original.parent) as temp:
  relocated=Path(temp)/'开发控制台'/original.name;relocated.parent.mkdir();shutil.move(original,relocated)
  try:
   env=dict(os.environ,PICO_PROJECT_ROOT=str(relocated/'project'),PICO_TOOLS_ROOT=str(relocated/'tools'),PATH=str(relocated/'tools/bin')+os.pathsep+os.environ['PATH'])
   env['FONTCONFIG_FILE']=str(relocated/'tools/fonts/fonts.conf')
   # The launcher scripts set these; a re-export must not retain parent paths.
   env['CUBE_BUNDLE_PATH']=str(relocated/'tools/stm32cube/bundles')
   env['CMSIS_PACK_ROOT']=str(relocated/'tools/stm32cube/packs')
   def run(args):
    result=subprocess.run([str(v) for v in args],env=env,cwd=relocated,capture_output=True,text=True,timeout=600)
    if result.returncode:
     print(result.stdout,flush=True);print(result.stderr,flush=True);result.check_returncode()
    return result
   status=json.loads(run([relocated/'PICOCLI','check']).stdout)
   if not status['ready'] or status.get('programmer_backend')!='OpenOCD':raise RuntimeError('Bundled developer tools not ready: '+str(status))
   smoke=run([relocated/'PICOCLI','self-test']);print(smoke.stdout,flush=True)
   for name in ('cmake','ninja','openocd'):run([relocated/'tools/bin'/name,'--version'])
   if 'NotoSansCJK' not in run(['fc-match','-f','%{file}','Noto Sans CJK SC']).stdout:raise RuntimeError('Bundled Chinese font not usable')
   built={}
   for profile in ('RS10P-Tuning','RS00-Tuning','Motors-Tuning'):
    log=run([relocated/'PICOCLI','build',profile]);built[profile]='PASS';print(profile,'frozen CLI ARM build PASS',flush=True)
   export_file=Path(temp)/'PICO 再次迁移.tar.gz'
   run([relocated/'PICOCLI','export',export_file])
   if not export_file.exists():raise RuntimeError('Linux re-export did not create an archive')
   export_file.unlink();Path(str(export_file)+'.sha256').unlink()
   # Debugger reset and flash command construction is tested; hardware is absent.
   report={'platform':'Ubuntu 24.04 x86_64','relocation_with_spaces_and_chinese':'PASS','frozen_native_gui_self_test':'PASS','bundled_tool_detection':status['tools'],'programmer_backend':'OpenOCD','arm_builds':built,'native_linux_reexport':'PASS','hardware_flash':'NOT_RUN','motor_motion':'NOT_RUN','editors':'use separately installed Linux VS Code / STM32CubeMX'}
   (relocated/'UBUNTU_VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
   # Do not ship build caches with runner-specific absolute paths.
   project=relocated/'project'
   for cache in (project/'build',project/'projects/pico-firmware/firmware/PICO_CAN/build'):
    if cache.exists():
     if not cache.resolve().is_relative_to(project.resolve()):raise RuntimeError('Invalid build cache path')
     shutil.rmtree(cache)
  finally:shutil.move(relocated,original)
 sys.path.insert(0,str(Path(__file__).parent));from build_distribution import archive
 archive(original);print('Relocation and three packaged ARM builds validated; archive refreshed',flush=True)
if __name__=='__main__':main()
