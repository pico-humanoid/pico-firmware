"""Dedicated PC/board bench contract, using RobStride AT extended frames."""
def request(sequence):
    if not 0<=sequence<100:raise ValueError('sequence must be 0..99')
    data=bytes([sequence,0x88,0x77,0x66,0x55,0x44,0x33,0x22])
    return b'AT'+((0x321<<3)|4).to_bytes(4,'big')+b'\x08'+data+b'\r\n'

def _assess(sent,frames,reply_id,board_pass,cancelled):
    valid=[];invalid=0;other=0
    for identifier,data in frames:
        if identifier!=reply_id:other+=1;continue
        if len(data)!=8 or data[0]>=100 or data[1:]!=bytes.fromhex('22 33 44 55 66 77 88'):
            invalid+=1;continue
        valid.append(data[0])
    missing=sorted(set(range(100))-set(valid))
    duplicates=sorted(v for v in set(valid) if valid.count(v)>1)
    passed=sent==100 and len(valid)==100 and not(missing or duplicates or invalid or other or cancelled) and board_pass
    return {'pass':passed,'sent':sent,'valid_replies':len(valid),'missing':missing,'duplicates':duplicates,
            'invalid':invalid,'other_frames':other,'board_pass':board_pass,'cancelled':cancelled}

def assess(sent,frames,board_log,cancelled=False):
    board_pass='# CAN3_PC_TEST=1;' in board_log and '# RESULT=PASS ' in board_log
    return _assess(sent,frames,0x123,board_pass,cancelled)

def channel_ids(channel):
    if channel not in (1,2,3):raise ValueError('channel must be 1, 2 or 3')
    return 0x320+channel,0x120+channel

def multi_request(sequence,channel):
    identifier,_=channel_ids(channel)
    if not 0<=sequence<100:raise ValueError('sequence must be 0..99')
    return b'AT'+((identifier<<3)|4).to_bytes(4,'big')+b'\x08'+bytes([sequence])+bytes.fromhex('88 77 66 55 44 33 22')+b'\r\n'

def multi_health(line):
    if not line.startswith('# MULTI_HEALTH,'):return None
    fields=dict(item.split('=',1) for item in line.strip().split(',')[1:] if '=' in item)
    return fields if fields.get('channel') in ('CAN1','CAN2','CAN3') else None

def assess_multi(sent,frames,board_log,channel,cancelled=False):
    request_id,reply_id=channel_ids(channel)
    summaries=[]
    for line in board_log.splitlines():
        if line.startswith('# MULTI_RESULT '):
            fields=dict(v.split('=',1) for v in line.split()[2:] if '=' in v)
            if fields.get('channel')=='CAN'+str(channel):summaries.append(fields)
    board_pass=('# CAN_MULTI_TEST=1;' in board_log and '# MULTI_READY=1;' in board_log and len(summaries)==1
        and summaries[0].get('result')=='PASS'
        and all(summaries[0].get(k)=='100' for k in ('rx_unique','tx_submit','tx_done')))
    result=_assess(sent,frames,reply_id,board_pass,cancelled)
    health={}
    for line in board_log.splitlines():
        value=multi_health(line)
        if value:health[value['channel']]=value
    result.update(channel='CAN'+str(channel),request_id=hex(request_id),reply_id=hex(reply_id),channels=health)
    return result
