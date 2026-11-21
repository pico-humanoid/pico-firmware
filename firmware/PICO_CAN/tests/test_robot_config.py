"""Configuration invariants: pins, 160/80MHz clocks, classic CAN and RTOS."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
D = dict(line.split('=', 1) for line in (ROOT / 'PICO_CAN.ioc').read_text().splitlines()
         if '=' in line and not line.startswith('#'))

class RobotConfig(unittest.TestCase):
    def test_clock_and_baud(self):
        self.assertEqual(D['RCC.PWR_Regulator_Voltage_Scale'], 'PWR_REGULATOR_VOLTAGE_SCALE1_BOOST')
        self.assertEqual(D['RCC.PLLM'], 'RCC_PLLM_DIV4')
        self.assertEqual(D['RCC.PLLN'], '80')
        self.assertEqual(D['RCC.PLLR'], 'RCC_PLLR_DIV2')
        self.assertEqual(D['RCC.SYSCLKFreq_VALUE'], '160000000')
        self.assertEqual(D['RCC.APB1Freq_Value'], '80000000')
        for bus,rate in ((1,500000),(2,1000000),(3,1000000)):
            prefix=f'FDCAN{bus}.'
            tq=1+int(D[prefix+'NominalTimeSeg1'])+int(D[prefix+'NominalTimeSeg2'])
            self.assertEqual(80000000//int(D[prefix+'NominalPrescaler'])//tq,rate)
            self.assertEqual(D[prefix+'FrameFormat'],'FDCAN_FRAME_CLASSIC')
            self.assertEqual(D[prefix+'Mode'],'FDCAN_MODE_NORMAL')
            self.assertEqual(D[prefix+'AutoRetransmission'],'ENABLE')
            self.assertEqual(D[f'NVIC.FDCAN{bus}_IT0_IRQn'].split('\\:')[1],'5')
    def test_pins_and_rtos(self):
        for pin,signal in (('PA11','FDCAN1_RX'),('PA12','FDCAN1_TX'),('PB12','FDCAN2_RX'),('PB13','FDCAN2_TX'),('PA8','FDCAN3_RX'),('PA15','FDCAN3_TX')):
            self.assertEqual(D[pin+'.Signal'],signal)
        self.assertEqual(D['LPUART1.BaudRate'],'115200')
        self.assertEqual(D['NVIC.LPUART1_IRQn'].split('\\:')[1],'5')
        self.assertEqual(D['NVIC.TimeBaseIP'],'TIM6')
        self.assertEqual(D['NVIC.TimeBase'],'TIM6_DAC_IRQn')
        for key,value in (('configTOTAL_HEAP_SIZE','16384'),('HEAP_NUMBER','4'),('MEMORY_ALLOCATION','2'),('configTICK_RATE_HZ','1000'),('configCHECK_FOR_STACK_OVERFLOW','2'),('configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY','5')):
            self.assertEqual(D['FREERTOS.'+key],value)
        self.assertIn('RobotComm,40,1024,RobotComm_Task,As external',D['FREERTOS.Tasks01'])
        self.assertIn('Telemetry,24,512,RobotTelemetry_Task,As external',D['FREERTOS.Tasks01'])

if __name__=='__main__': unittest.main()
