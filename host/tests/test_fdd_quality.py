"""Selective preset, actual hardware allocator and safe runtime switching."""
import dataclasses
import unittest
from unittest.mock import patch
import test_mechanical_arrangement as helper_module
from runtime.application import Application
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.fdd_quality import mechanical_cost
from playback.orchestra import parse_policy
from playback.hardware_profiles import HardwareDeviceState
from test_runtime import Link
from web.server import create_app
from fastapi.testclient import TestClient

class QualityTests(unittest.TestCase):
    setUp=helper_module.MechanicalArrangementTests.setUp;source=helper_module.MechanicalArrangementTests.source;registry=helper_module.MechanicalArrangementTests.registry;plan=helper_module.MechanicalArrangementTests.plan;assert_feasible=helper_module.MechanicalArrangementTests.assert_feasible
    def quality_registry(self,**counts):
        r=self.registry(**counts)
        # Keep cost-strategy fixtures in their original register; the global
        # octave experiment has separate end-to-end coverage.
        for d in r.devices:
            if d['type']=='FDD': d.update(transpose=0, overrides={})
        r.document['parameters']['arrangementPreset']='fdd_quality'
        return r
    def test_steps_reversal_and_short_note_at_endpoint(self):
        r=self.registry();p=r.profile('fdd-1');policy=r.configuration().policy
        for hz,duration in ((200,.36),(300,.24),(400,.18)):
            cost=mechanical_cost(p,HardwareDeviceState(),hz,duration,0,[],policy)
            self.assertAlmostEqual(cost['steps'],72);self.assertEqual(cost['estimatedReversals'],1)
        short=mechanical_cost(p,HardwareDeviceState(away_steps=71),200,.01,0,[],policy)
        self.assertEqual(short['estimatedReversals'],1)
    def test_rest_reduces_phrase_load(self):
        r=self.registry();p=r.profile('fdd-1');policy=r.configuration().policy
        h=[{'start':0.,'end':1.,'steps':200.,'chainStart':0.}]
        dense=mechanical_cost(p,HardwareDeviceState(),200,.2,1.01,h,policy)
        rested=mechanical_cost(p,HardwareDeviceState(),200,.2,1.5,h,policy)
        self.assertGreater(dense['cost'],rested['cost']);self.assertEqual(rested['phraseSteps'],40)
    def test_shortening_is_not_restored_by_sustain_or_continuity(self):
        r=self.quality_registry(dvd=0);r.document['parameters'].update(mechanicalSustain=True,sourceContinuity=True)
        p=self.plan([('Pad',0,[(0,4,60)])],r)
        e=p.events[0];self.assertTrue(e.played);self.assertLess(e.actual_duration,4)
        self.assertEqual(e.outcome,'SHORTENED');self.assertEqual(e.sustain_added,0)
        commands=[c for c in compile_plan(p).commands if c.kind=='tone']
        self.assertTrue(all(c.duration==e.actual_duration for c in commands))
    def test_optional_repeats_are_selective_not_every_other_note(self):
        tracks=[('Pad',0,[(i*.1,i*.1+.08,60) for i in range(40)])]
        balanced=self.plan(tracks,self.registry(fdd=1,dvd=0))
        r=self.quality_registry(fdd=1,dvd=0);q=self.plan(tracks,r)
        self.assertLess(sum(e.played for e in q.events),sum(e.played for e in balanced.events))
        self.assertTrue(q.events[0].played)
        omitted=[i for i,e in enumerate(q.events) if not e.played]
        self.assertTrue(omitted);self.assertNotEqual(omitted,list(range(1,40,2)))
        self.assert_feasible(q,r)
    def test_characteristic_motif_and_bass_survive(self):
        tracks=[('Guitar',0,[(i*.25,i*.25+.15,57+i%5) for i in range(12)]),('Bass',1,[(0,4,48)])]
        r=self.quality_registry(fdd=2,dvd=1);q=self.plan(tracks,r,{'Bass':'bass'})
        self.assertTrue(all(e.played for e in q.events));self.assert_feasible(q,r)
    def test_expensive_material_can_use_dvd(self):
        r=self.quality_registry();q=self.plan([('Pad',0,[(0,3,60)])],r)
        self.assertEqual(q.events[0].device_type,'DVD_SLED');self.assertEqual(q.events[0].actual_duration,3)
        self.assertEqual(q.report()['fddQuality']['dvdTakeovers'],0)  # Sustain was already DVD's role.
        transferred=self.plan([('Guitar',0,[(0,.3,64)])],r)
        self.assertEqual(transferred.events[0].device_type,'DVD_SLED')
        self.assertTrue(transferred.report()['fddQuality']['dvdTakeovers'])
        self.assertTrue(all(r.profile(f'DVD_STEPPER_{i}').get('pitchRatio')==.5 for i in (1,2,3)))
    def test_quality_unison_preserves_primary_and_duty(self):
        r=self.quality_registry(dvd=0);tracks=[('Guitar',0,[(i*.5,i*.5+.2,57+i%5) for i in range(15)])]
        a=self.plan(tracks,r);self.assert_feasible(a,r)
        self.assertTrue(a.reinforcements)
        self.assertLessEqual(sum(e.duration for e in a.reinforcements),a.duration*a.policy['fddQualityUnisonDuty']+1e-9)
        for u in a.reinforcements:
            source=next(e for e in a.events if e.id==u.source_id)
            self.assertEqual((u.start,u.duration,u.hz),(source.actual_start,source.actual_duration,source.played_hz))
        r.document['parameters']['fddUnisonEnabled']=False;b=self.plan(tracks,r)
        self.assertEqual(a.events,b.events)
    def test_balanced_default_equivalence_and_quality_determinism(self):
        tracks=[('Guitar',0,[(0,.2,60),(.4,3,64)])];r=self.registry()
        default=self.plan(tracks,r);r.document['parameters']['arrangementPreset']='balanced'
        self.assertEqual(default.as_dict(),self.plan(tracks,r).as_dict())
        r.document['parameters']['arrangementPreset']='fdd_quality'
        self.assertEqual(self.plan(tracks,r).as_dict(),self.plan(tracks,r).as_dict())
    def test_switch_stops_before_planning_and_does_not_resume(self):
        app=Application(self.registry());app.load(self.source([('Guitar',0,[(0,3,60)])]).path)
        link=Link();app.real.attach(link);app.player.state='playing';revision=app.revision
        original=arrange
        def after_stop(*args):
            self.assertEqual(app.player.state,'stopped');self.assertIn('ALL STOP token',link.sent)
            return original(*args)
        with patch('runtime.application.arrange',side_effect=after_stop):app.set_preset('fdd_quality')
        self.assertEqual(app.revision,revision+1);self.assertEqual(app.plan.policy['arrangementPreset'],'fdd_quality')
        self.assertEqual(app.player.state,'stopped');self.assertEqual(app.timeline,compile_plan(app.plan))
        before=app.timeline
        app.router.switch('VIRTUAL');self.assertEqual(app.timeline,before)
        app.set_preset('balanced');self.assertEqual(app.plan.policy['arrangementPreset'],'balanced')
    def test_playing_virtual_cancels_audio_before_rebuild(self):
        app=Application(self.registry());app.load(self.source([('Guitar',0,[(0,3,60)])]).path)
        app.router.switch('VIRTUAL');app.virtual.owner='browser';app.virtual.active=True;app.player.state='playing'
        messages=[]
        def emit(message):
            messages.append(message)
            if message['type']=='audio_cancel':app.virtual.acknowledge('browser',message['token'])
        app.virtual.emit=emit
        original=arrange
        def after_cancel(*args):
            self.assertFalse(app.virtual.active);self.assertEqual(messages[0]['type'],'audio_cancel')
            return original(*args)
        with patch('runtime.application.arrange',side_effect=after_cancel):app.set_preset('fdd_quality')
        self.assertEqual(app.player.state,'stopped')
    def test_stop_failure_aborts_switch(self):
        app=Application(self.registry());app.load(self.source([('Guitar',0,[(0,3,60)])]).path)
        link=Link();app.real.attach(link);link.fail_stop=True;old=app.plan
        with self.assertRaises(Exception):app.set_preset('fdd_quality')
        self.assertIs(app.plan,old);self.assertEqual(app.snapshot()['arrangementPreset'],'balanced')
    def test_planning_failure_restores_preset(self):
        app=Application(self.registry());app.load(self.source([('Guitar',0,[(0,3,60)])]).path);old=app.plan
        with patch('runtime.application.arrange',side_effect=ValueError('bad plan')):
            with self.assertRaises(ValueError):app.set_preset('fdd_quality')
        self.assertIs(app.plan,old);self.assertEqual(app.snapshot()['arrangementPreset'],'balanced')
    def test_websocket_switch_ack_rebuilds_plan(self):
        app=Application(self.registry());app.load(self.source([('Guitar',0,[(0,3,60)])]).path)
        with TestClient(create_app(runtime=app,connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                ws.send_json({'action':'arrangement_preset','preset':'fdd_quality','requestId':'preset-test'})
                while True:
                    message=ws.receive_json()
                    if message.get('requestId')=='preset-test':break
                self.assertEqual(message['type'],'ack');self.assertEqual(message['state']['arrangementPreset'],'fdd_quality')
                self.assertEqual(client.get('/api/plan').json()['report']['fddQuality']['preset'],'fdd_quality')
    def test_invalid_policy(self):
        for p in ({'arrangementPreset':'dvd_lead'},{'fddQualityPhraseSteps':0},{'fddQualityDensity':2},{'fddQualityUnisonDuty':float('nan')}):
            with self.assertRaises(ValueError):parse_policy(p)
