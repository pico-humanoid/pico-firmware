"""Synthetic analysis fixtures only: no serial access, NOT a device PASS."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('analysis',Path(__file__).parents[1]/'scripts/analyze_power_capture.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)
HEADER='# PICO device-read v1; READ ONLY; device=POWER bitrate=1000000 power_id=0xAA rtr_dlc=8 crc_order=1 status_order=1'

def fixture():
    events=[]
    for t in range(1000,65000,200):
        job=((t-1000)//200)%12; data=bytes(8)
        if job==0: txid=0x050000AA; rxid=0x05AA0000; reply=b'V1.08\0\0\0'
        elif job<3:
            txid=0x020000AA;rxid=(3 if job==1 else 4)<<24|0x00AA0000
            if job==2:data=bytes([0xca])+bytes(7)
            reply=bytes(8)
        else:
            idx=list(analysis.PARAMS)[job-3];txid=0x070000AA;rxid=0x07AA0000
            data=idx.to_bytes(2,'little')+bytes(6);reply=data[:4]+bytes([1,0,0,0])
        for delta,event,id_,payload in [(0,'TX_SUBMIT',txid,data),(1,'TX_DONE',txid,data),(2,'RX',rxid,reply)]:
            events.append((t+delta,f'{t+delta},{event},FDCAN1,EXT,DATA,0x{id_:08X},8,{payload.hex(" ").upper()}'))
    for t in range(5000,65001,5000):
        fields={'t_ms':t,'seen':0xfff,'valid':0xfff,'tec':0,'rec':0,'counters_ok':1,**dict.fromkeys(analysis.ERRORS,0)}
        events.append((t+3,'# HEALTH,'+','.join(f'{k}={v}' for k,v in fields.items())))
    return HEADER+'\n'+'\n'.join(s for _,s in sorted(events))+'\n'

class Tests(unittest.TestCase):
    def run_analysis(self,text,code=1,bitrate=1000000):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fixture.log';p.write_text(text);return analysis.analyze(p,code,bitrate)
    def test_baseline(self):
        r=self.run_analysis(fixture());self.assertEqual(r['result'],'PASS');self.assertEqual(r['window_seconds'],60);self.assertTrue(r['arming_gate_counters_eligible'])
    def test_excludes_stale_prefix(self):
        r=self.run_analysis('garbage old VCP bytes\n# HEALTH,truncated\n'+fixture());self.assertEqual(r['result'],'PASS');self.assertEqual(r['excluded_prefix_lines'],2)
    def test_no_boot(self):self.assertEqual(self.run_analysis('junk\n')['result'],'NOT_PASS')
    def test_wrong_configuration(self):self.assertEqual(self.run_analysis(fixture(),bitrate=500000)['result'],'NOT_PASS')
    def test_wrong_parameter(self):self.assertEqual(self.run_analysis(fixture(),code=2)['result'],'NOT_PASS')
    def test_missing_reply(self):
        text=fixture();text='\n'.join(s for s in text.splitlines() if not s.startswith('1002,RX'))+'\n'
        self.assertEqual(self.run_analysis(text)['result'],'NOT_PASS')
    def test_unsafe_tx(self):
        text=fixture().replace('1000,TX_SUBMIT,FDCAN1,EXT,DATA,0x050000AA','1000,TX_SUBMIT,FDCAN1,EXT,DATA,0x080000AA')
        self.assertEqual(self.run_analysis(text)['result'],'NOT_PASS')
    def test_short_window(self):
        text='\n'.join(s for s in fixture().splitlines() if not s.startswith('# HEALTH,t_ms=65000'))+'\n'
        self.assertEqual(self.run_analysis(text)['result'],'NOT_PASS')
    def test_later_error_cannot_authorize_write(self):
        text=fixture();latest=next(s for s in reversed(text.splitlines()) if s.startswith('# HEALTH'))
        text+=latest.replace('t_ms=65000','t_ms=70000').replace('query_timeouts=0','query_timeouts=1')+'\n'
        r=self.run_analysis(text);self.assertEqual(r['result'],'PASS');self.assertFalse(r['arming_gate_counters_eligible']);self.assertEqual(r['latest_health_in_file']['query_timeouts'],1)
    def test_error_inside_window(self):
        self.assertEqual(self.run_analysis(fixture().replace('query_timeouts=0','query_timeouts=1'))['result'],'NOT_PASS')

if __name__=='__main__':unittest.main()
