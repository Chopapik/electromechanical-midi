"""Request the shared DeviceService upload barrier through the LOCAL running app.

Never invokes PlatformIO directly and has no bypass for missing POWER OFF ACK.
Run only when authorized to flash: .venv/bin/python scripts/safe_upload.py
"""
import argparse
import asyncio
import json
import uuid
from urllib.parse import urlsplit

async def upload(url, transport='usb'):
    from websockets.asyncio.client import connect
    parsed=urlsplit(url)
    if parsed.scheme!='ws' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.path!='/ws':
        raise ValueError('Safe upload requires local ws://localhost-or-127.0.0.1:PORT/ws')
    if transport not in ('usb','ble'):raise ValueError('Invalid firmware transport')
    request=uuid.uuid4().hex
    async with connect(url,origin='http://'+parsed.netloc) as socket:
        await socket.send(json.dumps({'action':'service','operation':'firmware_ble' if transport=='ble' else 'firmware','requestId':request}))
        async with asyncio.timeout(1200):
            async for raw in socket:
                message=json.loads(raw)
                if message.get('type')=='firmware_event':
                    print(message.get('line') or message.get('stage',''),flush=True)
                if message.get('requestId')==request:
                    if message.get('type')=='error': raise RuntimeError(message['message'])
                    if message.get('type')=='ack': return
        raise RuntimeError('Backend disconnected before upload acknowledgement')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='ws://127.0.0.1:5173/ws')
    parser.add_argument('--transport',choices=('usb','ble'),default='usb')
    args=parser.parse_args()
    asyncio.run(upload(args.url,args.transport))
