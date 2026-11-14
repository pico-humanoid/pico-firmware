"""Headless operator for the same stopped diagnostic session as the native UI.

Does not flash or enable. --verify explicitly requests the stopped loc_ref echo;
the firmware still enforces STOP, UID, mode and heartbeat interlocks.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ui'))
import catalog
from position_diagnostic import DiagnosticData,PositionDiagnosticPanel,comports

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=PositionDiagnosticPanel.profile_ids,default='RS10P-Position-Diag')
    parser.add_argument('--port',default='COM5' if sys.platform=='win32' else None)
    parser.add_argument('--duration',type=float,default=30)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    matches=[p for p in comports() if p.vid==0x0483 and p.serial_number and (not args.port or p.device==args.port)]
    if len(matches)!=1:raise RuntimeError('需要唯一匹配的ST-LINK日志串口。')
    panel=PositionDiagnosticPanel.__new__(PositionDiagnosticPanel)
    panel.events=queue.Queue();panel.commands=queue.Queue();panel.finish=threading.Event()
    failures=[]
    def worker():
        try:panel.worker(matches[0],catalog.profile(args.profile))
        except Exception as exc:failures.append(str(exc))
        finally:panel.events.put(('finished',''))
    thread=threading.Thread(target=worker,daemon=True);thread.start()
    data=DiagnosticData();folder=None;session=False;verify_sent=False;start=time.monotonic();end=None
    try:
        while thread.is_alive() or not panel.events.empty():
            now=time.monotonic()
            if end is None and now-start>=args.duration:panel.finish.set();end=now
            if end is not None and now-end>6:raise RuntimeError('诊断线程未按时退出；请检查原始日志及停机状态。')
            try:kind,value=panel.events.get(timeout=.1)
            except queue.Empty:continue
            if kind=='folder':folder=Path(value);print('日志：'+value,flush=True)
            elif kind=='session':session=value
            elif kind=='text':
                data.feed(value)
                if value.startswith('#'):print(value,flush=True)
                if args.verify and session and data.can_verify() and not verify_sent and not panel.finish.is_set():
                    verify_sent=True;panel.commands.put('VERIFY');print('确认停机、UID和模式后，请求三轮当前位置写回验证。',flush=True)
                if data.result and end is None:panel.finish.set();end=time.monotonic()
            elif kind=='finished':break
    finally:
        panel.finish.set();thread.join(3)
    result={'time':datetime.now().isoformat(),'profile':args.profile,'port':matches[0].device,'verify_requested':args.verify,'verify_sent':verify_sent,'state':data.state,'uid':data.uid,'version':data.version,'values':{f'0x{k:04X}':data.value(k) for k in data.values},'result':data.result,'echo':data.echo,'errors':failures,'no_enable':True}
    if folder:(folder/'operator_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 0 if not failures and data.state.get('stop_confirmed')=='1' and (not args.verify or data.result and data.result.get('result')=='CONSISTENT') else 1

if __name__=='__main__':raise SystemExit(main())
