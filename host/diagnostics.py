"""Bounded, asynchronous local flight recorder. Never takes playback locks.

No environment dumps, MIDI payloads, firmware images, credentials or locals in traces.
A durable active marker detects unclean exits on the next start (not their cause).
"""
from collections import deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import threading
import time
import traceback
import uuid

_SECRET = re.compile(r'(?i)(authorization|password|secret|token|private.?key|api.?key|signature)')
_TEXT_SECRET = re.compile(r'(?i)(bearer\s+)[\w.+/=-]+|((?:password|secret|token|api[_-]?key|private[_-]?key)\s*[=:]\s*)[^\s,;]+')

def clean(value, depth=0):
    if depth>6: return '[depth limit]'
    if value is None or isinstance(value,bool): return value
    if isinstance(value,(int,float)): return value if math.isfinite(value) else str(value)
    if isinstance(value,str):
        value=re.sub(r'-----BEGIN .*?PRIVATE KEY-----.*?-----END .*?PRIVATE KEY-----','[REDACTED KEY]',value,flags=re.S)
        return _TEXT_SECRET.sub(lambda m:(m.group(1) or m.group(2) or '')+'[REDACTED]',value)[:4000]
    if isinstance(value,dict):
        return {str(k)[:100]:('[REDACTED]' if _SECRET.search(str(k)) else clean(v,depth+1)) for k,v in list(value.items())[:64]}
    if isinstance(value,(list,tuple,deque)):return [clean(v,depth+1) for v in list(value)[-100:]]
    return clean(str(value),depth+1)

class NullDiagnostics:
    def record(self,*args,**kwargs): pass
    def incident(self,*args,**kwargs): return None
    def status(self): return {'enabled':False,'error':None,'lastIncident':None,'droppedEvents':0,'droppedIncidents':0}

class Diagnostics:
    def __init__(self, directory, *, max_bytes=2_000_000, backups=4, keep_incidents=50, capacity=512):
        self.directory=Path(directory)
        self.max_bytes=max_bytes;self.backups=backups;self.keep_incidents=keep_incidents
        self.session=uuid.uuid4().hex
        self.events=queue.Queue(maxsize=capacity);self.incidents=queue.Queue(maxsize=32)
        self.recent=deque(maxlen=100);self.lock=threading.Lock();self.wake=threading.Event()
        self.stopping=threading.Event();self.thread=None;self.sequence=0
        self.error=None;self.last_incident=None;self.dropped_events=0;self.dropped_incidents=0
        self.started=False

    def _atomic(self,path,value):
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
        temporary.replace(path)

    def start(self):
        if self.started:return
        self.started=True
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            marker=self.directory/'active.json'
            previous=None
            existing=sorted(self.directory.glob('incident-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            if existing:self.last_incident=existing[0].stem.removeprefix('incident-')
            if marker.exists():
                try: previous=json.loads(marker.read_text())
                except (ValueError,OSError):previous={'unreadable':True}
            self._atomic(marker,{'session':self.session,'started':datetime.now(timezone.utc).isoformat(),'pid':os.getpid()})
            self.thread=threading.Thread(target=self._run,name='diagnostics-writer',daemon=True)
            self.thread.start()
            self.record('session_started',{'python':os.sys.version.split()[0]})
            if previous:self.incident('unclean_shutdown',context={'previousSession':previous},message='Previous session did not record a clean shutdown; cause unknown')
        except Exception as exc:self._failed(exc)

    def _failed(self,exc):
        with self.lock:self.error=f'{type(exc).__name__}: {clean(str(exc))}'

    def _entry(self,kind,data):
        with self.lock:
            self.sequence+=1
            return {'schema':1,'session':self.session,'seq':self.sequence,'utc':datetime.now(timezone.utc).isoformat(),
                    'monotonic':time.monotonic(),'kind':kind,'data':clean(data)}

    def record(self,kind,data=None):
        if not self.started or self.stopping.is_set():return
        entry=self._entry(kind,data or {})
        with self.lock:self.recent.append(entry)
        try:self.events.put_nowait(entry)
        except queue.Full:
            with self.lock:self.dropped_events+=1
        self.wake.set()

    def incident(self,kind,*,context=None,error=None,message=None):
        if not self.started or self.stopping.is_set():return None
        ident=uuid.uuid4().hex
        entry=self._entry(kind,{'context':context or {},'message':message or (str(error) if error else ''),
            'traceback':''.join(traceback.format_exception(type(error),error,error.__traceback__)) if error else None})
        with self.lock:recent=list(self.recent)
        entry.update(incidentId=ident,recent=recent)
        try:self.incidents.put_nowait(entry)
        except queue.Full:
            with self.lock:self.dropped_incidents+=1
            return None
        self.wake.set()
        return ident

    def status(self):
        with self.lock:return {'enabled':self.started,'session':self.session,'error':self.error,
            'lastIncident':self.last_incident,'droppedEvents':self.dropped_events,'droppedIncidents':self.dropped_incidents}

    def _append(self,entry):
        path=self.directory/'events.jsonl'
        line=json.dumps(entry,ensure_ascii=False,allow_nan=False)+'\n'
        if path.exists() and path.stat().st_size+len(line.encode())>self.max_bytes:
            for i in range(self.backups,0,-1):
                old=path if i==1 else self.directory/f'events.{i-1}.jsonl'
                target=self.directory/f'events.{i}.jsonl'
                if old.exists():old.replace(target)
        with path.open('a',encoding='utf-8') as f:
            f.write(line)
            f.flush()
            if 'incidentId' in entry or entry['kind']=='session_closed':os.fsync(f.fileno())

    def _write(self,entry):
        while entry.get('recent') and len(json.dumps(entry,ensure_ascii=False).encode())>256_000:
            entry['recent'].pop(0)
            entry['historyTruncated']=True
        if 'incidentId' in entry:
            self._atomic(self.directory/f"incident-{entry['incidentId']}.json",entry)
            with self.lock:self.last_incident=entry['incidentId']
            files=sorted(self.directory.glob('incident-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            for path in files[self.keep_incidents:]:path.unlink()
        self._append(entry)

    def _run(self):
        while not self.stopping.is_set() or not self.events.empty() or not self.incidents.empty():
            self.wake.wait(.2);self.wake.clear()
            # Incident queue has priority; seq and monotonic preserve causal order.
            for source in (self.incidents,self.events):
                for _ in range(64):
                    try:entry=source.get_nowait()
                    except queue.Empty:break
                    try:self._write(entry)
                    except Exception as exc:self._failed(exc)
                    finally:source.task_done()
            if not self.events.empty() or not self.incidents.empty():self.wake.set()
        try:
            self._append(self._entry('session_closed',self.status()))
            # Keep the marker if any write failed: do not claim a complete log.
            if self.error is None:(self.directory/'active.json').unlink(missing_ok=True)
        except Exception as exc:self._failed(exc)

    def close(self):
        self.stopping.set();self.wake.set()
        if self.thread:self.thread.join(timeout=3)
        if self.thread and self.thread.is_alive():self._failed(RuntimeError('Diagnostics flush did not finish within 3 s'))

    def wait_saved(self,ident,timeout=2):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if (self.directory/f'incident-{ident}.json').exists():return
            if self.status()['error']:raise RuntimeError('Diagnostic write failed')
            time.sleep(.01)
        raise TimeoutError('Diagnostic persistence timed out')

    def read_incident(self,ident):
        if not re.fullmatch(r'[0-9a-f]{32}',ident):raise ValueError('Invalid incident ID')
        return json.loads((self.directory/f'incident-{ident}.json').read_text())
