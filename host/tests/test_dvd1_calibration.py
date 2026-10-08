"""Individual measured DVD1 bands: host allocation, final validation and folding."""
import dataclasses
import tempfile
import unittest
from pathlib import Path
from playback.hardware_profiles import HardwareRegistry, HardwareNote, HardwareProfile, HardwareDeviceState, HardwareContext, evaluate
from playback.hardware_arranger import fold_for_profile, validate_reinforcement
from playback.allocator import allocate, ManualPin
from playback.orchestra import default_orchestra
from playback.hardware import build_plan_commands, bind_devices
from playback.virtual import VirtualOrchestra
from midi_source import MidiSource
from test_allocator import write_tracks
from test_hardware_profiles import quantity

class Dvd1CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = HardwareRegistry()
        self.profile = self.registry.effective('DVD_SLED', 'sled:1')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_allowed_forbidden_and_unsampled_gaps(self):
        for hz in (150,160,220,250,320,490,49,125,175,195,265,305,335,475,501):
            with self.subTest(hz=hz):
                result = evaluate(self.profile, HardwareNote(hz,.5,0))
                self.assertFalse(result.authorized)
                self.assertIn('OUTSIDE_ALLOWED_BANDS',result.reasons)
        for hz in (50,100,120,180,190,270,280,300,340,400,440,470):
            with self.subTest(hz=hz):self.assertTrue(evaluate(self.profile, HardwareNote(hz,.5,0)).authorized)

    def test_only_dvd1_and_measured_metadata(self):
        self.assertEqual(self.profile.quantities['allowedBandsHz'].evidence_type,'MEASURED')
        for lane in ('sled:2','sled:3','sled:4'):
            profile = self.registry.effective('DVD_SLED',lane)
            self.assertIsNone(profile.get('allowedBandsHz'))
            self.assertTrue(evaluate(profile,HardwareNote(250,.5,0)).authorized)

    def test_invalid_bands_and_overrides(self):
        for value in ([],[[-1,50]],[[100,50]],[[50,100],[90,120]],[[True,100]],[[50,float('nan')]],[[120,150],[50,100]]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.registry.effective('DVD_SLED', overrides={'allowedBandsHz':quantity(value)})
        with self.assertRaises(ValueError):self.profile.overlay({'allowedBandsHz':quantity(None)})
        with self.assertRaises(ValueError):self.profile.overlay({'allowedBandsHz':quantity([[50,500]])})

    def test_ratio_preserves_physical_bands_and_min_period(self):
        profile = self.profile.overlay({'pitchRatio':quantity(2)})
        self.assertFalse(evaluate(profile,HardwareNote(440,.5,0)).authorized)
        self.assertTrue(evaluate(profile,HardwareNote(200,.5,0)).authorized)
        fold = fold_for_profile(57,100,940,'auto',profile)
        self.assertTrue(evaluate(profile,HardwareNote(fold.hz,.5,0)).authorized)
        fast = self.registry.effective('DVD_SLED','sled:2',{'pitchRatio':quantity(.001),'musicalStepRate':quantity([1,1000000])})
        self.assertIn('STEP_INTERVAL_LIMIT',evaluate(fast,HardwareNote(100,.5,0)).reasons)

    def config(self):
        config=default_orchestra(fdd_count=1,dvd_count=1,hdd_count=0,tray_count=0)
        for d in config.devices:d['mode']='real'
        config.policy.update(mechanicalSustain=False,sourceContinuity=False)
        return config

    def test_220_folds_to_440_and_commands_renderer_agree(self):
        source=MidiSource(write_tracks(Path(self.tmp.name)/'a.mid',[('Guitar',0,[(0,.5,57)])]))
        config=self.config();dvd=next(d for d in config.devices if d['type']=='DVD_SLED')
        plan=allocate(source,config,hardware_context=HardwareContext(True,inventory={'sled:1':True}),pins={'1:0':ManualPin(rule_id='test',device_id=dvd['id'])})
        event=next(e for e in plan.events if e.played)
        self.assertAlmostEqual(event.played_hz,440)
        self.assertEqual(event.played_note,69)
        preview=VirtualOrchestra();preview.render_plan(plan)
        self.assertTrue(any(e.kind=='tone' and abs(e.hz-440)<1e-6 for e in preview.events))
        commands=build_plan_commands(plan,bind_devices(config.instances(),2)[0])
        self.assertTrue(any(c.kind=='play' and c.hz==440 for c in commands))

    def test_no_octave_reassigns_or_drops_and_manual_no_fold_rejects(self):
        source=MidiSource(write_tracks(Path(self.tmp.name)/'a.mid',[('Guitar',0,[(0,.5,57)])]))
        config=self.config();dvd=next(d for d in config.devices if d['type']=='DVD_SLED')
        dvd['hardware_overrides']={'musicalStepRate':quantity([200,260])}
        pin={'1:0':ManualPin(rule_id='test',device_id=dvd['id'])}
        plan=allocate(source,config,hardware_context=HardwareContext(True,inventory={'sled:1':True,'fdd:1':True}),pins=pin)
        self.assertEqual(plan.events[0].device_type,'FDD')
        self.assertTrue(plan.events[0].reassigned)
        plan=allocate(source,config,hardware_context=HardwareContext(True,inventory={'sled:1':True}),pins=pin)
        self.assertFalse(plan.events[0].played)
        dvd.pop('hardware_overrides')
        plan=allocate(source,config,hardware_context=HardwareContext(True,inventory={'sled:1':True}),pins={'1:0':ManualPin(rule_id='test',device_id=dvd['id'],octave_fold=False)})
        self.assertFalse(plan.events[0].played)

    def test_reinforcement_cannot_use_forbidden_frequency(self):
        from types import SimpleNamespace
        plan=SimpleNamespace(events=[],reinforcements=[SimpleNamespace(device_id='dvd',start=0,duration=.5,hz=220)],tray_events=[],hardware={})
        validate_reinforcement(plan,{'dvd':self.profile},{'dvd':'sled:1'})
        self.assertEqual(plan.reinforcements,[])
