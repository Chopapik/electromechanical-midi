"""Universal orchestration contracts, independent of the benchmark song names."""
from dataclasses import replace
from pathlib import Path
import unittest

import test_mechanical_arrangement as helpers
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.application import Application
from runtime.registry import DeviceRegistry
from playback.allocator import ManualPin, allocate
from playback.analysis import analyze
from playback.mechanical_arrangement import _chronology
from playback.universal import PRESET


class UniversalTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible

    def registry(self, fdd=4, dvd=4, speakers=False):
        r=helpers.MechanicalArrangementTests.registry(self,fdd=fdd,dvd=dvd)
        r.document['parameters']['arrangementPreset']=PRESET
        for d in r.devices:
            if d['type']=='VHS':d['enabled']=speakers
        return r

    def test_attack_aware_allocation_uses_free_drives_instead_of_late_drops(self):
        source=self.source([('Riff',0,[(i*.06,i*.06+.04,60+i%5) for i in range(30)])])
        r=self.registry(dvd=0)
        p=arrange(source,r)
        self.assertTrue(all(e.played for e in p.events))
        self.assertEqual(p.articulation['fddAttackRate']['suppressedAttacks'],0)
        for d in r.devices:
            if d['type']!='FDD':continue
            starts=[c.time for c in compile_plan(p).commands if c.kind=='tone' and c.device_id==d['id']]
            self.assertTrue(all(b-a>=.12-1e-9 for a,b in zip(starts,starts[1:])))
        self.assert_feasible(p,r)

    def test_monophonic_vocal_legato_overlaps_do_not_erase_syllables(self):
        r=self.registry(speakers=True)
        source=self.source([('Lead Vocal',0,[(i*.2,i*.2+.24,65+i%3) for i in range(24)])])
        p=arrange(source,r)
        self.assertTrue(all(e.played for e in p.events))
        self.assertTrue(all(e.device_id=='vhs-1' for e in p.events))
        self.assertTrue(all(e.actual_duration<=.2+1e-8 for e in p.events[:-1]))
        self.assert_feasible(p,r)

    def test_polyphonic_vocal_falls_back_to_other_voices(self):
        r=self.registry(speakers=True)
        p=arrange(self.source([('Lead Vocal',0,[(0,.5,65),(0,.5,69),(0,.5,72)])]),r)
        self.assertEqual(sum(e.played for e in p.events),3)
        self.assertGreater(len({e.device_id for e in p.events}),1)
        self.assert_feasible(p,r)

    def test_source_identity_determinism_and_filename_independence(self):
        r=self.registry()
        source=self.source([('Riff',0,[(i*.18,i*.18+.12,60+i%7) for i in range(16)]),
                            ('Pad',1,[(0,4,n) for n in (45,52,57)])])
        a=arrange(source,r);b=arrange(source,r)
        self.assertEqual(compile_plan(a),compile_plan(b))
        renamed=Path(self.tmp.name)/'completely-different-name.mid'
        renamed.write_bytes(source.path.read_bytes())
        from midi_source import MidiSource
        self.assertEqual(compile_plan(a),compile_plan(arrange(MidiSource(renamed),r)))
        expected={(t.index,n.order):(n.note,n.start,n.duration,n.channel) for t in source.tracks for n in source.notes(t.index)}
        for e in a.events:
            self.assertEqual((e.note,e.start,e.duration,e.channel),expected[e.track,int(e.id.split(':')[1])])
            if e.played:self.assertEqual((e.played_note-e.note)%12,0)
        self.assert_feasible(a,r)

    def test_sparse_pad_preserves_source_hold_and_real_rest(self):
        r=self.registry()
        p=arrange(self.source([('Pad',0,[(0,3,n) for n in (45,52,57)]+[(5,8,n) for n in (45,52,57)])]),r)
        self.assertTrue(all(e.played and e.device_type=='DVD_SLED' for e in p.events))
        self.assertTrue(all(abs(e.actual_duration-3)<1e-8 for e in p.events))
        self.assertFalse(any(c.kind=='tone' and c.time<5 and c.time+c.duration>3 for c in compile_plan(p).commands))
        self.assert_feasible(p,r)

    def test_high_dvd_notes_fold_to_600_and_long_fdd_fallback_is_short(self):
        for counts in ({'fdd':0,'dvd':4},{'fdd':4,'dvd':0}):
            r=self.registry(**counts)
            p=arrange(self.source([('Pad',0,[(0,4,84)])]),r)
            self.assertTrue(p.events[0].played)
            if counts['dvd']:self.assertLessEqual(p.events[0].played_hz,600)
            else:self.assertLessEqual(p.events[0].actual_duration,.4)
            self.assert_feasible(p,r)

    def test_other_parts_receive_a_voice_before_additional_chord_tones(self):
        r=self.registry(fdd=2,dvd=0)
        source=self.source([('Chord',0,[(0,.2,n) for n in (60,64,67,72)]),('Counterline',1,[(0,.2,65)])])
        analysis=analyze(source)
        analysis=replace(analysis,roles={f'{t.index}:{n.order}':'harmony' for t in source.tracks for n in source.notes(t.index)})
        from runtime.registry import PlanningProfiles
        p=allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analysis)
        self.assertEqual({e.track_name for e in p.events if e.played},{'Chord','Counterline'})
        self.assert_feasible(p,r)

    def test_percussion_is_identical_to_instrument_roles(self):
        r=DeviceRegistry()
        source=self.source([('Riff',0,[(i*.06,i*.06+.04,60+i%5) for i in range(40)]),
                            ('Drums',9,[(i*.12,i*.12+gate,n) for i in range(20) for gate,n in ((.02,36),(.03,38),(.01,42))])])
        r.document['parameters']['arrangementPreset']='instrument_roles'
        before=compile_plan(arrange(source,r))
        r.document['parameters']['arrangementPreset']=PRESET
        after=compile_plan(arrange(source,r))
        self.assertEqual([c for c in before.commands if c.kind=='hit'],[c for c in after.commands if c.kind=='hit'])

    def test_vocal_reservation_prevents_accompaniment_from_taking_main_speaker(self):
        r=self.registry(fdd=0,dvd=0,speakers=True)
        source=self.source([('Lead Vocal',0,[(.1,.4,65),(.6,.9,67),(1.1,1.4,69)]),
                            ('Guitar',1,[(0,.3,72),(.5,.8,74),(1,1.3,76)])])
        p=arrange(source,r)
        vocals=[e for e in p.events if e.track_name=='Lead Vocal']
        self.assertTrue(all(e.played and e.device_id=='vhs-1' for e in vocals))
        self.assertTrue(all(e.device_id!='vhs-1' for e in p.events if e.track_name=='Guitar'))
        self.assert_feasible(p,r)

    def test_noise_and_trays_cannot_receive_tonal_voices(self):
        import mido
        r=self.registry(speakers=True)
        for d in r.devices:
            if d['type']=='DVD_TRAY':d['enabled']=True
        source=self.source([('Noise',0,[(0,1,60)]),('Pad',1,[(0,1,65)])])
        midi=mido.MidiFile(source.path)
        midi.tracks[1].insert(1,mido.Message('program_change',channel=0,program=122,time=0))
        midi.save(source.path)
        from midi_source import MidiSource
        p=arrange(MidiSource(source.path),r)
        noise=next(e for e in p.events if e.track_name=='Noise')
        self.assertFalse(noise.played);self.assertEqual(noise.reason,'UNPITCHED_EFFECT_UNSUPPORTED')
        self.assertFalse(p.tray_events)
        self.assertTrue(all(p.hardware['excludedDevices'][d['id']]=='UNIVERSAL_TRAY_EXCLUDED'
            for d in r.devices if d['type']=='DVD_TRAY'))
        self.assertFalse(any(e.device_type=='DVD_TRAY' for e in p.events if e.played))

    def test_upcoming_dedicated_fx_is_reserved_before_its_source_attack(self):
        import mido
        from midi_source import MidiSource
        r=self.registry(fdd=0,dvd=0,speakers=True)
        source=self.source([('Lead Vocal',0,[(i*.5,i*.5+.3,65+i%3) for i in range(24)]),
                            ('Ornaments',1,[(i*.5+.2,i*.5+.35,82+i%3) for i in range(24)]),
                            ('Accompaniment',2,[(i*.5+.15,i*.5+.35,72) for i in range(24)])])
        midi=mido.MidiFile(source.path)
        midi.tracks[2].insert(1,mido.Message('program_change',channel=1,program=73,time=0))
        midi.save(source.path)
        p=arrange(MidiSource(source.path),r)
        ornaments=[e for e in p.events if e.track_name=='Ornaments']
        self.assertEqual(len(ornaments),24)
        self.assertTrue(all(e.played and e.device_id=='pc-speaker-fx' for e in ornaments))
        self.assertTrue(all(e.device_id!='pc-speaker-fx' for e in p.events if e.track_name=='Accompaniment'))
        self.assert_feasible(p,r)

    def test_manual_transpose_and_gate_are_retained(self):
        from runtime.registry import PlanningProfiles
        r=self.registry(fdd=0,dvd=1)
        source=self.source([('Part',0,[(0,2,60)])])
        analysis=analyze(source)
        note=next(n for t in source.tracks for n in source.notes(t.index))
        track=next(t for t in source.tracks if source.notes(t.index))
        ident=f'{track.index}:{note.order}'
        p=allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),
                   pins={ident:ManualPin('DVD_STEPPER_1','manual',transpose=12,gate=.5)})
        e=next(e for e in p.events if e.id==ident)
        self.assertTrue(e.played)
        self.assertEqual(e.played_note,72)
        self.assertAlmostEqual(e.actual_duration,1.)
        self.assertEqual(e.note,60)
        self.assert_feasible(p,r)

    def test_tempo_and_meter_changes_do_not_move_source_attacks(self):
        import mido
        from midi_source import MidiSource
        r=self.registry()
        source=self.source([('Riff',0,[(i*.2,i*.2+.1,60+i%3) for i in range(24)])])
        midi=mido.MidiFile(source.path)
        midi.tracks[0].extend([mido.MetaMessage('set_tempo',tempo=700000,time=960),
                               mido.MetaMessage('time_signature',numerator=3,denominator=4,time=0),
                               mido.MetaMessage('set_tempo',tempo=350000,time=960)])
        midi.save(source.path);source=MidiSource(source.path)
        p=arrange(source,r)
        self.assertTrue(all(e.played for e in p.events))
        self.assertEqual(compile_plan(p),compile_plan(arrange(source,r)))
        for e in p.events:self.assertLessEqual(e.delay,.09+1e-9)
        self.assert_feasible(p,r)

    def test_polyphonic_bass_track_upper_voice_can_use_fx_but_root_cannot(self):
        from runtime.registry import PlanningProfiles
        r=self.registry(fdd=1,dvd=0,speakers=True)
        source=self.source([('Polyphonic bass label',0,[(0,.3,43),(.01,.25,59)]),
                            ('Lead Vocal',1,[(0,1,65)])])
        analysis=analyze(source)
        analysis=replace(analysis,roles={f'{t.index}:{n.order}':('lead' if t.name=='Lead Vocal' else 'bass')
            for t in source.tracks for n in source.notes(t.index)})
        p=allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analysis)
        root=next(e for e in p.events if e.note==43)
        upper=next(e for e in p.events if e.note==59)
        self.assertEqual(root.device_type,'FDD')
        self.assertEqual(upper.device_id,'pc-speaker-fx')
        self.assert_feasible(p,r)

    def test_monophonic_bass_jump_does_not_enter_the_fx_pool(self):
        from runtime.registry import PlanningProfiles
        r=self.registry(fdd=1,dvd=0,speakers=True)
        source=self.source([('Bass',0,[(0,.05,43),(.06,.2,59)])])
        analysis=analyze(source)
        analysis=replace(analysis,roles={f'{t.index}:{n.order}':'bass'
            for t in source.tracks for n in source.notes(t.index)})
        p=allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analysis)
        self.assertTrue(all(e.device_type!='VHS' for e in p.events))
        self.assert_feasible(p,r)

    def test_application_selection_shares_compiled_schedule_and_stops(self):
        app=Application(self.registry())
        app.load(self.source([('Part',0,[(0,1,60)])]).path)
        app.set_preset(PRESET)
        self.assertEqual(app.timeline,compile_plan(app.plan))
        timeline=app.timeline
        app.player.switch('VIRTUAL')
        self.assertEqual(timeline,app.timeline)
        self.assertEqual(app.player.state,'stopped')
        self.assertFalse(app.plan.policy['fddUnisonEnabled'])


if __name__=='__main__':unittest.main()
