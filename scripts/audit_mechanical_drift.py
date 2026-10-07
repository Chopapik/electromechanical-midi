#!/usr/bin/env python3
"""Reproducible MIDI/plan/real-engine timing audit. Never opens hardware.

CSV dispatchTime uses production PlaybackEngine and a virtual clock with
20 ms per transport write; deliveryTime models the detached gateway FIFO.
--wall-clock repeats the production engine run with real monotonic time and
an in-memory transport. Neither mode sends commands to physical devices.
"""
import argparse, csv, json, sys, time, statistics
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from playback.duplicates import normalize
from playback.allocator import allocate
from playback.orchestra import default_orchestra
from playback.hardware_profiles import HardwareContext
from playback.hardware import bind_devices, build_plan_commands
from playback.timeline import Timeline, Command
from playback.engine import PlaybackEngine, PlaybackState

class Clock:
    def __init__(self): self.now=0.
    def monotonic(self): return self.now

class Transport:
    protocol_version=2
    controller_status={}
    device_status={}
    def __init__(self, clock=None, cost=.020): self.clock=clock;self.cost=cost;self.writes=[]
    def send(self,text):
        self.writes.append((self.clock.now if self.clock else time.monotonic(),text))
        if self.clock:self.clock.now+=self.cost
        else:time.sleep(self.cost)
    def poll_lines(self): return []
    def close(self): pass
    def ping(self): pass

def engine_for(timeline, transport, trace):
    engine=PlaybackEngine(keepalive=1000)
    engine._timeline=timeline;engine._transport=transport
    engine._hardware.connected=True;engine._hardware.homed=True
    engine._virtual_mode=False;engine._hardware_active=True
    engine._state=PlaybackState.PLAYING
    engine._on_command=lambda c:trace.append((c,transport.writes[-1][0]))
    return engine

def summary(xs):
    ys=sorted(xs)
    return {'mean':statistics.mean(ys),'min':ys[0],'max':ys[-1],
            'p95':ys[int((len(ys)-1)*.95)],'p99':ys[int((len(ys)-1)*.99)]} if ys else {}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wall-clock',action='store_true');ap.add_argument('--output',default='docs/diagnostics/mechanical-drift');ap.add_argument('--label', default='after', choices=['before','after']);ap.add_argument('--ble-cost-ms',type=float,default=38.589903)
    args=ap.parse_args();out=ROOT/args.output;out.mkdir(parents=True,exist_ok=True)
    source=MidiSource(ROOT/'midi/0002-02-radiohead_1993-creep-[k] (2).mid');normal=normalize(source)
    config=default_orchestra(fdd_count=4,dvd_count=1,hdd_count=0,tray_count=0)
    for d in config.devices:d['mode']='real'
    context=HardwareContext(True,inventory={**{f'fdd:{i}':True for i in range(1,5)},'sled:1':True,'drum:1':True})
    plan=allocate(normal,config,hardware_context=context)
    bound,_=bind_devices(config.instances(),2);commands=build_plan_commands(plan,bound)
    # Runtime also contains virtual-plan events. Include its final stop/duration
    # rather than incorrectly equating the last physical command to MIDI length.
    from playback.virtual import VirtualOrchestra
    virtual=VirtualOrchestra(config.instances())
    virtual_timeline=virtual.render_plan(plan)
    timeline=Timeline.from_commands(list(virtual_timeline.commands)+commands)
    if args.wall_clock:
        transport=Transport();trace=[];engine=engine_for(timeline,transport,trace)
        engine._origin=time.monotonic();engine._last_io=engine._origin
        started=engine._origin;engine.start()
        while engine.state==PlaybackState.PLAYING:
            time.sleep(.2)
        elapsed=time.monotonic()-started;engine.shutdown()
        data={'midi':source.path.name,'timelineDuration':timeline.duration,'realEngineElapsedSeconds':elapsed,'writeCostSeconds':.020,'transport':'in-memory, no hardware','writes':len(transport.writes),'dispatchLag':summary([t-started-c.time for c,t in trace])}
        (out/f'wall-clock-{args.label}.json').write_text(json.dumps(data,indent=2));print(json.dumps(data));return
    clock=Clock();transport=Transport(clock);trace=[];engine=engine_for(timeline,transport,trace);engine._origin=0.
    with patch('playback.engine.time.monotonic',clock.monotonic):
        while engine._state==PlaybackState.PLAYING:
            delay=engine._plan_locked()
            if delay is not None:clock.now+=max(delay,.000001)
    # Index original timestamps by the exact plan event, not nearest MIDI note.
    inverse={d.id:lane for lane,d in bound.items()};lookup={}
    for e in plan.events:
        if e.played:lookup[(inverse[e.device_id],e.actual_start)]=e
    rows=[];delivery_end=0.;cost=args.ble_cost_ms/1000.
    for c,dispatch in trace:
        e=lookup.get((c.lane,c.time)) if c.kind in ('play','drum_on') else None
        wire_count=2 if c.kind=='drum_on' else 1
        # Detached TCP gateway: host dispatch at command deadline, BLE FIFO.
        delivery_start=max(c.time,delivery_end);delivery_end=delivery_start+cost*wire_count
        if e:
            rows.append(dict(eventId=e.id,originalTime=e.start,plannedTime=e.actual_start,commandTime=c.time,
                             dispatchTime=dispatch,deltaFromOriginal=dispatch-e.start,
                             deliveryTime=delivery_start,deliveryDelta=delivery_start-e.start,
                             device=c.lane,command=f'{c.kind} {c.hz:.2f}'))
    with (out/f'creep-events-{args.label}.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
    data={'midi':source.path.name,'originalMidiDuration':source.duration,'normalizedDuration':normal.duration,
          'performancePlanDuration':plan.duration,'physicalCommandDuration':max(c.time for c in commands),
          'commandTimelineDuration':timeline.duration,'simulatedEngineElapsedSeconds':clock.now,
          'lateCommands':engine._late_commands,'discardedAtEnd':engine._end_discarded_commands,'engineTransportCostMs':20,'physicalCommands':len(commands),'physicalWrites':sum(2 if c.kind=='drum_on' else 1 for c in commands),
          'playedEvents':len(rows),'localPlannedDelay':summary([e.actual_start-e.start for e in plan.events if e.played]),
          'engineDispatchLag':summary([r['dispatchTime']-r['commandTime'] for r in rows]),
          'gatewayDeliveryDelta':summary([r['deliveryDelta'] for r in rows]),'gatewayModelFinalDelivery':delivery_end,
          'gatewayModelArchitecture':'unbounded baseline FIFO, comparison only; not corrected gateway','gatewayModelCostMs':cost*1000,'inventory':'offline 4 FDD + DVD1 + VHS; no profile or limit overrides',
          'timeBuckets':[{'from':i,'to':i+30,'planned':summary([r['plannedTime']-r['originalTime'] for r in rows if i<=r['originalTime']<i+30]),'fifo':summary([r['deliveryDelta'] for r in rows if i<=r['originalTime']<i+30])} for i in range(0,240,30)]}
    (out/f'plan-{args.label}.json').write_text(json.dumps(data,indent=2));print(json.dumps(data,indent=2))
if __name__=='__main__':main()
