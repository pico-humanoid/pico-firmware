#!/usr/bin/env python3
"""Analyze a boot-anchored G474 power-reader capture. Never sends device data.
Only declares a read-link window PASS, not a baud migration or physical safety PASS.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct

PARAMS={0x6001:'Can_baud',0x6002:'Com_baud',0x6004:'remoteCtrl',0x6005:'fanspeedCtrl',0x6006:'POWER_ID',0x6007:'soundEffect',0x8001:'currocpt',0x8003:'sdT',0x8004:'arTime'}
ERRORS='invalid query_timeouts query_failures tx_rejected tx_timeout rx_fifo_lost rx_queue_drop rx_read_fail rx_unsupported tx_event_lost tx_event_unknown bus_off'.split()
FRAME=re.compile(r'^(\d+),(TX_SUBMIT|TX_DONE|TX_TIMEOUT|RX),FDCAN1,(EXT|STD),(DATA|RTR),0x([0-9A-F]+),(\d+),(.*)$')
def analyze(path,code,bitrate):
    raw=path.read_bytes(); lines=raw.decode('ascii',errors='replace').splitlines()
    boots=[i for i,s in enumerate(lines) if s.startswith('# PICO device-read v1;')]
    issues=[]
    if not boots: return {'result':'NOT_PASS','issues':['No complete boot header; do not guess around buffered VCP data.']}
    boot=boots[-1]; header=lines[boot]; stop=next((i for i in range(boot+1,len(lines)) if lines[i].startswith('# BAUD_TEST,stage=DRAIN')),len(lines))
    if f'bitrate={bitrate} ' not in header or 'power_id=0xAA' not in header or 'status_order=1' not in header: issues.append('Boot configuration mismatch')
    health=[]
    for i in range(boot+1,stop):
        s=lines[i]
        if s.startswith('# HEALTH,'):
            try: h={k:int(v,0) for k,v in (pair.split('=',1) for pair in s[len('# HEALTH,'):].split(','))}
            except ValueError: continue
            if all(k in h for k in ['t_ms','seen','valid','tec','rec','counters_ok',*ERRORS]): health.append((i,h))
    good=[(i,h) for i,h in health if h['seen']==h['valid']==0xfff]
    if not good: return {'result':'NOT_PASS','issues':['No fully fresh HEALTH yet'],'boot_header':header}
    first=good[0]; last=next(((i,h) for i,h in good if h['t_ms']-first[1]['t_ms']>=60000),good[-1])
    window=[(i,h) for i,h in health if first[0]<=i<=last[0]]
    latest=health[-1][1]
    gate_eligible=not any(latest[k] for k in ERRORS) and latest['seen']==latest['valid']==0xfff and latest['tec']==latest['rec']==0 and latest['counters_ok']==1
    if last[1]['t_ms']-first[1]['t_ms']<60000: issues.append('Less than 60s complete HEALTH window')
    if any(h['seen']!=0xfff or h['valid']!=0xfff or h['tec'] or h['rec'] or h['counters_ok']!=1 or any(h[k] for k in ERRORS) for _,h in health if _<=last[0]): issues.append('Nonzero error counters / invalid freshness / counters unavailable since boot')
    if any(b[1]['t_ms']-a[1]['t_ms']>5500 or b[1]['t_ms']<=a[1]['t_ms'] for a,b in zip(window,window[1:])): issues.append('HEALTH gap or timestamp reversal')
    frames=[]; malformed=[]; samples=[]
    for i in range(boot+1,last[0]+1):
        s=lines[i]; m=FRAME.fullmatch(s)
        if m:
            t,event,fmt,kind,id_,dlc,data=m.groups()
            try: f=dict(line=i+1,t=int(t),event=event,fmt=fmt,kind=kind,id=int(id_,16),dlc=int(dlc),data=bytes.fromhex(data))
            except ValueError: malformed.append(i+1); continue
            if len(f['data'])!=f['dlc']: malformed.append(i+1)
            frames.append(f)
        elif s.startswith('# POWER,'): samples.append(s)
        elif s and not s.startswith(('#','t_ms,')): malformed.append(i+1)
    def category(f):
        typ=f['id']>>24; data=f['data']
        if typ==5: return 'version'
        if typ in (3,4): return 'status0'+str(typ)
        if typ==2: return 'status04' if data==bytes([0xca])+bytes(7) else 'status03'
        if typ==7: return PARAMS.get(int.from_bytes(data[:2],'little'),'unknown')
        return 'unknown'
    def allowed(f):
        return f['fmt']=='EXT' and f['kind']=='DATA' and f['dlc']==8 and f['id']&0xffffff==0xaa and ((f['id']>>24==5 and f['data']==bytes(8)) or (f['id']>>24==2 and f['data'] in (bytes(8),bytes([0xca])+bytes(7))) or (f['id']>>24==7 and int.from_bytes(f['data'][:2],'little') in PARAMS and f['data'][2:]==bytes(6)))
    unsafe=[f['line'] for f in frames if f['event']=='TX_SUBMIT' and not allowed(f)]
    unexpected=[f['line'] for f in frames if f['event']=='RX' and (f['fmt']!='EXT' or f['kind']!='DATA' or f['dlc']!=8 or (f['id']>>16)&255!=0xaa or category(f)=='unknown')]
    counts={e:dict(Counter(category(f) for f in frames if f['event']==e and first[0]+1<f['line']<=last[0]+1)) for e in ['TX_SUBMIT','TX_DONE','RX','TX_TIMEOUT']}
    for e in ['TX_SUBMIT','TX_DONE','RX']:
        if len(counts[e])!=12 or not all(counts[e].values()): issues.append(f'Not all 12 query categories in {e}')
    pending=None; unanswered=[]; orphan=[]; matched=0; tx=Counter(); done=Counter()
    for f in frames:
        if f['event']=='TX_SUBMIT':
            if pending: unanswered.append(pending['line'])
            pending=f; tx[(f['id'],f['data'])]+=1
        elif f['event']=='TX_DONE': done[(f['id'],f['data'])]+=1
        elif f['event']=='RX':
            if pending and category(pending)==category(f) and 0<=f['t']-pending['t']<500: pending=None; matched+=1
            else: orphan.append(f['line'])
    if pending and not 0<=last[1]['t_ms']-pending['t']<500: unanswered.append(pending['line'])
    outstanding=list((tx-done).elements()); excess_done=list((done-tx).elements())
    if excess_done or len(outstanding)>1 or (outstanding and (not pending or outstanding[0]!=(pending['id'],pending['data']))): issues.append('Unmatched TX_DONE')
    if malformed or unsafe or unexpected or unanswered or orphan: issues.append('Malformed/unsafe/unmatched frame(s)')
    parameters={}
    for idx,name in PARAMS.items():
        vals=sorted({f['data'][4:] for f in frames if f['event']=='RX' and category(f)==name})
        parameters[name]={'index':hex(idx),'raw_values':[v.hex(' ').upper() for v in vals], 'values':[struct.unpack('<f',v)[0] if idx>=0x8000 else v[0] for v in vals]}
    if parameters['Can_baud']['values']!=[code]: issues.append('Can_baud does not match requested code')
    versions=sorted({f['data'].split(b'\x00')[0].decode('ascii',errors='replace') for f in frames if f['event']=='RX' and category(f)=='version'})
    ranges={}
    for key in ['battery_mv','motor_mv','temp_c']:
        vals=[int(m.group(1)) for s in samples if (m:=re.search(r'(?:,|^)'+key+r'=(\d+)',s))]
        if vals:ranges[key]=dict(min=min(vals),max=max(vals))
    return dict(result='PASS' if not issues else 'NOT_PASS',scope='boot-anchored read-link baseline only; NOT migration PASS',source=str(path.resolve()),raw_sha256=hashlib.sha256(raw).hexdigest(),boot_line=boot+1,boot_header=header,excluded_prefix_lines=boot,first_health=first[1],last_health=last[1],window_seconds=(last[1]['t_ms']-first[1]['t_ms'])/1000,latest_health_in_file=latest,arming_gate_counters_eligible=gate_eligible,health_count=len(window),counts_by_query=counts,matched_since_boot=matched,trailing_pending=pending['line'] if pending else None,parameters=parameters,versions=versions,status_ranges=ranges,malformed_lines=malformed,unsafe_tx_lines=unsafe,unexpected_rx_lines=unexpected,unanswered=unanswered,orphan_rx=orphan,issues=issues,verified_lines=[boot+1,last[0]+1])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);p.add_argument('--code',type=int,required=True,choices=[1,2]);p.add_argument('--bitrate',type=int,required=True,choices=[500000,1000000]);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output exists; choose a new analysis path')
    report=analyze(a.log,a.code,a.bitrate);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['result']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
