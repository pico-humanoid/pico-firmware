"""One-shot, read-only RS10P diagnostic through the board's ST-LINK only."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ui'),str(ROOT/'ui/vendor')]
import catalog
import platform_tools as tools
import serial
from serial.tools.list_ports import comports

PROFILE='RS10P-DMATrace-1M'
SERIAL='002000303335511635383531'

def board_port():
    ports=[p for p in comports() if p.vid==0x0483 and p.serial_number==SERIAL]
    if len(ports)!=1:
        raise RuntimeError('未检测到这块开发板的 ST-LINK 日志串口。请保持板载 ST-LINK USB 连接后重试。')
    return ports[0].device

def main():
    parser=argparse.ArgumentParser(description='CAN3 RS10P DMA首帧诊断：仅板载ST-LINK，不使用USB-CAN')
    parser.add_argument('--check',action='store_true',help='仅检查连接及配置，不编译或烧录')
    args=parser.parse_args()
    p=catalog.profile(PROFILE)
    expected={'PICO_APP':'Motor','PICO_DEVICE_BITRATE':1000000,'PICO_MOTOR_COUNT':1,
              'PICO_MOTOR1_ID':'0x7F','PICO_MOTOR_HOST_ID':'0xFD',
              'PICO_CAN_PIN_TRACE':True,'PICO_CAN_DMA_TRACE':True}
    if any(p['cmake_options'].get(k)!=v for k,v in expected.items()):
        raise RuntimeError('诊断配置与确认的RS10P参数不符，已停止。')
    port=board_port()
    programmer=tools.tool('programmer')
    if not programmer:raise RuntimeError('未找到 STM32CubeProgrammer。')
    print('ST-LINK日志串口：'+port,flush=True)
    if args.check:
        print('配置检查通过；未编译、未烧录。',flush=True)
        return 0
    out=ROOT/'logs'/('can3-dma-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(parents=True)
    print('日志目录：'+str(out),flush=True)
    env=tools.environment();env['PICO_PROJECT_ROOT']=str(ROOT)
    def run(command,name):
        result=subprocess.run([str(v) for v in command],cwd=ROOT,env=env,
            capture_output=True,timeout=180)
        data=result.stdout+result.stderr
        (out/name).write_bytes(data)
        text=data.decode('utf-8',errors='replace')
        print(text[-1800:],flush=True)
        if result.returncode:raise RuntimeError('操作失败，现场已保存：'+name)
        return text
    run([sys.executable,ROOT/'ui/package_cli.py','build',PROFILE],'build.log')
    # Re-enumerate after compilation; do not reuse an obsolete COM number.
    port=board_port()
    base=[programmer,'-c','port=SWD','sn='+SERIAL,'freq=1000']
    with serial.Serial(port,115200,timeout=.15) as handle:
        run(base+['mode=HOTPLUG','-u','0x08000000','0x80000',out/'board-before.bin'],'backup.log')
        handle.reset_input_buffer()
        image=tools.image_for(PROFILE)
        text=run(base+['mode=UR','-w',image,'-v','-rst'],'flash.log')
        if 'Download verified successfully' not in text:raise RuntimeError('未确认烧录校验成功。')
        raw=b'';deadline=time.monotonic()+13
        with (out/'board.log').open('wb') as target:
            while time.monotonic()<deadline:
                data=handle.read(4096);raw+=data;target.write(data);target.flush()
    text=raw.decode('utf-8',errors='replace');print(text,flush=True)
    summary={'profile':PROFILE,'serial':SERIAL,'port':port,'flash_verified':True,
             'dma_banner_seen':'sampler=TIM6_DMA' in text,
             'motor_readings':text.count('# MOTOR,'),'tx_done':text.count(',TX_DONE,'),
             'rx':text.count(',RX,'),'tx_timeout':text.count(',TX_TIMEOUT,'),
             'note':'DMA采样输出不等于电机通信通过；需检查完成时间及实际回复。'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('全部日志已保存：'+str(out),flush=True)
    return 0 if summary['dma_banner_seen'] else 3

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(main())
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        print('已停止：'+str(exc),file=sys.stderr);raise SystemExit(2)
