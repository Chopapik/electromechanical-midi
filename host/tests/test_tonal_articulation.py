"""Tonal expression invariants: source timing, curves, tails, actuator priority."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import mido
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.performance import PerformancePlan, PerformanceEvent, ReinforcementEvent
from playback.tonal_articulation import resolve, render, capture, chord_context, Curve, apply_mode
from playback.virtual import VirtualOrchestra
from reference_audio import WavePreview
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra


def event(ident='a',start=0.,duration=.4,device='dvd',kind='DVD_SLED',velocity=90,note=60):
    return PerformanceEvent(ident,1,'Guitar',note,None,velocity,0,start,duration,
        device,kind,note,220.,start,duration,'ACCEPTED')


def plan(events=None,expression=None,program=26):
    events=events or [event()]
    devices={e.device_id:{'id':e.device_id,'type':e.device_type,'name':e.device_id} for e in events}
    return PerformancePlan('Test',events,list(devices.values()),{},
        analysis={'trackPrograms':{'1':[program]}},expression=expression or {})


def lane(p,mode='articulated'):
    o=VirtualOrchestra();o.tonal_mode=mode;o.render_plan(p)
    w=WavePreview();rows=w._plan(o,22050*4)
    return w,[r for r in rows if r[2].kind=='tone'],o


class TonalTest(unittest.TestCase):
    def test_v15_interpolates_parameters_without_changing_gate(self):
        for device in ('FDD','DVD_SLED'):
            for duration in (.0625,1.):
                a=dataclasses.replace(resolve(plan())[0]['a'],device=device,
                    gate=duration,source_duration=duration)
                v1=apply_mode(a,'extreme');v2=apply_mode(a,'extreme_v2')
                mid=apply_mode(a,'extreme_v15')
                for field in ('attack','decay','sustain','release','brightness','transient'):
                    self.assertAlmostEqual(getattr(mid,field),(getattr(v1,field)+getattr(v2,field))*.5)
                self.assertEqual(mid.gate,a.gate)
                self.assertEqual(mid.source_duration,a.source_duration)
                t=np.arange(int((duration+mid.release)*22050),dtype=np.float32)/22050
                y=render(t,mid,220.,duration+mid.release,np)
                self.assertTrue(np.isfinite(y).all())
                self.assertGreater(float(np.max(np.abs(y))),0.)
                indexes=(0,110,220,1000)
                for i in indexes:
                    if i<len(t):self.assertAlmostEqual(float(y[i]),render(float(t[i]),mid,220.,duration+mid.release),places=3)
        p=plan();snapshot=dataclasses.asdict(p)
        w,rows,_=lane(p,'extreme_v15')
        self.assertTrue(rows[0][2].tonal_articulation.extreme_v15)
        self.assertEqual(snapshot,dataclasses.asdict(p))

    def test_v2_source_length_velocity_and_device_profiles(self):
        base=resolve(plan())[0]['a']
        short=apply_mode(dataclasses.replace(base,source_duration=.0625,gate=.0625),'extreme_v2')
        long=apply_mode(dataclasses.replace(base,source_duration=1.,gate=.4),'extreme_v2')
        v1=apply_mode(dataclasses.replace(base,source_duration=1.,gate=.4),'extreme')
        self.assertLess(short.attack,.016)
        self.assertLessEqual(short.release,.300)
        self.assertGreater(long.release,v1.release*1.5)
        mid=apply_mode(dataclasses.replace(base,source_duration=.44),'extreme_v2')
        self.assertTrue(short.release<mid.release<long.release)
        low=apply_mode(dataclasses.replace(base,velocity=40),'extreme_v2')
        high=apply_mode(dataclasses.replace(base,velocity=120),'extreme_v2')
        self.assertGreater(high.transient-low.transient,base.transient)
        fdd=apply_mode(dataclasses.replace(base,device='FDD'),'extreme_v2')
        self.assertNotEqual(fdd.attack,mid.attack)
        dvd=apply_mode(dataclasses.replace(base,device='DVD_SLED'),'extreme_v2')
        self.assertLess(fdd.release,dvd.release)
        continuous=dataclasses.replace(base,profile='CONTINUOUS')
        self.assertEqual(apply_mode(continuous,'extreme_v2'),continuous)

    def test_v2_pcm_and_retrigger_preserve_normal_plan(self):
        p=plan([event(duration=1.),event('b',start=.2,duration=.0625)])
        frozen=dataclasses.asdict(p)
        w,rows,o=lane(p,'extreme_v2')
        self.assertLessEqual(rows[0][3]+rows[0][4],rows[1][3])
        self.assertEqual(dataclasses.asdict(p),frozen)
        self.assertEqual(o.report['dvd']['played'],2)
        for mode in ('raw','articulated','extreme'):
            _,_,previous=lane(p,mode)
            self.assertEqual(o.report,previous.report)
        y,_=w._render_numpy(np,rows,22050,1)
        _,old,_=lane(p,'extreme')
        v1,_=w._render_numpy(np,old,22050,1)
        self.assertGreater(np.linalg.norm(y-v1)/np.linalg.norm(v1),.25)
        py,_=w._render_python(rows,22050,1)
        self.assertTrue(np.allclose(y,py,atol=2e-4))
        # Both offline solo and the application consume these same scheduled rows.
        o.tonal_mode='extreme_v2'
        with tempfile.TemporaryDirectory() as folder:
            w.render(o,1.)
            self.assertTrue(w.path.exists())
            w.close()
        self.assertEqual(dataclasses.asdict(p),frozen)

    def test_note_off_has_tail_but_raw_has_minimal_release(self):
        p=plan();w,rows,_=lane(p);_,raw,_=lane(p,'raw')
        self.assertGreater(rows[0][4]/w.RATE,.45)
        self.assertLess(raw[0][4]/w.RATE,.403)
        y,_=w._render_numpy(np,rows,22050,1)
        self.assertGreater(np.max(np.abs(y[9000:10000])),0)
        self.assertAlmostEqual(y[rows[0][4]-1],0)

    def test_guitar_and_continuous_profiles(self):
        a=resolve(plan())[0]['a'];b=resolve(plan(program=65))[0]['a']
        self.assertEqual(a.profile,'PLUCKED');self.assertEqual(b.profile,'CONTINUOUS')
        self.assertLess(a.sustain,b.sustain)

    def test_velocity_changes_brightness_transient_attack_not_only_gain(self):
        a=resolve(plan([event(velocity=40)]))[0]['a'];b=resolve(plan([event(velocity=120)]))[0]['a']
        self.assertLess(a.brightness,b.brightness);self.assertLess(a.transient,b.transient)
        self.assertGreater(a.attack,b.attack)

    def test_short_note_stays_short(self):
        w,r,_=lane(plan([event(duration=.07)]))
        self.assertTrue(r[0][2].tonal_articulation.staccato)
        self.assertLess(r[0][4]/w.RATE,.082)

    def test_long_pluck_decays_but_keeps_body(self):
        a=resolve(plan([event(duration=2)]))[0]['a']
        # RMS windows avoid mistaking oscillator zero crossings for gate silence.
        t=np.arange(45000)/22050;y=render(t,a,220,2.07,np)
        self.assertGreater(np.sqrt(np.mean(y[100:1500]**2)),np.sqrt(np.mean(y[30000:40000]**2)))
        self.assertGreater(np.max(np.abs(y[30000:40000])),.01)

    def test_retrigger_is_mono_and_does_not_mutate_primary(self):
        p=plan([event(),event('b',.4,.2)]);before=[dataclasses.asdict(e) for e in p.events]
        w,r,_=lane(p)
        self.assertEqual(w.tonal_stats['retriggers'],1)
        self.assertLessEqual(r[0][3]+r[0][4],r[1][3])
        self.assertEqual(before,[dataclasses.asdict(e) for e in p.events])
        y,_=w._render_numpy(np,r[:1],22050,1)
        self.assertAlmostEqual(y[r[0][4]-1],0)

    def test_strum_microtiming_preserved_and_simultaneous_chord_not_invented(self):
        p=plan([event(str(i),t,note=n,device=str(i)) for i,(t,n) in enumerate([(0,60),(.011,64),(.023,67),(.036,72)])])
        _,r,o=lane(p)
        self.assertEqual(sorted(x[2].time for x in r),[0,.011,.023,.036])
        self.assertEqual(len(o.strum_groups),1)
        self.assertTrue(all(x[2].tonal_articulation.strum_like for x in r))
        simultaneous=[dataclasses.replace(e,start=0,actual_start=0) for e in p.events]
        self.assertEqual(chord_context(simultaneous)[1],[])

    def test_legato_only_continuous_source_and_not_simultaneous_chord(self):
        p=plan([event(),event('b',.3)],program=65)
        self.assertTrue(resolve(p)[0]['b'].legato)
        self.assertFalse(resolve(plan(p.events))[0]['b'].legato)
        self.assertFalse(resolve(plan([event(),event('b')],program=65))[0]['b'].legato)

    def test_sustain_holds_keyoff_until_pedal_up_without_voice_reservation(self):
        cc=lambda t,v:{'time':t,'kind':'control_change','control':64,'value':v}
        p=plan([event(duration=.1)],{'0':[cc(0,127),cc(.7,0)]})
        a=resolve(p)[0]['a'];self.assertTrue(a.pedal);self.assertAlmostEqual(a.gate,.7)
        self.assertEqual(p.events[0].actual_duration,.1)
        p.events.append(event('b',.2,.1));w,r,_=lane(p)
        self.assertLessEqual(r[0][3]+r[0][4],r[1][3]);self.assertTrue(p.events[1].played)

    def test_transport_includes_final_pedal_release_tail(self):
        p=plan([event(duration=.1)],{'0':[{'time':0,'kind':'control_change','control':64,'value':127},
            {'time':1.,'kind':'control_change','control':64,'value':0}]})
        o=VirtualOrchestra(); timeline=o.render_plan(p)
        self.assertGreater(timeline.duration,1.)
        self.assertEqual(p.duration,.1)

    def test_cc_volume_expression_multiplied_once_and_time_varying(self):
        p=plan(expression={'0':[{'time':0,'kind':'control_change','control':7,'value':64},
            {'time':0,'kind':'control_change','control':11,'value':32},
            {'time':.2,'kind':'control_change','control':11,'value':100}]})
        a=resolve(p)[0]['a'];self.assertAlmostEqual(a.gain.at(0),64*32/127**2)
        self.assertAlmostEqual(a.gain.at(.3),64*100/127**2)

    def test_bend_rpn_preserved_continuous_phase_not_retriggered(self):
        stream=[{'time':0,'kind':'control_change','control':cc,'value':v} for cc,v in [(101,0),(100,0),(6,12)]]
        stream.append({'time':.1,'kind':'pitchwheel','value':4096})
        p=plan(expression={'0':stream});a=resolve(p)[0]['a']
        self.assertAlmostEqual(a.frequency.at(.2),220*2**.5)
        self.assertGreater(a.frequency.at(.097),220)
        self.assertEqual(len(lane(p)[1]),1)
        self.assertAlmostEqual(a.frequency.integral(.1-1e-8),a.frequency.integral(.1+1e-8),places=4)

    def test_modulation_only_when_source_requests_it(self):
        a=resolve(plan())[0]['a'];self.assertEqual(a.modulation.at(.2),0)
        p=plan(expression={'0':[{'time':0,'kind':'control_change','control':1,'value':64}]})
        self.assertGreater(resolve(p)[0]['a'].modulation.at(.2),0)

    def test_device_profiles_differ(self):
        f=resolve(plan([event(kind='FDD')]))[0]['a'];d=resolve(plan())[0]['a']
        self.assertLess(f.attack,d.attack);self.assertLess(f.release,d.release)
        t=np.arange(1000)/22050
        self.assertFalse(np.allclose(render(t,f,220,.47,np),render(t,d,220,.47,np)))

    def test_reinforcement_inherits_profile_and_cannot_change_normal_tail(self):
        p=plan([event(kind='FDD',device='fdd')]);p.devices.append({'id':'dvd','type':'DVD_SLED'})
        p.reinforcements=[ReinforcementEvent('a','dvd',0,.4,220.,90)]
        w,r,_=lane(p);extra=next(x[2].tonal_articulation for x in r if x[2].reinforcement)
        self.assertEqual(extra.profile,'PLUCKED');self.assertEqual(extra.program,26)
        self.assertEqual(extra.device,'DVD_SLED')
        # Same-device extra cannot choke the existing PRIMARY release.
        p.reinforcements=[ReinforcementEvent('a','fdd',.41,.1,220.,90)]
        _,with_extra,_=lane(p);p.reinforcements=[];_,normal,_=lane(p)
        self.assertEqual(with_extra[0][4],normal[0][4]);self.assertEqual(len(with_extra),1)

    def test_python_numpy_equivalence_including_bend_and_release(self):
        p=plan(expression={'0':[{'time':.1,'kind':'pitchwheel','value':2000}]})
        w,r,_=lane(p);a,_=w._render_numpy(np,r,14000,1);b,_=w._render_python(r,14000,1)
        np.testing.assert_allclose(a,np.asarray(b),atol=2e-6)

    def test_parser_expression_on_conductor_track_and_sub_tick_onsets(self):
        with tempfile.TemporaryDirectory() as folder:
            m=mido.MidiFile(ticks_per_beat=1000)
            m.tracks.append(mido.MidiTrack([mido.Message('control_change',channel=0,control=11,value=70)]))
            m.tracks.append(mido.MidiTrack([mido.Message('program_change',program=26),
                mido.Message('note_on',note=60,velocity=80),mido.Message('note_on',note=64,velocity=85,time=22),
                mido.Message('note_off',note=60,time=200),mido.Message('note_off',note=64,time=22)]))
            path=Path(folder)/'expression.mid';m.save(path);s=MidiSource(path)
            self.assertAlmostEqual(s.notes(1)[1].start,.011)
            p=allocate(normalize(s),default_orchestra())
            self.assertEqual(sorted(e.start for e in p.events),[0,.011])
            self.assertTrue(any(e.get('control')==11 for e in p.expression['0']))

    def test_extreme_profile_is_diagnostic_and_continuous_unchanged(self):
        a=resolve(plan())[0]['a'];x=apply_mode(a,'extreme')
        self.assertTrue(x.extreme)
        self.assertTrue(.025<=x.attack<=.040)
        self.assertTrue(.250<=x.decay<=.350)
        self.assertTrue(.1<=x.sustain<=.2)
        self.assertTrue(.300<=x.release<=.500)
        continuous=resolve(plan(program=65))[0]['a']
        self.assertEqual(apply_mode(continuous,'extreme'),continuous)
        low=apply_mode(resolve(plan([event(velocity=40)]))[0]['a'],'extreme')
        high=apply_mode(resolve(plan([event(velocity=120)]))[0]['a'],'extreme')
        self.assertGreater(high.transient,low.transient*8)
        self.assertGreater(high.brightness,low.brightness*8)

    def test_extreme_final_pcm_differs_beyond_a_scalar_gain(self):
        import wave
        p=plan();snapshot=dataclasses.asdict(p)
        signals={}
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('raw','articulated','extreme'):
                w,rows,o=lane(p,mode)
                w.render(o,1.)  # Same WAV entry point used by the playback worker.
                try:
                    with wave.open(str(w.path),'rb') as wav:
                        signals[mode]=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(float)
                finally: w.close()
                self.assertEqual(snapshot,dataclasses.asdict(p))
                self.assertEqual(rows[0][2].time,p.events[0].actual_start)
            raw,ext=signals['raw'],signals['extreme']
            fit=np.dot(raw,ext)/np.dot(raw,raw)
            self.assertGreater(np.linalg.norm(ext-fit*raw)/np.linalg.norm(raw),.3)
            # Check real PCM after NOTE_OFF, rather than inspecting release params.
            self.assertGreater(np.max(np.abs(ext[int(.5*22050)*2:int(.6*22050)*2])),0)
            self.assertTrue(np.all(raw[int(.5*22050)*2:]==0))
            w,rows,_=lane(p,'extreme');l,_=w._render_numpy(np,rows,22050,1);q,_=w._render_python(rows,22050,1)
            np.testing.assert_allclose(l,np.asarray(q),atol=2e-6)

    def test_extreme_short_notes_and_retrigger_keep_physical_plan(self):
        p=plan([event(duration=.07),event('b',.07,.07)])
        snapshot=dataclasses.asdict(p);w,rows,_=lane(p,'extreme')
        self.assertLess(rows[1][2].tonal_articulation.release,.04)
        self.assertLessEqual(rows[0][3]+rows[0][4],rows[1][3])
        self.assertEqual(snapshot,dataclasses.asdict(p))


if __name__=='__main__':unittest.main()
