"""Authenticated, bounded BLE maintenance transfer; never musical retries."""
import asyncio
import hashlib
import struct
import time
from collections import deque

CONTROL = '6E400005-B5A3-F393-E0A9-E50E24DCCA9E'
DATA = '6E400006-B5A3-F393-E0A9-E50E24DCCA9E'
MAX_IMAGE = 0x140000
QUERY, META, BEGIN, WRITE, END, COMMIT, ABORT = range(1, 8)
CHALLENGE, READY, PROGRESS, VERIFIED, COMMITTED, ABORTED = range(0x81, 0x87)
ERROR = 0xff
ERRORS = {1:'firmware bez klucza OTA lub dwóch partycji aplikacji',2:'nieprawidłowa ramka',
          3:'ATX musi być logicznie OFF',4:'niezgodny klucz lub uwierzytelnienie obrazu',
          5:'obraz przekracza partycję OTA',6:'błąd zapisu Flash lub wyboru partycji',
          7:'brakujący lub powtórzony fragment',8:'błędny SHA-256 lub obraz ESP32',
          9:'nieprawidłowy stan OTA',10:'timeout OTA',11:'przepełnienie kolejki OTA'}


def manifest(image, key, nonce):
    from ecdsa import SigningKey, NIST256p
    if not 1 <= len(image) <= MAX_IMAGE or len(key)!=32 or len(nonce)!=16:
        raise ValueError('Invalid BLE OTA image/key/challenge size')
    body = struct.pack('<I',len(image))+hashlib.sha256(image).digest()
    signer=SigningKey.from_string(key,curve=NIST256p)
    return body+signer.sign_deterministic(nonce+body,hashfunc=hashlib.sha256)


async def upload(client, image, key, on_progress=None):
    """Own an existing BLE session exclusively until COMMITTED or failure.

    Receipt windows contain <=6 packets, within the eight firmware RX slots.
    Maintenance has a 10 s transaction timeout, not the musical 250 ms budget.
    No window, image or commit is automatically retried.
    """
    services=client.services
    if services.get_characteristic(CONTROL) is None or services.get_characteristic(DATA) is None:
        raise RuntimeError('Firmware nie obsługuje BLE OTA; pierwszą instalację wykonaj przez USB')
    replies=asyncio.Queue(maxsize=16)
    accepted=deque(maxlen=8)
    overflow=False
    committing=False
    def received(_characteristic, data):
        nonlocal overflow
        if replies.full(): overflow=True
        else: replies.put_nowait(bytes(data))
    await client.start_notify(CONTROL, received)
    async def send(uuid, packet):
        await client.write_gatt_char(uuid,packet,response=False)
    async def reply(expected, length, offset=None):
        deadline=time.monotonic()+10
        while True:
            packet=await asyncio.wait_for(replies.get(),max(0.,deadline-time.monotonic()))
            if overflow: raise RuntimeError('BLE OTA reply overflow')
            # Notifications may be duplicated by a peripheral TX retry. Ignore
            # only receipts already validated, without renewing the deadline or
            # resending image data. Unknown/wrong offsets remain fatal.
            if packet in accepted:continue
            if len(packet)==2 and packet[0]==ERROR:
                raise RuntimeError('BLE OTA: '+ERRORS.get(packet[1],'unknown firmware error'))
            if len(packet)!=length or packet[0]!=expected:
                raise RuntimeError('BLE OTA: unexpected receipt')
            if offset is not None and struct.unpack('<I',packet[1:])[0]!=offset:
                raise RuntimeError('BLE OTA: unexpected byte offset')
            accepted.append(packet)
            return packet
    try:
        if not 1 <= len(image) <= MAX_IMAGE or len(key)!=32:
            raise ValueError('Invalid BLE OTA image or key')
        await send(CONTROL,bytes([QUERY]))
        challenge=await reply(CHALLENGE,18)
        if challenge[1]!=1:raise RuntimeError('Unsupported BLE OTA protocol')
        metadata=manifest(image,key,challenge[2:])
        # Six metadata fragments and BEGIN fit the eight firmware RX slots.
        for offset in range(0,len(metadata),18):
            await send(CONTROL,bytes([META,offset])+metadata[offset:offset+18])
        await send(CONTROL,bytes([BEGIN]));await reply(READY,5,0)
        capacity=min(512,getattr(client,'mtu_size',23)-3,
                     services.get_characteristic(DATA).max_write_without_response_size)
        if capacity<20:raise RuntimeError('Invalid BLE OTA payload capacity')
        offset=0;last_percent=-1;started=time.monotonic()
        while offset<len(image):
            if time.monotonic()-started>900:raise RuntimeError('BLE OTA transfer timeout')
            for packet_index in range(6):
                payload=image[offset:offset+capacity-5]
                end=offset+len(payload)
                final=packet_index==5 or end==len(image)
                await send(DATA,bytes([WRITE|(0x80 if final else 0)])+struct.pack('<I',offset)+payload)
                offset=end
                if final:break
            await reply(PROGRESS,5,offset)
            percent=offset*100//len(image)
            if percent!=last_percent:
                last_percent=percent
                if on_progress:on_progress(percent)
        await send(CONTROL,bytes([END]));await reply(VERIFIED,1)
        committing=True
        await send(CONTROL,bytes([COMMIT]));await reply(COMMITTED,1)
        return {'sha256':hashlib.sha256(image).hexdigest(),'bytes':len(image)}
    except BaseException as error:
        # One best-effort abort, never claim that an absent receipt confirms it.
        try:await asyncio.wait_for(send(CONTROL,bytes([ABORT])),1)
        except Exception:pass
        if committing and isinstance(error,Exception):
            raise RuntimeError('BLE OTA: COMMIT niepotwierdzony; nowy obraz mógł zostać wybrany. Sprawdź recovery, nie ponawiaj automatycznie.') from error
        raise
    finally:
        try:await asyncio.wait_for(client.stop_notify(CONTROL),1)
        except Exception:pass
