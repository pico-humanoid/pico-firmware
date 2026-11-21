import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from can_pc_test_model import request,assess
from can_monitor_model import ATDecoder

class BenchContractTests(unittest.TestCase):
    def setUp(self):
        self.frames=[(0x123,bytes([n])+bytes.fromhex('22 33 44 55 66 77 88')) for n in range(100)]
        self.log='# CAN3_PC_TEST=1;\n# RESULT=PASS tx_submit=100 tx_done=100 rx_unique=100\n'
    def test_request_wire_contract(self):
        self.assertEqual(ATDecoder().feed(request(0)),[(0x321,bytes.fromhex('00 88 77 66 55 44 33 22'))])
        for n in [-1,100]:
            with self.assertRaises(ValueError):request(n)
    def test_both_sides_pass(self):
        self.assertTrue(assess(100,self.frames,self.log)['pass'])
    def test_missing_duplicate_corrupt_echo_and_unrelated_fail(self):
        for frames in [self.frames[:-1],self.frames+[self.frames[0]],self.frames[:-1]+[(0x123,b'bad')],
                       [(0x321,data) for _,data in self.frames],self.frames+[(0x7FFE,b'identity')]]:
            self.assertFalse(assess(100,frames,self.log)['pass'])
    def test_pc_count_alone_does_not_prove_board_received(self):
        for log in ['',self.log.replace('PASS','FAIL'),self.log.replace('# CAN3_PC_TEST=1;','')]:
            self.assertFalse(assess(100,self.frames,log)['pass'])
        self.assertFalse(assess(99,self.frames,self.log)['pass'])
        self.assertFalse(assess(100,self.frames,self.log,True)['pass'])

if __name__=='__main__':unittest.main()
