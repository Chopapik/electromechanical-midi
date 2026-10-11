"""Offline reversed roles, exact pitch decisions and transport parity."""
import unittest
from unittest.mock import patch
import test_mechanical_arrangement as helpers
from playback.dvd_lead import fdd_pitch, PRESET
from pitch import midi_to_hz
from runtime.application import Application
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from test_runtime import Link

class DvdLeadTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    registry=helpers.MechanicalArrangementTests.registry
    plan=helpers.MechanicalArrangementTests.plan
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible
    def experimental(self, **counts):
        r=self.registry(**counts);r.document['parameters']['arrangementPreset']=PRESET;return r
    def test_dvd_main_roles_and_original_register(self):
        r=self.experimental()
        p=self.plan([('Melody',0,[(0,.2,69)]),('Bass',1,[(0,1,48)]),('Pad',2,[(0,1,60)])],r,{'Melody':'lead','Bass':'bass'})
        self.assertTrue(all(e.played and e.device_type=='DVD_SLED' and e.note==e.played_note for e in p.events))
        self.assertEqual(len({e.device_id for e in p.events}),3);self.assert_feasible(p,r)
        self.assertTrue(all(r.profile(f'DVD_STEPPER_{i}').get('pitchRatio')==.5 for i in (1,2,3)))
    def test_three_dvd_voices_and_fdd_fallback(self):
        r=self.experimental();p=self.plan([('Chord',0,[(0,1,n) for n in (69,72,74,76)])],r)
        self.assertEqual(sum(e.device_type=='DVD_SLED' for e in p.events),3)
        f=next(e for e in p.events if e.device_type=='FDD')
        self.assertEqual(f.played_note,f.note-12);self.assertAlmostEqual(f.played_hz,midi_to_hz(f.note)/2)
        self.assertEqual(f.actual_duration,f.duration);self.assert_feasible(p,r)
    def test_no_double_folding_and_outside_range_rejected(self):
        self.assertEqual(fdd_pitch(69,200,410),(57,220.,True))
        n,hz,lowered=fdd_pitch(62,200,410)
        self.assertEqual(n,62);self.assertFalse(lowered);self.assertAlmostEqual(hz,midi_to_hz(62))
        p=self.plan([('Melody',0,[(0,.2,62),(1,1.2,81)])],self.experimental(dvd=0),{'Melody':'lead'})
        self.assertEqual(p.events[0].played_note,62);self.assertFalse(p.events[1].played)
        self.assertEqual(p.report()['dvdLeadLowFdd']['octaveRangeFallback'],1)
    def test_preserve_important_duration_and_source_metadata(self):
        r=self.experimental(dvd=0);r.document['parameters'].update(mechanicalSustain=True,sourceContinuity=True)
        p=self.plan([('Melody',0,[(0,2,69)])],r,{'Melody':'lead'})
        e=p.events[0];self.assertTrue(e.played);self.assertEqual(e.actual_duration,2)
        self.assertEqual((e.note,e.played_note,e.start,e.actual_start),(69,57,0,0))
    def test_selective_unison_matches_and_preserves_primary(self):
        r=self.experimental(dvd=0);tracks=[('Melody',0,[(i*.5,i*.5+.1,69) for i in range(20)])]
        p=self.plan(tracks,r,{'Melody':'lead'});self.assertTrue(p.reinforcements);self.assert_feasible(p,r)
        for u in p.reinforcements:
            e=next(e for e in p.events if e.id==u.source_id)
            self.assertEqual((u.hz,u.start,u.duration),(e.played_hz,e.actual_start,e.actual_duration))
        self.assertLessEqual(sum(u.duration for u in p.reinforcements),p.duration*p.policy['fddQualityUnisonDuty'])
        r.document['parameters']['fddUnisonEnabled']=False
        self.assertEqual(p.events,self.plan(tracks,r,{'Melody':'lead'}).events)
    def test_stop_before_switch_and_shared_real_virtual_timeline(self):
        app=Application(self.experimental());app.load(self.source([('Melody',0,[(0,1,69)])]).path)
        link=Link();app.real.attach(link);app.player.state='playing';original=arrange
        def stopped(*args):
            self.assertEqual(app.player.state,'stopped');self.assertIn('ALL STOP token',link.sent);return original(*args)
        with patch('runtime.application.arrange',side_effect=stopped):app.set_preset(PRESET)
        self.assertEqual(app.timeline,compile_plan(app.plan));timeline=app.timeline
        app.router.switch('VIRTUAL');self.assertEqual(app.timeline,timeline)
        for e in app.plan.events:
            if e.played:
                c=next(c for c in timeline.commands if c.kind=='tone' and c.source_id==e.id)
                self.assertEqual((c.hz,c.time,c.duration),(e.played_hz,e.actual_start,e.actual_duration))
    def test_deterministic_and_existing_presets_survive_roundtrip(self):
        r=self.registry();tracks=[('Pad',0,[(0,.2,69),(1,3,62)])]
        for old in ('balanced','fdd_quality'):
            r.document['parameters']['arrangementPreset']=old;a=self.plan(tracks,r).as_dict()
            r.document['parameters']['arrangementPreset']=PRESET
            self.assertEqual(self.plan(tracks,r).as_dict(),self.plan(tracks,r).as_dict())
            r.document['parameters']['arrangementPreset']=old;self.assertEqual(a,self.plan(tracks,r).as_dict())

    def test_optional_repeated_sustain_leaves_dvd_for_main_attack(self):
        r=self.experimental(fdd=0,dvd=1)
        tracks=[('Pad',0,[(0,.1,60),(.2,3,60)]),('Melody',1,[(1,1.3,69)])]
        p=self.plan(tracks,r,{'Melody':'lead'})
        melody=next(e for e in p.events if e.role=='lead')
        self.assertTrue(melody.played);self.assertEqual(melody.device_type,'DVD_SLED')
        self.assertEqual(melody.actual_start,melody.start);self.assert_feasible(p,r)
    def test_dvd_roles_are_dynamic_not_fixed_lanes(self):
        r=self.experimental(fdd=0,dvd=1)
        p=self.plan([('Melody',0,[(0,.2,69)]),('Bass',1,[(1,1.3,48)])],r,{'Melody':'lead','Bass':'bass'})
        self.assertTrue(all(e.played for e in p.events));self.assertEqual(p.events[0].device_id,p.events[1].device_id)
    def test_stop_failure_keeps_existing_plan(self):
        app=Application(self.registry());app.load(self.source([('Melody',0,[(0,1,69)])]).path)
        link=Link();app.real.attach(link);link.fail_stop=True;old=app.plan
        with self.assertRaises(Exception):app.set_preset(PRESET)
        self.assertIs(app.plan,old);self.assertEqual(app.snapshot()['arrangementPreset'],'balanced')
