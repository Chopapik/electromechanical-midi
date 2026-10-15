"""Adaptive source recovery in the actual physical allocator, no motors."""
import unittest
from unittest.mock import patch
import test_mechanical_arrangement as helpers
from playback.fdd_adaptive import DensityMap, PRESET, activity
from playback.allocator import _source_notes
from playback.analysis import analyze
from playback.orchestra import parse_policy
from playback.duplicates import normalize
from runtime.application import Application
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from test_runtime import Link

class AdaptiveTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    registry=helpers.MechanicalArrangementTests.registry
    plan=helpers.MechanicalArrangementTests.plan
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible
    def adaptive_registry(self,**counts):
        r=self.registry(**counts);r.document['parameters']['arrangementPreset']=PRESET;return r
    def riff(self):return [('Riff',0,[(i*.0625,i*.0625+.045,60+i%4) for i in range(64)])]
    def density(self,tracks):
        s=self.source(tracks);return DensityMap(s,_source_notes(s,analyze(s),parse_policy({})),4)
    def test_calm_and_dense_and_smoothed_transitions(self):
        calm=self.density([('Pad',0,[(i*.5,i*.5+.3,60) for i in range(8)])])
        self.assertTrue(all(f['level']==0 for f in calm.frames))
        dense=self.density(self.riff())
        self.assertGreater(max(f['level'] for f in dense.frames),.5)
        self.assertLess(max(abs(a['level']-b['level']) for a,b in zip(dense.frames,dense.frames[1:])),.5)
        # A few fast strum offsets across one bar are not a sustained riff.
        strum=self.density([('Strum',0,[(i*.02,i*.02+.3,60+i) for i in range(4)]+[(2,2.3,60)])])
        self.assertTrue(all(f['level']==0 for f in strum.frames))
    def test_quiet_plan_and_natural_gaps_are_identical(self):
        tracks=[('Pad',0,[(0,.15,60),(2,2.15,64),(5,5.2,67)])];r=self.adaptive_registry(dvd=0)
        a=self.plan(tracks,r);r.document['parameters']['arrangementPreset']='fdd_quality';q=self.plan(tracks,r)
        self.assertEqual(a.events,q.events);self.assertEqual(a.reinforcements,q.reinforcements)
        self.assertEqual(compile_plan(a),compile_plan(q));self.assertEqual(a.hardware['adaptive']['recoveredNotes'],0)
        self.assertGreater(a.hardware['adaptive']['silence']['zeroFddSecondsByCause']['naturalCompositionRest'],3)
    def test_recover_rhythmic_repeats_using_idle_independent_fdd(self):
        tracks=[('Accent',0,[(i*.0625,i*.0625+.04,60) for i in range(96)])]
        r=self.adaptive_registry(dvd=0);r.document['parameters']['fddQualityOptionalCost']=.3
        a=self.plan(tracks,r)
        self.assertGreater(a.hardware['adaptive']['recoveredNotes'],0)
        ids={e.id for e in a.events if e.played}
        self.assertTrue(set(a.hardware['adaptive']['recoveredIds'])<=ids)
        self.assertFalse(a.hardware['adaptive']['lostVsQuality']);self.assert_feasible(a,r)
        self.assertGreater(len({e.device_id for e in a.events if e.played}),1)
    def test_short_riff_gates_restore_without_crossing_source_off_or_future_notes(self):
        tracks=[('Riff',0,[(i*.0625,i*.0625+.16,60+i%4) for i in range(80)])]
        r=self.adaptive_registry(dvd=0);r.document['parameters']['maxNoteSeconds']=.04
        a=self.plan(tracks,r);self.assertGreater(a.hardware['adaptive']['restoredGates'],0)
        self.assertTrue(all(e.end<=e.start+e.duration+1e-8 for e in a.events if e.played))
        self.assert_feasible(a,r);self.assertFalse(a.hardware['adaptive']['lostVsQuality'])
    def test_dvd_sustain_and_pitch_are_preserved(self):
        r=self.adaptive_registry();tracks=self.riff()+[('Bass',1,[(0,4,48)])]
        a=self.plan(tracks,r,{'Bass':'bass'});self.assertTrue(a.hardware['adaptive']['dvdPrimaryPreserved'])
        self.assertTrue(any(e.played and e.device_type=='DVD_SLED' for e in a.events))
        for e in a.events:
            if e.played and e.device_type=='FDD':self.assertEqual(e.played_note%12,e.note%12)
        self.assert_feasible(a,r)
    def test_dynamic_unison_never_replaces_primary_and_no_artificial_notes(self):
        r=self.adaptive_registry(dvd=0);a=self.plan(self.riff(),r)
        r.document['parameters']['fddUnisonEnabled']=False;b=self.plan(self.riff(),r)
        self.assertEqual(a.events,b.events);self.assertEqual(len(a.events),64)
        self.assertTrue(all(e.start==e.actual_start for e in a.events if e.played and e.id in a.hardware['adaptive']['recoveredIds']))
        self.assert_feasible(a,r)
    def test_duplicates_do_not_create_extra_independent_voices(self):
        source=normalize(self.source(self.riff()+[('Dub',1,[(i*.0625,i*.0625+.045,60+i%4) for i in range(64)])]))
        r=self.adaptive_registry(dvd=0);a=arrange(source.source,r)
        self.assertEqual(len(a.events),sum(len(source.notes(t.index)) for t in source.tracks))
    def test_determinism_and_safe_switch_shared_transport(self):
        r=self.adaptive_registry(dvd=0);a=self.plan(self.riff(),r);self.assertEqual(a.as_dict(),self.plan(self.riff(),r).as_dict())
        app=Application(self.registry());app.load(self.source(self.riff()).path)
        link=Link();app.real.attach(link);app.player.state='playing';original=arrange
        def stopped(*args):
            self.assertEqual(app.player.state,'stopped');self.assertIn('ALL STOP token',link.sent);return original(*args)
        with patch('runtime.application.arrange',side_effect=stopped):app.set_preset(PRESET)
        self.assertEqual(app.timeline,compile_plan(app.plan));before=app.timeline
        app.router.switch('VIRTUAL');self.assertEqual(app.timeline,before)
    def test_activity_counts_distinct_devices_and_independent_voices(self):
        p=self.plan([('Chord',0,[(0,.2,n) for n in (60,64,67)])],self.adaptive_registry(dvd=0))
        h=activity(p)['primary'];self.assertAlmostEqual(sum(h['fractions']),1)
        self.assertGreater(h['seconds'][3],0);self.assertEqual(h['seconds'][4],0)

    def test_tempo_and_meter_windows_follow_midi(self):
        import mido
        source=self.source(self.riff())
        midi=mido.MidiFile(source.path)
        midi.tracks[0].append(mido.MetaMessage('set_tempo',tempo=250000,time=1920))
        midi.tracks[0].append(mido.MetaMessage('time_signature',numerator=3,denominator=4,time=0))
        midi.save(source.path)
        from midi_source import MidiSource
        source=MidiSource(source.path)
        d=DensityMap(source,_source_notes(source,analyze(source),parse_policy({})),4)
        self.assertAlmostEqual(d.frames[0]['end']-d.frames[0]['start'],.25)
        after=next(f for f in d.frames if f['start']>=2.)
        self.assertAlmostEqual(after['end']-after['start'],.125)
        self.assertEqual(after['barBeats'],3.)

    def test_restored_delayed_gate_respects_original_note_off(self):
        import dataclasses
        from playback.hardware_arranger import adapt_quality_plan
        from runtime.registry import PlanningProfiles
        tracks=[('Riff',0,[(i*.0625,i*.0625+.16,60+i%4) for i in range(64)])]
        r=self.registry(dvd=0);r.document['parameters'].update(arrangementPreset='fdd_quality',maxNoteSeconds=.04)
        q=self.plan(tracks,r)
        q.events=[dataclasses.replace(e,actual_start=e.actual_start+.01,actual_duration=e.actual_duration-.01) if e.played else e for e in q.events]
        r.document['parameters']['arrangementPreset']=PRESET
        a=adapt_quality_plan(self.source(tracks),r.configuration(),PlanningProfiles(r),q)
        restored=set(a.hardware['adaptive']['restoredGateIds']);self.assertTrue(restored)
        self.assertTrue(all(e.end<=e.start+e.duration+1e-8 for e in a.events if e.id in restored))
