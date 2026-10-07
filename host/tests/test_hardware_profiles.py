"""Theory, uncertainty, physical scheduler and execution defaults; no live I/O."""
import dataclasses
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'host'))
from playback.hardware_profiles import *
from playback.hardware_arranger import selection_key
from playback.allocator import allocate, ManualPin
from playback.orchestra import default_orchestra, parse_orchestra
from playback.hardware import bind_devices, build_plan_commands
from playback.virtual import VirtualDeviceInstance
from midi_source import MidiSource
from test_allocator import write_tracks, analysis_with


def quantity(value, evidence='MEASURED', confidence='HIGH'):
    return dict(value=value, evidenceType=evidence, confidence='UNKNOWN' if value is None else confidence, source='offline test fixture')

class ProfileTests(unittest.TestCase):
    def setUp(self): self.r=HardwareRegistry()
    def test_reference_not_instance_fact(self):
        p=self.r.effective('DVD_SLED')
        self.assertIsNone(p.get('travelSteps'))
        self.assertIn('reference', p.quantities['referencePhaseResistanceOhm'].source.lower())
    def test_fdd_step_formula(self): self.assertAlmostEqual(step_rate_limit(3),333.333333333)
    def test_unknown_pitch_ratio_no_crash(self):
        p=self.r.effective('DVD_SLED','sled:1',{'pitchRatio':quantity(None)})
        self.assertFalse(evaluate(p,HardwareNote(250,.2,0)).authorized)
    def test_measured_not_replaced_by_hypothesis(self):
        p=self.r.effective('DVD_SLED','sled:1',{'travelSteps':quantity(300,'HYPOTHESIS','LOW')})
        self.assertEqual(p.get('travelSteps'),140)
    def test_safety_unknown_cannot_erase_blocked(self):
        p=self.r.effective('HDD_TONAL',overrides={'safePeakCurrentA':quantity(.1)})
        self.assertEqual(evaluate(p,HardwareNote(440,.1,0,peak_current_a=.2)).physical_load,Verdict.BLOCKED)
    def test_fdd_protocol_execution_limit(self):
        e=evaluate(self.r.effective('FDD'),HardwareNote(400,.2,0))
        self.assertEqual(e.timing,Verdict.BLOCKED);self.assertIn('STEP_INTERVAL_LIMIT',e.reasons)
    def test_measured_fdd_410_exception(self):
        e=evaluate(self.r.effective('FDD','fdd:1'),HardwareNote(410,.2,0));self.assertTrue(e.authorized)
    def test_metadata_roundtrip(self):
        q=HardwareQuantity.parse(quantity(140));self.assertEqual(q.as_dict()['evidenceType'],'MEASURED')
    def test_unknown_mechanical_readiness_rejected(self):
        p=self.r.effective('HDD_PERCUSSION',overrides={'parkMs':quantity(None)})
        e=evaluate(p,HardwareNote(None,.1,0));self.assertFalse(e.authorized)
        self.assertEqual(e.timing,Verdict.UNKNOWN)
    def test_unknown_fdd_travel_rejected(self):
        p=self.r.effective('FDD',overrides={'travelSteps':quantity(None)})
        self.assertFalse(evaluate(p,HardwareNote(220,.1,0)).authorized)
    def test_percussion_phase_and_budget_labels(self):
        e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.084,0))
        self.assertEqual([v['state'] for v in e.readiness['commandPhases']],['HIT','RESET','SETTLE','CONTACT/STRIKE','READY'])
        self.assertIsNone(e.readiness['contactDetected']);self.assertIsNone(e.readiness['thermalBudgetReadyAt'])
    def test_nan_safety_input_rejected(self):
        with self.assertRaises(ValueError):HardwareNote(440,.2,0,peak_current_a=float('nan'))
    def test_unknown_min_note_not_pass(self):
        p=self.r.effective('FDD',overrides={'minCycles':quantity(None)})
        self.assertEqual(evaluate(p,HardwareNote(220,.2,0)).quality,Verdict.UNKNOWN)
    def test_larger_hdd_pulse_requires_safety_data(self):
        p=self.r.effective('HDD_PERCUSSION',overrides={'strikeMs':quantity(6)})
        e=evaluate(p,HardwareNote(None,.086,0));self.assertFalse(e.authorized)
        self.assertEqual(e.physical_load,Verdict.UNKNOWN)
    def test_quieter_hdd_execution_override(self):
        p=self.r.effective('HDD_PERCUSSION',overrides={'strikeMs':quantity(2)})
        self.assertEqual(execution_command(p,'hdd:1'),'HDD 1 PROFILE 40 40 2')
        e=evaluate(p,HardwareNote(None,.082,0));self.assertTrue(e.authorized)
    def test_null_is_unknown(self):
        p=self.r.effective('HDD_PERCUSSION');self.assertIsNone(p.get('safePeakCurrentA'))
        e=evaluate(p,HardwareNote(None,.084,0));self.assertEqual(e.physical_load,Verdict.UNKNOWN)
    def test_unknown_not_safe_for_aggressive(self):
        e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.1,0,aggressive=True))
        self.assertFalse(e.authorized)
    def test_known_current_block(self):
        p=self.r.effective('HDD_PERCUSSION',overrides={'safePeakCurrentA':quantity(.1)})
        e=evaluate(p,HardwareNote(None,.1,0,peak_current_a=.2));self.assertEqual(e.physical_load,Verdict.BLOCKED)
    def test_unknown_impact_not_pass(self):
        e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.1,0,impact_energy_j=.001))
        self.assertEqual(e.physical_load,Verdict.UNKNOWN)
    def test_measured_per_lane(self):
        self.assertEqual(self.r.effective('DVD_SLED','sled:1').get('travelSteps'),140)
        for i in range(2,5):self.assertIsNone(self.r.effective('DVD_SLED',f'sled:{i}').get('travelSteps'))
    def test_override_metadata(self):
        p=self.r.effective('DVD_SLED','sled:2',{'travelSteps':quantity(110)})
        self.assertEqual(p.get('travelSteps'),110);self.assertEqual(p.quantities['travelSteps'].evidence_type,'MEASURED')
    def test_explicit_unknown_revokes(self):
        p=self.r.effective('DVD_SLED','sled:1',{'travelSteps':quantity(None)})
        self.assertIsNone(p.get('travelSteps'));self.assertFalse(evaluate(p,HardwareNote(250,.2,0)).authorized)
    def test_unknown_travel_no_authorization(self):
        e=evaluate(self.r.effective('DVD_SLED'),HardwareNote(250,.2,0));self.assertFalse(e.authorized)
        self.assertIn('TRAVEL_LIMIT_UNKNOWN',e.reasons)
    def test_fdd_calibration_retained(self):
        p=self.r.effective('FDD','fdd:1');self.assertEqual(p.get('musicalHz'),[130,410]);self.assertEqual(p.get('travelSteps'),72)
    def test_bad_metadata_rejected(self):
        with self.assertRaises(ValueError):HardwareQuantity.parse(quantity(None,confidence='HIGH')|{'confidence':'HIGH'})
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):HardwareQuantity.parse(quantity(float('inf')))
    def test_negative_travel_rejected(self):
        with self.assertRaises(ValueError):self.r.effective('DVD_SLED',overrides={'travelSteps':quantity(-1)})
    def test_fdd_min_note(self):
        self.assertAlmostEqual(min_note_ms(self.r.effective('FDD'),100),40)
        self.assertAlmostEqual(min_note_ms(self.r.effective('FDD'),220),20)
    def test_dvd_min_note(self):self.assertEqual(min_note_ms(self.r.effective('DVD_SLED'),100),40)
    def test_tonal_min_note(self):self.assertEqual(min_note_ms(self.r.effective('HDD_TONAL'),100),40)
    def test_reversal_4ms(self):
        p=self.r.effective('FDD',overrides={'reversalIntervalMs':quantity(4)})
        self.assertAlmostEqual(reversal_penalty_ms(p,400),1.5)
    def test_reversal_18ms(self):self.assertAlmostEqual(reversal_penalty_ms(self.r.effective('FDD'),400),15.5)
    def test_preferred_scoring(self):
        p=self.r.effective('FDD');a=evaluate(p,HardwareNote(220,.15,0));b=evaluate(p,HardwareNote(350,.15,0))
        self.assertGreater(a.score,b.score);self.assertIn('OUTSIDE_PREFERRED_RANGE',b.quality_reasons)
    def test_duration_scoring(self):
        p=self.r.effective('FDD');self.assertGreater(evaluate(p,HardwareNote(220,.15,0)).score,evaluate(p,HardwareNote(220,.07,0)).score)
    def test_short_quality_not_hard_block(self):
        e=evaluate(self.r.effective('FDD'),HardwareNote(220,.01,0));self.assertEqual(e.quality,Verdict.DEGRADED)
        self.assertTrue(e.authorized);self.assertIn('NOTE_TOO_SHORT',e.quality_reasons)
    def test_fdd_travel_rates(self):
        e=evaluate(self.r.effective('FDD','fdd:1'),HardwareNote(288,.5,0))
        self.assertEqual(e.reversal_rate,4);self.assertEqual(e.round_trip_rate,2)
        self.assertIn('TRAVEL_REVERSAL',e.quality_reasons)
    def test_signed_transition(self):self.assertEqual(signed_transition_time(300,-300,5000),.12)
    def test_braking_distance(self):self.assertEqual(braking_distance(600,5000),36)
    def test_audio_vs_steps(self):
        p=self.r.effective('DVD_SLED','sled:1',{'pitchRatio':quantity(.5)})
        e=evaluate(p,HardwareNote(150,.2,0));self.assertEqual(e.audio_frequency,150);self.assertEqual(e.step_rate,300)
    def test_sled_projection_bounds(self):
        p=self.r.effective('DVD_SLED','sled:1');s=HardwareDeviceState(position=0.)
        for _ in range(100):
            advance_sled(s,p,600,.02);self.assertGreaterEqual(s.position,0);self.assertLessEqual(s.position,140)
        self.assertEqual(s.position_confidence,'LOW')
    def test_sled_acceleration(self):
        s=HardwareDeviceState(position=70.);advance_sled(s,self.r.effective('DVD_SLED','sled:1'),300,.01)
        self.assertLessEqual(s.current_step_rate,50)
    def test_sled_deceleration(self):
        s=HardwareDeviceState(position=70.,current_step_rate=300.);advance_sled(s,self.r.effective('DVD_SLED','sled:1'),100,.01)
        self.assertGreaterEqual(s.current_step_rate,250);self.assertLess(s.current_step_rate,300)
    def test_hdd_busy_reset(self):
        p=self.r.effective('HDD_PERCUSSION');s=HardwareDeviceState();n=HardwareNote(None,.084,0)
        advance_state(s,p,n,evaluate(p,n,s));self.assertAlmostEqual(s.ready_at,.2)
        self.assertEqual(evaluate(p,HardwareNote(None,.084,.1),s).timing,Verdict.DEGRADED)
    def test_hdd_continuous_rate(self):
        s=HardwareDeviceState(hit_times=[.05,.2,.4,.6,.8]);e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.084,.9),s)
        self.assertIn('CONTINUOUS_HIT_RATE',e.reasons);self.assertGreater(e.ready_at,.9)
    def test_hdd_burst_window(self):
        s=HardwareDeviceState(hit_times=[.05,.1,.15,.2,.25]);e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.084,.3),s)
        self.assertIn('BURST_WINDOW',e.reasons)
    def test_readiness_budgets(self):
        s=HardwareDeviceState(thermal_ready_at=2.,impact_ready_at=3.)
        e=evaluate(self.r.effective('HDD_PERCUSSION'),HardwareNote(None,.084,0),s)
        self.assertEqual(e.ready_at,3);self.assertEqual(e.timing,Verdict.DEGRADED)
    def test_harmonics(self):
        p=self.r.effective('HDD_TONAL');self.assertGreater(harmonic_risk(p,1500,'square'),0)
        self.assertEqual(harmonic_risk(p,1500,'sine'),0)
    def test_unknown_resonance_not_hard_band(self):
        e=evaluate(self.r.effective('HDD_TONAL'),HardwareNote(1500,.2,0))
        self.assertNotEqual(e.quality,Verdict.BLOCKED);self.assertIn('RESONANCE_BANDS_UNKNOWN',e.quality_reasons)
    def test_unknown_excursion_no_tonal_drive(self):
        e=evaluate(self.r.effective('HDD_TONAL'),HardwareNote(440,.2,0));self.assertFalse(e.authorized)
    def test_hypothesis_avoid_band_not_hard_block(self):
        p=self.r.effective('HDD_TONAL',overrides={'avoidBands':quantity([[430,450]],'HYPOTHESIS','LOW')})
        self.assertNotEqual(evaluate(p,HardwareNote(440,.2,0)).quality,Verdict.BLOCKED)
    def test_measured_harmonic_avoid_band_blocks(self):
        p=self.r.effective('HDD_TONAL',overrides={'avoidBands':quantity([[4400,4600]])})
        self.assertEqual(evaluate(p,HardwareNote(1500,.2,0)).quality,Verdict.BLOCKED)
    def test_projected_reversal_count(self):
        p=self.r.effective('FDD','fdd:1');s=HardwareDeviceState();n=HardwareNote(288,.5,0)
        advance_state(s,p,n,evaluate(p,n,s));self.assertEqual(s.travel_reversals,2)
    def test_hdd_transition_not_delta(self):
        p=self.r.effective('HDD_TONAL');s=HardwareDeviceState(current_frequency=400)
        a=evaluate(p,HardwareNote(440,.2,0),s);b=evaluate(p,HardwareNote(880,.2,0),s)
        self.assertEqual(a.transition_time,b.transition_time)
    def test_hdd_tonal_preferred_scoring(self):
        p=self.r.effective('HDD_TONAL');self.assertGreater(evaluate(p,HardwareNote(400,.2,0)).score,evaluate(p,HardwareNote(1200,.2,0)).score)
    def test_outside_range_blocked(self):
        e=evaluate(self.r.effective('FDD'),HardwareNote(2000,.2,0));self.assertEqual(e.quality,Verdict.BLOCKED)
    def test_generated_defaults_match(self):
        subprocess.run([sys.executable,str(ROOT/'scripts/generate_hardware_profiles.py'),'--check'],check=True)
    def test_context_connection_and_inventory(self):
        self.assertFalse(HardwareContext(False).present('fdd:1'))
        self.assertTrue(HardwareContext(True).present('fdd:1'))
        self.assertFalse(HardwareContext(True).present('fdd:2'))
        self.assertFalse(HardwareContext(True,inventory={'fdd:1':False}).present('fdd:1'))

class PhysicalArrangerTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def source(self,notes=None):
        return MidiSource(write_tracks(Path(self.tmp.name)/'g.mid',[('Guitar',0,notes or [(0,.2,57),(.4,.6,60)])]))
    def config(self):
        config=default_orchestra(fdd_count=2,dvd_count=2,hdd_count=0,tray_count=0)
        for d in config.devices:d['mode']='real'
        config.policy.update(mechanicalSustain=False,sourceContinuity=False)
        return config
    def plan(self,config=None,context=None):
        return allocate(self.source(),config or self.config(),hardware_context=context or HardwareContext(True))
    def test_disconnected_no_devices(self):
        p=self.plan(context=HardwareContext(False));self.assertTrue(all(not e.played for e in p.events))
        self.assertEqual({e.reason for e in p.events},{'NO_DEVICE'})
    def test_only_declared_lanes(self):
        p=self.plan();self.assertEqual(set(p.hardware['physicalLanes'].values()),{'fdd:1','sled:1'})
    def test_disabled_ordinal_preserved(self):
        c=self.config();c.devices[0]['enabled']=False
        p=self.plan(c,HardwareContext(True,inventory={'fdd:2':True}))
        self.assertEqual(set(p.hardware['physicalLanes'].values()),{'fdd:2'})
    def test_unmeasured_dvd_blocks(self):
        c=self.config()
        for d in c.devices:d['enabled']=d['type']=='DVD_SLED'
        p=self.plan(c,HardwareContext(True,inventory={'sled:2':True}))
        self.assertTrue(all(not e.played for e in p.events));self.assertEqual(p.events[0].reason,'TRAVEL_LIMIT_UNKNOWN')
    def test_best_quality_device(self):
        c=self.config();c.devices[0]['hardwareOverrides']={'preferredHz':quantity([350,400])}
        p=self.plan(c,HardwareContext(True,inventory={'fdd:1':True,'fdd:2':True}))
        self.assertEqual(p.events[0].device_id,c.devices[1]['id'])
    def test_deterministic(self):self.assertEqual(self.plan().as_dict(),self.plan().as_dict())
    def test_event_three_scores(self):
        e=next(e for e in self.plan().events if e.played)
        self.assertIn('timing',e.hardware);self.assertIn('quality',e.hardware);self.assertEqual(e.hardware['physicalLoad'],'UNKNOWN')
    def test_telemetry_planned_label(self):
        p=self.plan();self.assertIn('not measured',p.report()['hardware']['scope'])
        self.assertGreater(sum(c['playedNotes'] for c in p.hardware['counters'].values()),0)
    def test_schedule_from_plan_not_pcm(self):
        p=self.plan();bound,_=bind_devices(self.config().instances(),2)
        commands=build_plan_commands(p,bound)
        self.assertEqual(sum(c.kind=='play' for c in commands),sum(e.played for e in p.events))
    def test_virtual_legacy_unchanged(self):
        c=self.config()
        for d in c.devices:d['mode']='virtual'
        p=allocate(self.source(),c);self.assertFalse(p.hardware)
    def test_config_roundtrip(self):
        c=self.config();c.hardware={'inventory':{'fdd:1':True}}
        parsed=parse_orchestra(c.as_dict());self.assertEqual(parsed.hardware,c.hardware)
    def test_role_schema(self):
        d=dict(id='hdd',type='HDD_VCM',mode='real',hardwareRole='HDD_TONAL')
        self.assertEqual(VirtualDeviceInstance.parse(d).hardware_role,'HDD_TONAL')
    def test_unknown_hdd_reset_does_not_crash_or_play(self):
        c=default_orchestra(fdd_count=0,dvd_count=0,hdd_count=1,tray_count=0)
        for d in c.devices:
            d['mode']='real'
            if d['type']=='HDD_VCM':d['hardwareOverrides']={'parkMs':quantity(None)}
        source=MidiSource(write_tracks(Path(self.tmp.name)/'drums.mid',[('Drums',9,[(0,.05,36)])]))
        p=allocate(source,c,hardware_context=HardwareContext(True))
        self.assertFalse(p.events[0].played);self.assertIn('PROFILE_PARAMETER_UNKNOWN',p.events[0].reason)
    def test_sparse_hdd_reset_schedule(self):
        c=default_orchestra(fdd_count=0,dvd_count=0,hdd_count=1,tray_count=0)
        for d in c.devices:d['mode']='real'
        source=MidiSource(write_tracks(Path(self.tmp.name)/'drums.mid',[('Drums',9,[(0,.05,36),(.05,.1,36),(.25,.3,36)])]))
        p=allocate(source,c,hardware_context=HardwareContext(True))
        played=[e for e in p.events if e.played]
        self.assertEqual(len(played),2);self.assertGreaterEqual(played[1].actual_start-played[0].actual_start,.2)
        self.assertEqual(p.events[1].reason,'DEVICE_BUSY')
    def test_muted_device_not_physically_allocated(self):
        c=self.config();c.devices[0]['mute']=True
        p=self.plan(c,HardwareContext(True,inventory={'fdd:1':True}))
        self.assertTrue(all(not e.played for e in p.events))
    def test_blocked_candidate_cannot_be_reinforced(self):
        c=self.config();c.dvd_mode='reinforcement'
        p=self.plan(c,HardwareContext(True,inventory={'sled:2':True,'fdd:1':True}))
        self.assertTrue(all(e.device_id==c.devices[0]['id'] for e in p.events if e.played))
        self.assertFalse(any(e.device_id==c.devices[3]['id'] for e in p.reinforcements))
    def test_final_sustain_recheck(self):
        c=self.config();c.policy['mechanicalSustain']=True
        p=self.plan(c,HardwareContext(True,inventory={'fdd:1':True}))
        for e in p.events:
            if e.played:self.assertTrue(e.hardware['authorized'])
        per=p.by_device()
        for events in per.values():
            played=sorted([e for e in events if e.played],key=lambda e:e.actual_start)
            for a,b in zip(played,played[1:]):self.assertLessEqual(a.end,b.actual_start+1e-8)
    def test_unknown_safety_no_compensation(self):
        c=self.config();c.devices[0]['hardwareOverrides']={'safePeakCurrentA':quantity(None)}
        p=self.plan(c);self.assertTrue(all(e.hardware['physicalLoad']=='UNKNOWN' for e in p.events if e.played))

class PhysicalEngineTests(unittest.TestCase):
    """Runtime integration with a captured byte transport. Never connect/start it."""
    def setUp(self):
        from playback.engine import PlaybackEngine, HardwareStatus
        from test_engine import FakeTransport
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=PlaybackEngine(preview_mode=False,wait_ready=False)
        self.engine._controller_target='esp32'
        self.transport=FakeTransport()
        self.transport.protocol_version=2;self.transport.device_status={}
        self.transport.controller_status={'hardware_profiles':'1'}
        self.engine._transport=self.transport
        self.engine._hardware=HardwareStatus(connected=True,homed=True)
        c=default_orchestra(fdd_count=2,dvd_count=2,hdd_count=1,tray_count=0)
        for d in c.devices:d['mode']='real'
        self.engine._orchestra=c
        self.engine._source=MidiSource(write_tracks(Path(self.tmp.name)/'song.mid',[('Guitar',0,[(0,.2,57),(.4,.6,60)])]))
        self.engine._track_index=self.engine._source.tracks[0].index
    def test_runtime_direct_schedule_and_profiles(self):
        self.engine._rebuild_locked(keep_position=False)
        self.assertTrue(self.engine._plan.hardware)
        self.assertEqual(set(self.engine._hardware_bound),{'fdd:1','sled:1','hdd:1'})
        self.assertIn('FDD 1 PROFILE 72 5000 2439',[text for _,text in self.transport.commands()])
        self.assertIn('SLED 1 PROFILE 140 5000 1.0',[text for _,text in self.transport.commands()])
        self.assertFalse(any('FDD 2 ENABLE 1'==c for c in [text for _,text in self.transport.commands()]))
        self.assertTrue(all(c.lane in ('virtual','fdd:1','sled:1','hdd:1') for c in self.engine._timeline.commands))
    def test_snapshot_exposes_planned_vs_status(self):
        self.engine._rebuild_locked(keep_position=False)
        snapshot=self.engine.snapshot()
        self.assertIn('profiles',snapshot['hardwarePlanning']);self.assertIn('devices',snapshot['hardware'])
        self.assertIn('not measured',snapshot['hardwarePlanning']['scope'])
    def test_old_firmware_no_dvd_ramp_assumption(self):
        self.engine._rebuild_locked(keep_position=False)
        self.transport.controller_status={}
        from playback.timeline import Command
        self.assertFalse(self.engine._v2_command_locked(Command(0,'play',hz=250,lane='sled:1')))
        self.assertFalse(any(c=='SLED 1 PLAY 250.00' for c in [text for _,text in self.transport.commands()]))
        self.assertTrue(self.engine._hardware.connected)
    def test_disabled_lane_does_not_shift_ordinal(self):
        self.engine._orchestra.devices[0]['enabled']=False
        self.engine._orchestra.hardware={'inventory':{'fdd:2':True}}
        self.engine._rebuild_locked(keep_position=False)
        self.assertEqual(set(self.engine._hardware_bound),{'fdd:2'})
    def test_configuration_unknown_does_not_send_none(self):
        self.engine._orchestra.devices[0]['hardwareOverrides']={'travelSteps':quantity(None)}
        self.engine._rebuild_locked(keep_position=False)
        self.assertFalse(any('None' in c for c in [text for _,text in self.transport.commands()]))
        self.assertNotIn('FDD 1 ENABLE 1',[text for _,text in self.transport.commands()])
