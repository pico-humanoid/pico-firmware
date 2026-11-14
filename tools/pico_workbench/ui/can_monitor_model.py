"""Read-only decoder for RobStride AT-wrapped Classic CAN extended frames.

Source: RS10P 261016 manual, section 3.3.5; RobStride/CAN-USB-data-conversion.
Unrecognized serial bytes are retained by the monitor's separate raw log.
"""
import math
import struct

class ATDecoder:
    def __init__(self):
        self.buffer=bytearray();self.discarded=0;self.unsupported=0
    def feed(self,data):
        self.buffer.extend(data);frames=[]
        while self.buffer:
            start=self.buffer.find(b'AT')
            if start<0:
                keep=1 if self.buffer[-1:]==b'A' else 0
                self.discarded+=len(self.buffer)-keep
                self.buffer[:]=self.buffer[-1:] if keep else b''
                break
            if start:
                del self.buffer[:start];self.discarded+=start
            if len(self.buffer)<7:break
            dlc=self.buffer[6]
            if dlc>8:
                del self.buffer[0];self.discarded+=1;continue
            size=9+dlc
            if len(self.buffer)<size:break
            if self.buffer[size-2:size]!=b'\r\n':
                del self.buffer[0];self.discarded+=1;continue
            packet=bytes(self.buffer[:size]);del self.buffer[:size]
            word=int.from_bytes(packet[2:6],'big')
            if not word&4 or word&2:
                self.unsupported+=1;continue
            frames.append((word>>3,packet[7:7+dlc]))
        return frames

FIELDS={0x7019:('位置','rad'),0x701B:('速度','rad/s'),0x701A:('Iq电流','A'),0x701C:('母线电压','V')}
def describe(identifier,data):
    kind=(identifier>>24)&31;source=(identifier>>8)&255;dest=identifier&255
    if identifier>>16==0 and dest==0xFE and len(data)==8:
        return ('电机%02X → 身份回复FE（按ID）'%source,
                '身份信息；电机ID=0x%02X；UID=%s'%(source,data.hex(' ').upper()))
    if kind==17 and source==0xFD and dest==0x7F:
        origin='主机FD → 电机7F（按ID）'
    elif kind==17 and source==0x7F and dest==0xFD:
        origin='电机7F → 主机FD（按ID）'
    else:origin='其他扩展报文'
    meaning='类型 '+str(kind)
    if kind==17 and len(data)==8:
        index=int.from_bytes(data[:2],'little');meaning+='，读取 0x%04X'%index
        if index in FIELDS:
            name,unit=FIELDS[index];meaning+=' '+name
            if source==0x7F and dest==0xFD and data[2:4]==b'\0\0':
                value=struct.unpack('<f',data[4:])[0]
                if math.isfinite(value):meaning+=' = %.6g %s'%(value,unit)
    return origin,meaning
