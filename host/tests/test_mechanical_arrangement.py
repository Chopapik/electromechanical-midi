"""Real planning path, synthetic MIDI, fake transports; no physical motion."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback.analysis import analyze
from playback.allocator import allocate
from playback.orchestra import parse_policy
from playback.hardware_profiles import HardwareNote, HardwareDeviceState, evaluate, advance_state
from playback.mechanical_arrangement import phrase_context
from playback.virtual import VirtualOrchestra
from runtime.registry import DeviceRegistry, PlanningProfiles
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.application import Application
from fastapi.testclient import TestClient
from web.server import create_app
from test_allocator import write_tracks
from test_runtime import Link

class MechanicalArrangementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def source(self, tracks): return MidiSource(write_tracks(Path(self.tmp.name)/'fixture.mid',tracks))
    def registry(self, fdd=4, dvd=3):
        r=DeviceRegistry()
        for d in r.devices:
            d['enabled']=(d['type']=='FDD' and int(d['lane'].split(':')[1])<=fdd or
                          d['type']=='DVD_SLED' and int(d['lane'].split(':')[1])<=dvd)
        # These fixtures exercise Balanced, independently of the app default.
        r.document['parameters'].update(arrangementPreset='balanced',mechanicalSustain=False,sourceContinuity=False)
        return r
    def plan(self, tracks, r=None, roles=None):
        r=r or self.registry();source=self.source(tracks);analysis=analyze(source)
        analysis=dataclasses.replace(analysis,roles={f'{t.index}:{n.order}':(roles or {}).get(t.name,'harmony') for t in source.tracks for n in source.notes(t.index)})
        return allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analysis)
    def assert_feasible(self,p,r):
        for d in r.devices:
            profile=r.profile(d['id'])
            if not profile: continue
            state=HardwareDeviceState(position=0. if profile.name=='DVD_SLED' else None)
            notes=[HardwareNote(e.played_hz,e.actual_duration,e.actual_start) for e in p.events if e.played and e.device_id==d['id']]
            notes += [HardwareNote(e.hz,e.duration,e.start) for e in p.reinforcements if e.device_id==d['id']]
            for n in sorted(notes,key=lambda n:n.start):
                ev=evaluate(profile,n,state)
                self.assertTrue(ev.authorized);self.assertLessEqual(ev.ready_at,n.start+1e-8)
                advance_state(state,profile,n,ev)
    def test_short_and_long_on_same_track(self):
        p=self.plan([('Guitar',0,[(0,.15,60),(.3,.45,64),(.6,.75,67),(2,6,60)])])
        self.assertEqual([e.device_type for e in p.events],['FDD','FDD','FDD','DVD_SLED'])
        self.assertEqual(p.events[-1].actual_duration,4)
        self.assertTrue(all('selection' in e.hardware for e in p.events))
    def test_dvd_sustain_bypasses_global_cap(self):
        r=self.registry();r.document['parameters']['maxNoteSeconds']=.1
        p=self.plan([('Pad',0,[(0,7,60)])],r)
        self.assertEqual(p.events[0].device_type,'DVD_SLED');self.assertEqual(p.events[0].actual_duration,7)
    def test_repeated_pitch_phrase_context(self):
        p=self.plan([('Bass',0,[(i*.8,i*.8+.7,48) for i in range(5)])],roles={'Bass':'bass'})
        self.assertTrue(all(e.device_type=='DVD_SLED' for e in p.events))
        self.assertEqual(len({e.device_id for e in p.events}),1)
        self.assertGreater(p.events[2].hardware['selection']['repeatFraction'],.9)
    def test_glass_eyes_style_sustained_chord_fixture(self):
        r=self.registry()
        p=self.plan([('Pad',0,[(0,6,n) for n in (48,55,60)])],r)
        self.assertEqual(len([e for e in p.events if e.played and e.device_type=='DVD_SLED']),3)
        self.assertTrue(all(e.actual_duration==6 for e in p.events))
        self.assert_feasible(p,r)
    def test_all_i_need_style_sustain_and_sample_trigger_fixture(self):
        r=DeviceRegistry()
        source=self.source([('Pad',0,[(0,6,48),(0,6,55)]),('Drum sample triggers',9,[(0,6,36)])])
        p=arrange(source,r)
        drum=next(e for e in p.events if e.channel==9)
        self.assertEqual(drum.device_type,'HDD_VCM');self.assertLess(drum.actual_duration,.5)
        self.assertTrue(any(e.device_type=='DVD_SLED' and e.actual_duration>=5 for e in p.events))
    def test_fdd_dvd_fallback(self):
        p=self.plan([('Pad',0,[(0,3,60)])],self.registry(dvd=0))
        self.assertEqual(p.events[0].device_type,'FDD')
        p=self.plan([('Guitar',0,[(0,.15,60)])],self.registry(fdd=0))
        self.assertEqual(p.events[0].device_type,'DVD_SLED')
    def test_busy_preferred_type_falls_back(self):
        p=self.plan([('Pad',0,[(0,3,60),(0,3,64),(0,3,67),(0,3,69)])],self.registry(fdd=1))
        self.assertEqual(sum(e.device_type=='DVD_SLED' for e in p.events),3)
        self.assertEqual(sum(e.device_type=='FDD' for e in p.events),1)
    def test_priority_reclaims_unimportant_sustain(self):
        r=self.registry(fdd=0,dvd=1)
        p=self.plan([('Pad',0,[(0,8,60)]),('Bass',1,[(1,2,48)])],r,{'Bass':'bass'})
        self.assertEqual([e.outcome for e in p.events],['SHORTENED','ACCEPTED'])
        self.assertEqual(p.events[0].actual_duration,1)
        self.assert_feasible(p,r)
    def test_protected_bass_is_not_stolen_by_harmony(self):
        p=self.plan([('Bass',0,[(0,5,48)]),('Pad',1,[(1,2,60)])],self.registry(fdd=0,dvd=1),{'Bass':'bass'})
        self.assertEqual(p.events[0].actual_duration,5);self.assertFalse(p.events[1].played)
    def test_unison_has_identical_pitch_start_duration_and_two_devices(self):
        r=self.registry(dvd=0);p=self.plan([('Guitar',0,[(0,.25,60)])],r)
        self.assertEqual(len(p.reinforcements),1)
        e=p.events[0];u=p.reinforcements[0]
        self.assertEqual(u.kind,'UNISON');self.assertNotEqual(u.device_id,e.device_id)
        self.assertEqual((u.hz,u.start,u.duration),(e.played_hz,e.actual_start,e.actual_duration))
        self.assertEqual(u.source_id,e.id);self.assert_feasible(p,r)
    def test_any_available_pair_not_fixed_fdd1_fdd2(self):
        r=self.registry(dvd=0)
        r.by_id['fdd-1']['enabled']=False;r.by_id['fdd-2']['enabled']=False
        p=self.plan([('Guitar',0,[(0,.25,60)])],r)
        self.assertEqual({p.events[0].device_id,p.reinforcements[0].device_id},{'fdd-3','fdd-4'})
    def test_dense_polyphony_disables_unison(self):
        r=self.registry(dvd=0)
        p=self.plan([('Guitar',0,[(0,.25,n) for n in (57,60,64,67)])],r)
        self.assertEqual(sum(e.played for e in p.events),4);self.assertEqual(p.reinforcements,[])
        self.assert_feasible(p,r)
    def test_future_primary_prevents_unison_reservation(self):
        r=self.registry(fdd=2,dvd=0)
        p=self.plan([('Guitar',0,[(0,.4,60),(.2,.4,64),(.41,.7,67)])],r)
        self.assertFalse(any(e.source_id==p.events[0].id for e in p.reinforcements))
        self.assert_feasible(p,r)
    def test_unison_on_off_primary_plan_and_determinism(self):
        r=self.registry();tracks=[('Guitar',0,[(i*.3,i*.3+.2,60+i%5) for i in range(12)]),('Pad',1,[(0,4,48)])]
        a=self.plan(tracks,r);self.assertEqual(a.as_dict(),self.plan(tracks,r).as_dict())
        r.document['parameters']['fddUnisonEnabled']=False;b=self.plan(tracks,r)
        self.assertEqual(a.events,b.events);self.assert_feasible(a,r)
    def test_runtime_compiler_and_virtual_renderer_share_unison(self):
        r=self.registry(dvd=0);source=self.source([('Guitar',0,[(0,.25,60)])]);p=arrange(source,r)
        self.assertTrue(p.reinforcements)
        timeline=compile_plan(p);tones=[c for c in timeline.commands if c.kind=='tone']
        self.assertEqual(len(tones),2)
        self.assertEqual((tones[0].time,tones[0].duration,tones[0].hz),(tones[1].time,tones[1].duration,tones[1].hz))
        preview=VirtualOrchestra();preview.render_plan(p)
        self.assertEqual(len([e for e in preview.events if e.kind=='tone']),2)
        app=Application(r);app.load(source.path)
        before=app.timeline.as_dict();app.router.switch('VIRTUAL')
        self.assertEqual(app.timeline.as_dict(),before)
        link=Link();app.real.attach(link);app.router.switch('REAL')
        self.assertEqual(app.timeline.as_dict(),before)
        with patch.object(app.real, 'dispatch') as real_dispatch, patch.object(app.virtual, 'dispatch') as virtual_dispatch:
            app.router.dispatch(app.timeline.commands)
            app.router.switch('VIRTUAL');app.router.dispatch(app.timeline.commands)
            self.assertEqual(real_dispatch.call_args, virtual_dispatch.call_args)
    def test_vhs_hdd_allocations_unchanged(self):
        r=DeviceRegistry();source=self.source([('Vocal',0,[(0,.8,60),(1,2,64)]),('Drums',9,[(0,.1,36),(1,1.1,38)])])
        new=arrange(source,r);r.document['parameters'].update(mechanicalAware=False,fddUnisonEnabled=False)
        old=arrange(source,r)
        self.assertEqual([e for e in new.events if e.device_type in ('VHS','HDD_VCM')],[e for e in old.events if e.device_type in ('VHS','HDD_VCM')])
    def test_policy_rejects_invalid_unison_and_thresholds(self):
        for value in (0,3,True):
            with self.assertRaises(ValueError):parse_policy({'fddUnisonMaxVoices':value})
        for values in ({'dvdSustainThresholdMs':0},{'fddUnisonMinVelocity':128},{'mechanicalPreferenceWeight':float('nan')}):
            with self.assertRaises(ValueError):parse_policy(values)
    def test_plan_api_exposes_source_link_and_diagnostics(self):
        app=Application(self.registry(dvd=0));app.load(self.source([('Guitar',0,[(0,.25,60)])]).path)
        # No lifespan: avoids any background real BLE connection.
        response=TestClient(create_app(runtime=app)).get('/api/plan')
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['reinforcements'][0]['kind'],'UNISON')
        self.assertEqual(data['reinforcements'][0]['sourceId'],data['events'][0]['id'])
        self.assertIn('selection',data['events'][0]['hardware'])
