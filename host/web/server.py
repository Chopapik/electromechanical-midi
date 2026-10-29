"""FastAPI entrypoint for the single explicit orchestra runtime (ESP32 BLE)."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import hashlib
import threading
import os
import sys
from urllib.parse import urlsplit
from pathlib import Path
HOST_DIR=Path(__file__).resolve().parents[1]
if str(HOST_DIR) not in sys.path: sys.path.insert(0,str(HOST_DIR))
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from runtime.application import Application
from diagnostics import Diagnostics, NullDiagnostics
from runtime.registry import DeviceRegistry
from web.library import MidiLibrary, MidiLibraryError, MAX_UPLOAD_BYTES
from web.contracts import validate_command

LIBRARY_HTTP_STATUS = {'invalid_name':400, 'outside_library':400, 'not_found':404,
                       'invalid_upload_name':422, 'invalid_midi':422, 'upload_too_large':413}


def _library_call(operation, *args):
    """Keep transport statuses at the controller boundary, including WS errors."""
    try:
        return operation(*args)
    except MidiLibraryError as exc:
        raise HTTPException(LIBRARY_HTTP_STATUS[exc.code], str(exc)) from exc

def create_app(*, midi_dir=None, runtime=None, connect_on_start=True, registry_path=None, diagnostics_dir=None):
    library=MidiLibrary(Path(midi_dir or HOST_DIR.parent/'midi'))
    runtime=runtime or Application(DeviceRegistry(registry_path) if registry_path else None)
    diagnostics=Diagnostics(diagnostics_dir) if diagnostics_dir else NullDiagnostics()
    runtime.player.diagnostics=diagnostics
    def context():
        # Best-effort context without waiting for Player or the transport.
        player=runtime.player
        return {'file':runtime.source.path.name if runtime.source else None,
            'preset':runtime.registry.document.get('parameters',{}).get('arrangementPreset'),
            'state':player.state,'position':player.position(),'epoch':player.epoch,
            'output':runtime.router.mode,'connected':runtime.real.link is not None,
            'unknown':runtime.real.unknown,'planning':runtime.planning,
            'muted':sorted(runtime.router.muted),'homingDevices':list(runtime.real.homing_devices),
            'timing':{'droppedExpired':player.dropped,'maxLag':player.max_lag}}
    peers={}; peer_locks={}; tasks=set(); loop=None
    async def send_peer(peer, message):
        async def send():
            async with peer_locks[peer]: await peer.send_json(message)
        try:
            await asyncio.wait_for(send(), .5)
        except asyncio.TimeoutError as exc:
            diagnostics.incident('browser_send_timeout',context=context(),error=exc)
            # One stalled viewer must not hold every other browser's audio/ACK.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(peer.close(code=1013), .1)
            raise
    async def send_all(message):
        await asyncio.gather(*(send_peer(peer,message) for peer in list(peers.values())),
                             return_exceptions=True)
    def emit(message):
        if message.get('type')=='firmware_event' and message.get('kind')=='status':
            diagnostics.record('service_status',message)
            if message.get('error'):diagnostics.incident('service_failure',context=message,message=message['error'])
        if loop: asyncio.run_coroutine_threadsafe(send_all(message),loop)
    runtime.virtual.emit=emit
    runtime.service.emit=emit
    async def broadcast():
        while True:
            await send_all({'type':'state','state':await asyncio.to_thread(runtime.snapshot)})
            await asyncio.to_thread(runtime.expire_laboratory)
            await asyncio.sleep(.05)
    async def connect_loop():
        previous=None
        while True:
            await asyncio.to_thread(runtime.refresh_connection,connect_on_start)
            current=(runtime.real.link is not None,runtime.service.error)
            if current!=previous:
                diagnostics.record('connection_state',{'connected':current[0],'error':current[1]})
                if current[1]:diagnostics.incident('connection_failure',context=context(),message=current[1])
                previous=current
            await asyncio.sleep(2)
    async def heartbeat_log():
        while True:
            diagnostics.record('heartbeat',context())
            await asyncio.sleep(1)
    def worker_done(task):
        if not task.cancelled() and task.exception():
            diagnostics.incident('background_task_failed',context={**context(),'task':task.get_name()},error=task.exception())
    @contextlib.asynccontextmanager
    async def lifespan(app):
        nonlocal loop
        loop=asyncio.get_running_loop()
        old_handler=loop.get_exception_handler();old_thread_hook=threading.excepthook
        if isinstance(diagnostics,Diagnostics):
            diagnostics.start()
            digest=hashlib.sha256()
            try:
                for path in sorted(HOST_DIR.rglob('*.py')):
                    if 'tests' not in path.parts:
                        digest.update(str(path.relative_to(HOST_DIR)).encode());digest.update(path.read_bytes())
            except OSError as exc:diagnostics.incident('version_read_failure',error=exc)
            diagnostics.record('runtime_version',{'sourceFingerprint':digest.hexdigest(),
                'offline':not connect_on_start,'devices':[{'id':d['id'],'enabled':d['enabled']} for d in runtime.registry.devices]})
            def thread_error(args):
                diagnostics.incident('thread_crash',context={'thread':args.thread.name if args.thread else None},error=args.exc_value)
                old_thread_hook(args)
            def async_error(event_loop,details):
                diagnostics.incident('async_crash',context=context(),error=details.get('exception'),message=details.get('message'))
                if old_handler:old_handler(event_loop,details)
                else:event_loop.default_exception_handler(details)
            threading.excepthook=thread_error;loop.set_exception_handler(async_error)
        workers=[]
        try:
            runtime.start()
            workers=[asyncio.create_task(broadcast(),name='state-broadcast'),
                     asyncio.create_task(connect_loop(),name='connection-monitor'),
                     asyncio.create_task(heartbeat_log(),name='diagnostic-heartbeat')]
            for worker in workers:worker.add_done_callback(worker_done)
            yield
        except BaseException as exc:
            diagnostics.incident('server_lifecycle_failure',context=context(),error=exc)
            raise
        finally:
            for worker in workers:worker.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
            try:await asyncio.to_thread(runtime.close)
            except Exception as exc:diagnostics.incident('shutdown_failure',context=context(),error=exc)
            for task in list(tasks):task.cancel()
            await asyncio.gather(*list(tasks),return_exceptions=True)
            if isinstance(diagnostics,Diagnostics):
                threading.excepthook=old_thread_hook;loop.set_exception_handler(old_handler)
                await asyncio.to_thread(diagnostics.close)
            loop=None
    app=FastAPI(lifespan=lifespan)
    app.state.runtime=runtime
    @app.middleware('http')
    async def log_http_failure(request,call_next):
        try:return await call_next(request)
        except Exception as exc:
            diagnostics.incident('http_failure',context={'method':request.method,'path':request.url.path},error=exc)
            raise
    @app.get('/api/diagnostics')
    def diagnostic_status():return diagnostics.status()
    @app.get('/api/diagnostics/incidents/{ident}')
    def incident_file(ident:str):
        if not isinstance(diagnostics,Diagnostics):raise HTTPException(404,'Diagnostics disabled')
        try:return diagnostics.read_incident(ident)
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Incident not found')
    @app.get('/api/state')
    def state(): return runtime.snapshot()
    @app.get('/api/firmware/events')
    def firmware_events(): return list(runtime.service.events)
    @app.get('/api/monitor/raw')
    def monitor():
        return {**runtime.snapshot(),'commands':runtime.real.sent,'plan':runtime.plan.report() if runtime.plan else None}
    @app.get('/api/plan')
    def plan():
        return {'report':runtime.plan.report(),'events':[e.as_dict() for e in runtime.plan.events],
                'reinforcements':[e.as_dict() for e in runtime.plan.reinforcements]} if runtime.plan else None
    @app.get('/api/timeline')
    def timeline(): return runtime.timeline.as_dict() if runtime.timeline else None
    @app.get('/api/files')
    def files(): return library.list_files()
    @app.get('/api/files/{name}')
    def metadata(name:str): return _library_call(library.metadata,name)
    @app.post('/api/files')
    async def upload(file:UploadFile=File(...)):
        data=await file.read(MAX_UPLOAD_BYTES+1)
        path=_library_call(library.save_upload,file.filename,data)
        return {'name':path.name}
    async def command_error(peer, message, exc):
        raw=message if isinstance(message,dict) else {}
        operation=raw.get('action'); request=raw.get('requestId')
        if not isinstance(request,str): request=None
        detail=str(exc)
        lab_action={'lab_test':'uruchomienie testu','lab_update':'zmiana parametrów','lab_stop':'zatrzymanie testu'}.get(operation) if isinstance(operation,str) else None
        if lab_action:
            ident=raw.get('deviceId')
            device=runtime.registry.by_id.get(ident,{}) if isinstance(ident,str) else {}
            detail=f"{device.get('name', 'Urządzenie')} · {lab_action}: {detail}"
        incident=diagnostics.incident('command_failure',context={**context(),'action':operation,'requestId':request},error=exc)
        with contextlib.suppress(Exception): await send_peer(peer,{'type':'error','requestId':request,'message':detail,**({'incidentId':incident} if incident else {})})
    command_generation=0
    async def action(peer, owner, message):
        nonlocal command_generation
        operation=message.get('action'); request=message.get('requestId')
        if operation=='stop': command_generation+=1
        generation=command_generation
        diagnostics.record('command_requested',{'action':operation,'requestId':request,'arguments':{k:message[k] for k in ('file','preset','deviceId','deviceIds','muted','position','mode','operation') if k in message}})
        try:
            if operation!='client_error':runtime.require_available()
            if command_lock.locked() and operation=='service' and message.get('operation') in ('power_on','power_off','power_status','firmware','firmware_ble'):
                raise ValueError('DeviceService jest zajęty')
            def perform():
                if operation=='service' and message.get('operation') in ('power_on','power_off','power_status','firmware','firmware_ble'):
                    origin=urlsplit(peer.headers.get('origin',''))
                    if origin.scheme not in ('http','https') or origin.hostname not in ('localhost','127.0.0.1','::1') or origin.netloc!=peer.headers.get('host'):
                        raise ValueError('Sterowanie ATX i upload wymagają lokalnego połączenia z poprawnym Origin')
                if operation!='client_error':runtime.require_available()
                if operation=='set_file': runtime.load(_library_call(library.resolve,message['file']))
                elif operation=='arrangement_preset': runtime.set_preset(message['preset'])
                elif operation=='client_error':
                    ident=diagnostics.incident('browser_failure',context={**context(),'kind':message['kind'],'occurredAt':message.get('occurredAt')},message=message['message']+'\n'+message.get('stack',''))
                    if not ident:raise RuntimeError('Browser diagnostic was not accepted')
                    diagnostics.wait_saved(ident)
                elif operation=='play': runtime.play(owner)
                elif operation=='audio_error': runtime.audio_error(owner,message['epoch'],message.get('message','wyjście niedostępne'))
                elif operation=='pause': runtime.pause()
                elif operation=='stop': runtime.stop()
                elif operation=='seek': runtime.seek(message['position'])
                elif operation=='output': runtime.switch_output(message['mode'])
                elif operation=='speaker_waveform': runtime.set_speaker_waveform(message['deviceId'],message['waveform'])
                elif operation=='speaker_volume': runtime.set_speaker_volume(message['deviceId'],message['output'],message['value'])
                elif operation=='mute': runtime.mute(message['deviceId'],message['muted'])
                elif operation=='mute_group': runtime.mute_group(message['deviceIds'],message['muted'])
                elif operation=='lab_enter': runtime.enter_laboratory(owner)
                elif operation=='lab_leave': runtime.leave_laboratory(owner)
                elif operation in ('lab_test','lab_update'):
                    runtime.test_laboratory(owner,message['deviceId'],message.get('hz',200),message.get('duration',1),message.get('modulation'),update=operation=='lab_update')
                elif operation=='lab_stop': runtime.stop_laboratory(owner,message['deviceId'])
                elif operation=='service': runtime.run_service(message['operation'],confirmed=message.get('confirmed') is True)
                else: raise ValueError('Unknown action')
            if operation in ('output','stop','client_error'):
                # File loading plans outside Player's lock. Changing its output
                # must not wait behind the whole computation; Player.switch
                # still cancels playback and enforces the existing STOP barrier.
                await asyncio.to_thread(perform)
            else:
                async with command_lock:
                    if peers.get(owner) is not peer:
                        raise ValueError('Sesja przeglądarki została zamknięta')
                    if generation!=command_generation:
                        raise ValueError('Polecenie anulowane przez STOP')
                    await asyncio.to_thread(perform)
            diagnostics.record('command_completed',{'action':operation,'requestId':request,**context()})
            await send_peer(peer,{'type':'ack','requestId':request,'state':await asyncio.to_thread(runtime.snapshot)})
        except Exception as exc:
            await command_error(peer,message,exc)
    command_lock=asyncio.Lock()
    @app.websocket('/ws')
    async def websocket(peer:WebSocket):
        import uuid,time
        await peer.accept(); owner=uuid.uuid4().hex; peers[owner]=peer; peer_locks[peer]=asyncio.Lock()
        async with peer_locks[peer]:
            await peer.send_json({'type':'hello','session':owner})
            for event in list(runtime.service.events): await peer.send_json(event)
        diagnostics.record('browser_connected',{})
        try:
            while True:
                raw=None
                try:
                    raw=await peer.receive_json()
                    message=validate_command(raw)
                except (ValueError,TypeError) as exc:
                    await command_error(peer,raw,exc)
                    continue
                if message.get('action')=='audio_ack': runtime.acknowledge_audio(owner,message['token'])
                elif message.get('action')=='sync':
                    runtime.heartbeat(owner)
                    await send_peer(peer,{'type':'sync','sent':message['sent'],'serverTime':time.monotonic()})
                else:
                    if len(tasks)>=128 and message['action'] not in ('stop','output'):
                        await command_error(peer,message,ValueError('Zbyt wiele oczekujących poleceń; poczekaj lub użyj STOP'))
                        continue
                    task=asyncio.create_task(action(peer,owner,message)); tasks.add(task); task.add_done_callback(tasks.discard)
        except WebSocketDisconnect: pass
        finally:
            diagnostics.record('browser_disconnected',context())
            peers.pop(owner,None)
            peer_locks.pop(peer,None)
            await asyncio.to_thread(runtime.disconnect,owner)
    dist=HOST_DIR.parent/'web/dist'
    if dist.exists():
        @app.get('/settings',include_in_schema=False)
        def settings_page(): return FileResponse(dist/'index.html')
        app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    return app

def main(argv=None):
    import uvicorn
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--midi-dir',type=Path,default=HOST_DIR.parent/'midi')
    parser.add_argument('--registry',type=Path,default=None)
    parser.add_argument('--offline',action='store_true',default=os.getenv('ORCHESTRA_OFFLINE')=='1',help='Disable BLE discovery; output still starts REAL')
    args=parser.parse_args(argv)
    uvicorn.run(create_app(midi_dir=args.midi_dir,registry_path=args.registry,connect_on_start=not args.offline,
        diagnostics_dir=os.getenv('ORCHESTRA_DIAGNOSTICS_DIR',str(HOST_DIR.parent/'.runtime/diagnostics/backend'))),host=args.host,port=args.port)
    return 0
if __name__=='__main__': raise SystemExit(main())
