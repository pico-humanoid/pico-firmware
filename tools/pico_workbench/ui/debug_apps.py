"""Launch installed vendor tools; paths can be changed without editing code."""
import os
from pathlib import Path
import subprocess
import catalog
import platform_tools as tools

LABELS={'waveshare':'微雪 USB-CAN','robstride':'灵足电机调试'}

def settings_path():
    return catalog.STATE/'debug_apps.json'

def paths():
    saved=catalog.load(settings_path(),{})
    defaults={
        'waveshare':str(tools.ROOT.parent/'USBCANV2.12_Chinese/USBCANV2.12.exe'),
        'robstride':str(Path(os.environ.get('LOCALAPPDATA',''))/'RobStride/motor_toolV14L/motor_tool.exe'),
    }
    result={}
    for key in LABELS:
        value=Path(saved.get(key,defaults[key]))
        if not value.is_absolute():value=tools.ROOT.parent/value
        result[key]=str(value)
    return result

def save(values):
    cleaned={}
    for key in LABELS:
        value=str(values.get(key,'')).strip()
        if value and not Path(value).is_file():raise ValueError(LABELS[key]+'的程序文件不存在。')
        cleaned[key]=value
    catalog.write(settings_path(),cleaned)

def launch(key):
    if key not in LABELS:raise ValueError('未知调试软件。')
    executable=Path(paths()[key])
    if not executable.is_file():raise ValueError('未找到'+LABELS[key]+'，请在“更多 → 调试软件路径”中设置。')
    if not tools.WINDOWS and executable.suffix.lower()=='.exe':
        raise ValueError('当前设置是Windows程序，请在调试软件路径中选择适用于本系统的启动程序。')
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if tools.WINDOWS else {'start_new_session':True}
    tools.spawn([str(executable)],cwd=str(executable.parent),env=tools.environment(),
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**options)
    return str(executable)
