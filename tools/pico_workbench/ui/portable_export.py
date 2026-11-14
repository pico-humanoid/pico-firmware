"""Offline export of the current Windows workbench; no device operations."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from runtime_paths import project_root

SKIP={'.git','__pycache__','build','state','node_modules','.pytest_cache','logs','user-data'}
def copy(source,dest):
    shutil.copytree(source,dest,dirs_exist_ok=True,ignore=lambda _,names:[n for n in names if n in SKIP or n.endswith(('.pyc','.pyo'))])

def tools_source(root):
    candidates=[Path(os.environ.get('PICO_TOOLS_ROOT',str(root.parent/'tools'))),
                Path('D:/Desk/2.正在处理文件/PICO/PICO_Workbench/tools')]
    for path in candidates:
        if (path/'stm32cube/bundles').is_dir() and (path/'vscode/Code.exe').is_file() and (path/'STM32CubeMX/MX/STM32CubeMX.exe').is_file():return path
    raise RuntimeError('未找到完整离线开发工具（编译器、烧录器、VS Code、CubeMX），未生成不完整压缩包。')

def profiles_for_export(root):
    path=root/'ui/state/profiles.json'
    profiles=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    for p in profiles:
        project=Path(p['project_dir'])
        if project.is_absolute():
            try:p['project_dir']=project.resolve().relative_to(root.resolve()).as_posix() or '.'
            except ValueError:raise RuntimeError('自定义实验工程在工作区外，请先移入工作区再打包：'+str(project))
    return profiles

def export(destination,progress=lambda text:None):
    if os.name!='nt':raise RuntimeError('当前一键离线ZIP导出支持Windows x64；Ubuntu需使用对应平台构建包。')
    root=project_root();destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('目标文件已存在，请使用新的压缩包名称。')
    destination.parent.mkdir(parents=True,exist_ok=True)
    tools=tools_source(root);profiles=profiles_for_export(root)
    required=['cmake','ninja','gnu-tools-for-stm32','programmer']
    for name in required:
        if not (tools/'stm32cube/bundles'/name).is_dir():raise RuntimeError('缺少开发工具：'+name)
    size=sum(p.stat().st_size for p in tools.rglob('*') if p.is_file())
    if shutil.disk_usage(destination.parent).free<size*2+1024**3:raise RuntimeError('输出磁盘空间不足，需预留离线工具大小的两倍及1GB余量。')
    # Temporary tree is beside the ZIP so a large package never fills C:\Temp.
    with tempfile.TemporaryDirectory(prefix='pico-export-',dir=destination.parent) as temporary:
        work=Path(temporary);bundle=work/'PICO-Workbench-Windows-x64';bundle.mkdir()
        if getattr(sys,'frozen',False):
            progress('复制便携运行环境…')
            runtime=Path(sys.executable).resolve().parent
            for name in ('PICOConsole.exe','PICOCLI.exe','PICOLogViewer.exe'):
                shutil.copy2(runtime/name,bundle/name)
            copy(runtime/'_internal',bundle/'_internal')
        else:
            progress('构建当前控制台运行环境（首次可能需要数分钟）…')
            env=dict(os.environ,PICO_SOURCE_ROOT=str(root))
            command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(work/'dist'),'--workpath',str(work/'build'),str(root/'ui/packaging/desktop.spec')]
            with (work/'build.log').open('w',encoding='utf-8') as log:
                result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError('运行环境构建失败：'+(work/'build.log').read_text(encoding='utf-8')[-2500:])
            copy(work/'dist/PICO-Workbench',bundle)
        progress('复制当前工程与界面…')
        sys.path.insert(0,str(root/'ui/packaging'))
        from build_distribution import seed_project
        seed_project(bundle/'project',root,local=root)
        for name in ('docs',):
            if (root/name).is_dir():copy(root/name,bundle/'project'/name)
        for folder in (root/'outputs').glob('*'):
            if folder.is_dir() and (folder.name.startswith('motor-') or folder.name=='can-periodic'):
                copy(folder,bundle/'project/outputs'/folder.name)
        state=bundle/'project/ui/state';state.mkdir(parents=True,exist_ok=True)
        (state/'profiles.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
        progress('复制离线工具、编辑器和驱动…')
        copy(tools,bundle/'tools')
        clean_settings=bundle/'tools/vscode/data/user-data/User/settings.json';clean_settings.parent.mkdir(parents=True,exist_ok=True)
        clean_settings.write_text(json.dumps({'update.mode':'none','extensions.autoUpdate':False,'workbench.startupEditor':'none'}),encoding='utf-8')
        import debug_apps
        paths={}
        for key,value in debug_apps.paths().items():
            exe=Path(value)
            if exe.is_file():
                target=bundle/'tools/vendor'/key;copy(exe.parent,target)
                paths[key]=str((Path('tools/vendor')/key/exe.name).as_posix())
        (state/'debug_apps.json').write_text(json.dumps(paths,ensure_ascii=False,indent=2),encoding='utf-8')
        for title,exe in [('打开开发控制台','PICOConsole'),('打开日志查看器','PICOLogViewer')]:
            (bundle/(title+'.cmd')).write_text('@echo off\nstart "" "%~dp0'+exe+'.exe"\n',encoding='utf-8')
        (bundle/'检查环境.cmd').write_text('@echo off\n"%~dp0PICOCLI.exe" check\npause\n',encoding='utf-8')
        readme='Windows x64 离线迁移包\n\n解压到可写的短路径，运行“打开开发控制台.cmd”。已含Python/Tk、当前实验工程、编译/烧录工具、VS Code和CubeMX。无需安装Python。\n新电脑缺少USB驱动时，请以管理员权限运行tools/drivers中的对应驱动安装程序，再重新插入设备。首次连接应重新选择ST-LINK串口。\n单机及双机转动必须手动点击开始；本包未执行烧录或使能。\n历史原始日志、账户登录和个人编辑器数据未打包。厂商软件保留原许可，仅用于本地迁移。\nUbuntu请使用Ubuntu对应包，Windows程序不能直接在Ubuntu运行。\n可在本控制台再次点击“一键打包”，无需安装打包器。\n'
        (bundle/'使用说明.txt').write_text(readme,encoding='utf-8-sig')
        shutil.copy2(root/'ui/packaging/THIRD_PARTY_NOTICES.md',bundle/'THIRD_PARTY_NOTICES.md')
        manifest={'created':datetime.now().isoformat(),'platform':'Windows-x64','development_tools_bundled':True,'historical_logs_included':False,'hardware_actions_executed':False,'profile_count':len(__import__('catalog').profiles())}
        (bundle/'bundle.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        progress('检查导出后的环境与界面…')
        env=dict(os.environ,PICO_PROJECT_ROOT=str(bundle/'project'),PICO_TOOLS_ROOT=str(bundle/'tools'))
        for action in ('check','self-test'):
            result=subprocess.run([str(bundle/'PICOCLI.exe'),action],env=env,capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError('便携程序验证失败：'+result.stderr.decode(errors='replace')[-2000:])
            if action=='check':
                info=json.loads(result.stdout.decode('utf-8'))
                if not info['ready'] or not all(Path(p).resolve().is_relative_to(bundle.resolve()) for p in info['tools'].values()):raise RuntimeError('工具仍依赖原电脑路径，打包已中止。')
        progress('正在压缩，请勿关闭控制台…')
        partial=work/'export.zip'
        with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            for path in bundle.rglob('*'):
                if path.is_file():archive.write(path,path.relative_to(work))
        with partial.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        # Replace only a new destination; an unrelated existing file is never overwritten.
        if destination.exists():raise FileExistsError(destination)
        shutil.move(str(partial),destination)
        destination.with_suffix('.zip.sha256').write_text(digest+'  '+destination.name+'\n',encoding='ascii')
    progress('打包完成：'+str(destination));return destination

if __name__=='__main__':export(sys.argv[1],print)
