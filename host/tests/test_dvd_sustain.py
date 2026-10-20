import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.dvd_sustain import apply
from playback.performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from playback.orchestra import parse_policy
from runtime.registry import DeviceRegistry
from runtime.compiler import compile_plan

DVD = 'DVD_STEPPER_1'

def event(i, start, duration=.15, **changes):
    e = PerformanceEvent(str(i),1,'riff',60+i,None,100,0,start,duration,DVD,'DVD_SLED',
                         60+i,220.+i*20,start,duration,'ACCEPTED')
    return replace(e, **changes)

def plan(events):
    return PerformancePlan('riff',events,[{'id':DVD,'type':'DVD_SLED'}],
                           parse_policy({'dvdContinuousSustain':True}))

class DvdSustainTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {DVD: DeviceRegistry().profile(DVD)}
        self.source = SimpleNamespace()
    def apply(self, p): return apply(p,self.profiles,self.source)
    def test_dynamic_riff_exact_legato_deterministic_and_immutable_attacks(self):
        original = [event(i,i*.25) for i in range(6)]
        p = plan(original); q = plan(original)
        self.assertEqual(self.apply(p)['bridged'],5)
        self.apply(q); self.assertEqual(p.events,q.events)
        for a,b in zip(original,p.events):
            self.assertEqual(replace(b,actual_duration=a.actual_duration,sustain_added=0),a)
        self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),1)
        self.assertEqual(self.apply(p)['bridged'],0)
    def test_repeat_part_channel_stolen_explicit_articulation_and_other_device(self):
        for changes in ({'played_note':60}, {'track':2}, {'channel':1},
                        {'device_type':'FDD'}, {'articulation':'STACCATO'}):
            p=plan([event(0,0),event(1,.25,**changes),event(2,.5)])
            self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
        for outcome in ('SHORTENED','STOLEN'):
            p=plan([event(0,0,outcome=outcome),event(1,.25),event(2,.5)])
            self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
    def test_rest_sparse_long_and_skipped_source_attack(self):
        for events in ([event(0,0,.04),event(1,.24),event(2,.48)],
                       [event(0,0,.9),event(1,1),event(2,2)],
                       [event(0,0,1.2),event(1,1.3),event(2,1.55)],
                       [event(0,0),event(9,.2,outcome='DROPPED',device_id=None),event(1,.25),event(2,.5)]):
            p=plan(events); self.apply(p)
            self.assertEqual(p.events[0],events[0])
    def test_reinforcement_reservation_is_not_consumed(self):
        p=plan([event(i,i*.25) for i in range(3)])
        p.reinforcements=[ReinforcementEvent('other',DVD,.17,.04,220,100)]
        self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
    def test_disabled_and_ceiling(self):
        for policy in ({'dvdContinuousSustain':False},{'dvdMaxBridgeMs':50}):
            p=plan([event(i,i*.25) for i in range(3)]);before=list(p.events)
            p.policy.update(policy); self.apply(p); self.assertEqual(p.events,before)
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): parse_policy({'dvdMaxBridgeMs':value})
    def test_local_tempo_changes_dynamic_threshold(self):
        p=plan([event(i,i*.35,.25) for i in range(4)])
        self.source.tempo=SimpleNamespace(_segments=[SimpleNamespace(seconds=0,tempo=250000)])
        self.assertEqual(self.apply(p)['bridged'],0)
        p.policy['dvdDynamicAware']=False
        self.assertGreater(self.apply(p)['bridged'],0)
    def test_compiler_ulp_only_dvd_and_preserves_real_gap(self):
        for kind,gap,stops in [('DVD_SLED',0.,1),('DVD_SLED',.000001,2),('FDD',0.,2)]:
            p=plan([event(0,.1,.2,device_type=kind),event(1,.3+gap,device_type=kind)])
            p.devices=[{'id':DVD,'type':kind}]
            self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),stops)

    def test_mechanical_veto_preserves_primary(self):
        p=plan([event(i,i*.25) for i in range(3)]); before=list(p.events)
        with patch('playback.dvd_sustain.ChronologyCache.check', return_value=None):
            self.assertEqual(self.apply(p)['bridged'],0)
            self.assertEqual(p.events,before)

    def background(self, events):
        p = plan(events)
        p.policy['arrangementPreset'] = 'instrument_roles'
        return p

    def test_background_slow_repeats_become_one_continuous_run(self):
        original = [event(i, i*.6, .45, note=60, played_note=60, played_hz=220.) for i in range(5)]
        p = self.background(original)
        report = self.apply(p)
        self.assertEqual(report['bridged'], 4)
        self.assertEqual(report['repeatsBridged'], 4)
        self.assertEqual(sum(c.kind == 'stop' for c in compile_plan(p).commands), 1)
        for a, b in zip(original, p.events):
            self.assertEqual(replace(b, actual_duration=a.actual_duration, sustain_added=0), a)
        self.assertEqual(self.apply(p)['bridged'], 0)

    def test_background_preserves_existing_dynamic_links(self):
        original = [event(i, i*.25) for i in range(6)]
        dynamic = plan(original)
        self.apply(dynamic)
        p = self.background(original)
        report = self.apply(p)
        self.assertEqual(report['dynamicBridgesPreserved'], 5)
        self.assertTrue(all(b.actual_duration >= a.actual_duration for a, b in zip(dynamic.events, p.events)))

    def test_background_long_notes_and_polyphonic_inner_voice_can_connect(self):
        p = self.background([event(0, 0, .9), event(1, 1, .9)])
        self.assertEqual(self.apply(p)['bridged'], 1)
        low = [event(i, i*.6, .5, note=48, played_note=48, played_hz=130.8) for i in range(4)]
        upper = [event(20+i, i*.2, .12, note=72+i%3, played_note=72+i%3,
                       device_id='fdd-1', device_type='FDD') for i in range(12)]
        p = self.background(low+upper)
        self.assertEqual(self.apply(p)['bridged'], 3)
        self.assertEqual(p.events[4:], upper)

    def test_background_preserves_phrase_pauses_pickups_accents_and_other_parts(self):
        cases = [
            [event(0, 0, 1), event(1, 2, 1)],
            [event(0, 0, .04), event(1, .25)],
            [event(0, 0, .4, note=60, played_note=60),
             event(1, .5, note=60, played_note=60, velocity=127)],
            [event(0, 0, .4), event(1, .5, track=2)],
            [event(0, 0, .4, articulation='STACCATO'), event(1, .5)],
            [event(0, 0, .4, outcome='SHORTENED'), event(1, .5)],
            [event(0, 0, .15), event(9, .2, outcome='DROPPED', device_id=None), event(1, .5)],
        ]
        for original in cases:
            with self.subTest(events=original):
                p = self.background(original)
                self.apply(p)
                self.assertEqual(p.events[0], original[0])

    def test_background_ceiling_tempo_and_reinforcement_are_hard_limits(self):
        for policy in ({'dvdBackgroundMaxBridgeMs': 50}, {'dvdContinuousSustain': False}):
            p = self.background([event(i, i*.6, .45) for i in range(3)])
            original = list(p.events)
            p.policy.update(policy)
            self.apply(p)
            self.assertEqual(p.events, original)
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): parse_policy({'dvdBackgroundMaxBridgeMs': value})
        p = self.background([event(i, i*.6, .45) for i in range(3)])
        self.source.tempo = SimpleNamespace(_segments=[SimpleNamespace(seconds=0, tempo=100000)])
        self.assertEqual(self.apply(p)['bridged'], 0)
        p = self.background([event(i, i*.6, .45) for i in range(3)])
        self.source = SimpleNamespace()
        p.reinforcements = [ReinforcementEvent('other', DVD, .48, .04, 220, 100)]
        self.apply(p)
        self.assertEqual(p.events[0].actual_duration, .45)

    def test_background_fdd_grace_in_release_gap_does_not_cut_dvd_bed(self):
        # Bodysnatchers 2:16: short guitar ornaments sit between chord gates.
        chord = [event(0, 0, .172619, note=53), event(1, .357142, .35119, note=53)]
        grace = event(9, .178571, .008929, note=53,
                      device_id='fdd-1', device_type='FDD')
        p = self.background(chord+[grace])
        p.devices.append({'id': 'fdd-1', 'type': 'FDD'})
        self.apply(p)
        self.assertAlmostEqual(p.events[0].end, chord[1].start)
        self.assertEqual(p.events[2], grace)
        self.assertEqual(sum(c.kind == 'stop' and c.device_id == DVD
                             for c in compile_plan(p).commands), 1)
        # This exception belongs only to background articulation, and only
        # to already rendered, very short attacks inside the source gap.
        for changes in ({'duration': .04}, {'duration': .2},
                        {'outcome': 'DROPPED', 'device_id': None},
                        {'device_type': 'VHS'}, {'articulation': 'STACCATO'},
                        {'start': .352}):
            with self.subTest(changes=changes):
                p = self.background(chord+[replace(grace, **changes)])
                self.apply(p)
                self.assertEqual(p.events[0], chord[0])
        p = plan(chord+[grace])
        self.apply(p)
        self.assertEqual(p.events[0], chord[0])
    def test_source_continuity_gate_and_both_outputs_share_compiled_schedule(self):
        from runtime.outputs import RealOutput, VirtualOutput
        from playback.articulation import apply_source_continuity
        from playback.capabilities import capabilities_for
        from playback.virtual import VirtualDeviceInstance
        p=plan([event(i,i*.25,actual_duration=.08) for i in range(3)])
        caps=capabilities_for([VirtualDeviceInstance.parse({'id':DVD,'type':'DVD_SLED'})])
        apply_source_continuity(p,caps)
        self.assertEqual(self.apply(p)['bridged'],2)
        timeline=compile_plan(p)
        registry=DeviceRegistry(); real=RealOutput(registry); lines=[]
        real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        packets=[]; virtual=VirtualOutput(packets.append)
        virtual.dispatch(timeline.commands,epoch=1)
        real.dispatch(timeline.commands)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(lines,['SLED 1 PLAY 220.00','SLED 1 PLAY 240.00','SLED 1 PLAY 260.00','SLED 1 STOP'])


class ChronologyCacheTests(unittest.TestCase):
    def test_every_extension_matches_full_replay_and_rejects_invalid_future(self):
        from playback.mechanical_arrangement import ChronologyCache, _chronology
        profile=DeviceRegistry().profile(DVD)
        cache=ChronologyCache(profile)
        events=[event(i,i*.25) for i in range(12)]
        for i in range(len(events)):
            events[i]=replace(events[i],actual_duration=.20)
            self.assertEqual(cache.check(events,[]),_chronology(profile,events,[]))
        invalid=events+[event(99,4,played_hz=1000000)]
        self.assertIsNone(cache.check(invalid,[]))
        self.assertEqual(cache.check(events,[]),_chronology(profile,events,[]))
        overlapping=list(events);overlapping[0]=replace(overlapping[0],actual_duration=.4)
        self.assertIsNone(cache.check(overlapping,[]))
        self.assertEqual(cache.check(events,[]),_chronology(profile,events,[]))

    def test_changed_extra_reservations_cannot_reuse_invalid_cached_tail(self):
        from playback.mechanical_arrangement import ChronologyCache, _chronology
        profile=DeviceRegistry().profile(DVD);cache=ChronologyCache(profile)
        events=[event(i,i*.25) for i in range(8)]
        extras=[ReinforcementEvent('copy',DVD,3,.1,220,100)]
        self.assertEqual(cache.check(events,extras),_chronology(profile,events,extras))
        bad=[replace(extras[0],start=.1)]
        self.assertIsNone(cache.check(events,bad))
        self.assertEqual(cache.check(list(reversed(events)),extras),_chronology(profile,events,extras))

    def test_mutable_percussion_history_snapshots_are_independent(self):
        from playback.mechanical_arrangement import ChronologyCache, _chronology
        profile=DeviceRegistry().profile('hdd_vcm-1');cache=ChronologyCache(profile)
        events=[event(i,i*.3,.084,played_hz=None,device_type='HDD_VCM') for i in range(6)]
        for length in (6,2,4,1,6):
            trial=events[:length]
            self.assertEqual(cache.check(trial,[]),_chronology(profile,trial,[]))
        self.assertEqual(cache.states[0].hit_times,[])
