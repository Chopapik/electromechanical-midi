"""FastAPI entrypoint for the single explicit orchestra runtime (ESP32 BLE)."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path
HOST_DIR=Path(__file__).resolve().parents[1]
if str(HOST_DIR) not in sys.path: sys.path.insert(0,str(HOST_DIR))
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from midi_source import MidiSource
from runtime.application import Application
from runtime.registry import DeviceRegistry
from web.library import MidiLibrary

MAX_UPLOAD_BYTES=5*1024*1024

def create_app(*, midi_dir=None, runtime=None, connect_on_start=True, registry_path=None):
    library=MidiLibrary(Path(midi_dir or HOST_DIR.parent/'midi'))
    runtime=runtime or Application(DeviceRegistry(registry_path) if registry_path else None)
    peers={}; tasks=set(); loop=None
    async def send_all(message):
        for peer in list(peers.values()):
            with contextlib.suppress(Exception): await peer.send_json(message)
    def emit(message):
        if loop: asyncio.run_coroutine_threadsafe(send_all(message),loop)
    runtime.virtual.emit=emit
    async def broadcast():
        while True:
            await send_all({'type':'state','state':await asyncio.to_thread(runtime.snapshot)})
            await asyncio.to_thread(runtime.lab.expire)
            await asyncio.sleep(.05)
    async def connect_loop():
        while True:
            await asyncio.to_thread(runtime.service.refresh)
            if connect_on_start and runtime.router.mode=='REAL' and not runtime.real.link:
                await asyncio.to_thread(runtime.service.connect)
            await asyncio.sleep(2)
    @contextlib.asynccontextmanager
    async def lifespan(app):
        nonlocal loop
        loop=asyncio.get_running_loop(); runtime.player.start()
        workers=[asyncio.create_task(broadcast()),asyncio.create_task(connect_loop())]
        yield
        for worker in workers: worker.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        # Stop barriers need the socket receiver alive; disconnected browsers self-silence.
        with contextlib.suppress(Exception): await asyncio.to_thread(runtime.player.close)
        if runtime.real.link: runtime.real.link.close()
        for task in tasks: task.cancel()
    app=FastAPI(lifespan=lifespan)
    app.state.runtime=runtime
    @app.get('/api/state')
    def state(): return runtime.snapshot()
    @app.get('/api/monitor/raw')
    def monitor():
        return {**runtime.snapshot(),'commands':runtime.real.sent,'plan':runtime.plan.report() if runtime.plan else None}
    @app.get('/api/plan')
    def plan():
        return {'report':runtime.plan.report(),'events':[e.as_dict() for e in runtime.plan.events]} if runtime.plan else None
    @app.get('/api/timeline')
    def timeline(): return runtime.timeline.as_dict() if runtime.timeline else None
    @app.get('/api/files')
    def files(): return library.list_files()
    @app.get('/api/files/{name}')
    def metadata(name:str): return library.metadata(name)
    @app.post('/api/files')
    async def upload(file:UploadFile=File(...)):
        name=Path(file.filename or '').name
        if not name or name.startswith('.') or Path(name).suffix.lower() not in ('.mid','.midi'):
            raise HTTPException(422,'Wybierz plik MIDI')
        data=await file.read(MAX_UPLOAD_BYTES+1)
        if len(data)>MAX_UPLOAD_BYTES: raise HTTPException(413,'MIDI przekracza 5 MB')
        library.directory.mkdir(parents=True,exist_ok=True)
        import tempfile
        with tempfile.NamedTemporaryFile(dir=library.directory,suffix='.mid') as temp:
            temp.write(data); temp.flush()
            try: MidiSource(Path(temp.name))
            except Exception as exc: raise HTTPException(422,str(exc)) from exc
        path=library.directory/name
        if path.exists():
            stem=path.stem; i=1
            while path.exists(): path=library.directory/f'{stem}-{i}.mid'; i+=1
        path.write_bytes(data)
        return {'name':path.name}
    async def action(peer, owner, message):
        operation=message.get('action'); request=message.get('requestId')
        try:
            def perform():
                if runtime.service.busy: raise ValueError('DeviceService jest zajęty')
                p=runtime.player
                if operation=='set_file': runtime.load(library.resolve(message['file']))
                elif operation=='play':
                    if runtime.router.mode=='VIRTUAL':
                        if runtime.virtual.active and runtime.virtual.owner!=owner: raise ValueError('Web Audio jest używane przez inną przeglądarkę')
                        runtime.virtual.owner=owner
                    if p.owner!='orchestra' or p.timeline is not runtime.timeline: runtime.orchestra()
                    p.play()
                elif operation=='audio_error':
                    if runtime.virtual.owner==owner and runtime.router.mode=='VIRTUAL' and message.get('epoch')==p.epoch:
                        p.pause(); p.error='Web Audio: '+str(message.get('message','wyjście niedostępne'))[:250]
                elif operation=='pause': p.pause()
                elif operation=='stop': p.stop()
                elif operation=='seek': p.seek(message['position'])
                elif operation=='output': p.switch(message['mode'])
                elif operation=='mute': p.mute(message['deviceId'],message['muted'])
                elif operation=='lab_enter': runtime.lab.enter(owner)
                elif operation=='lab_leave': runtime.lab.leave(owner); runtime.orchestra()
                elif operation=='lab_test':
                    if runtime.router.mode=='VIRTUAL': runtime.virtual.owner=owner
                    runtime.lab.test(owner,message['deviceId'],message.get('hz',200),message.get('duration',1))
                elif operation=='service': runtime.service.run(message['operation'])
                else: raise ValueError('Unknown action')
            async with command_lock:
                await asyncio.to_thread(perform)
            await peer.send_json({'type':'ack','requestId':request,'state':await asyncio.to_thread(runtime.snapshot)})
        except Exception as exc:
            with contextlib.suppress(Exception): await peer.send_json({'type':'error','requestId':request,'message':str(exc)})
    command_lock=asyncio.Lock()
    @app.websocket('/ws')
    async def websocket(peer:WebSocket):
        import uuid,time
        await peer.accept(); owner=uuid.uuid4().hex; peers[owner]=peer
        await peer.send_json({'type':'hello','session':owner})
        try:
            while True:
                message=await peer.receive_json()
                if message.get('action')=='audio_ack': runtime.virtual.acknowledge(owner,message.get('token'))
                elif message.get('action')=='sync':
                    runtime.lab.touch(owner)
                    await peer.send_json({'type':'sync','sent':message['sent'],'serverTime':time.monotonic()})
                else:
                    task=asyncio.create_task(action(peer,owner,message)); tasks.add(task); task.add_done_callback(tasks.discard)
        except WebSocketDisconnect: pass
        finally:
            peers.pop(owner,None)
            if runtime.virtual.owner==owner:
                # Browser heartbeat watchdog silences scheduled nodes within 500 ms.
                # Keep owner through STOP timeout; do not claim acknowledgement.
                with contextlib.suppress(Exception): await asyncio.to_thread(runtime.player.stop)
                await asyncio.sleep(.6)  # Audio-graph heartbeat lease has expired.
                runtime.virtual.active=False
                runtime.virtual.owner=None
            if runtime.lab.session==owner:
                with contextlib.suppress(Exception): await asyncio.to_thread(runtime.lab.leave,owner)
    dist=HOST_DIR.parent/'web/dist'
    if dist.exists(): app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    return app

def main(argv=None):
    import uvicorn
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--midi-dir',type=Path,default=HOST_DIR.parent/'midi')
    parser.add_argument('--registry',type=Path,default=None)
    parser.add_argument('--offline',action='store_true',default=os.getenv('ORCHESTRA_OFFLINE')=='1',help='Disable BLE discovery; output still starts REAL')
    args=parser.parse_args(argv)
    uvicorn.run(create_app(midi_dir=args.midi_dir,registry_path=args.registry,connect_on_start=not args.offline),host=args.host,port=args.port)
    return 0
if __name__=='__main__': raise SystemExit(main())
