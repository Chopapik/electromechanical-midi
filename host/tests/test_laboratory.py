"""Live laboratory contracts with fake time/transport, never hardware."""
import unittest
from unittest.mock import patch
from test_runtime import Link
from runtime.application import Application
from runtime.outputs import OutputError


class LaboratoryTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.player = self.app.player
        self.now = 100.
        self.player.clock = lambda: self.now
        self.lab = self.app.lab
        self.link = Link()
        self.app.real.attach(self.link)
        self.app.real.configured = True
        self.lab.enter('a')
        self.link.sent.clear()

    def step(self, seconds=.1):
        self.now += seconds
        self.lab.touch('a')
        self.player.tick()

    def test_two_continuous_devices_share_output_without_stopping_each_other(self):
        self.lab.test('a', 'fdd-1', 300, None)
        self.player.tick()
        self.lab.test('a', 'fdd-2', 200, None)
        self.player.tick()
        self.assertEqual(self.link.sent, ['FDD 1 PLAY 300.00', 'FDD 2 PLAY 200.00'])
        for _ in range(120): self.step(1)
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(len(self.lab.jobs), 2)
        self.assertEqual(len(self.link.sent), 2)  # Static REAL tone needs no renew commands.
        self.lab.stop_device('a', 'fdd-1')
        self.assertEqual(self.link.sent[-1], 'FDD 1 STOP')
        self.assertIn('fdd-2', self.lab.jobs)
        self.assertEqual(self.player.state, 'playing')

    def test_independent_finite_deadlines_and_live_update_preserves_duration(self):
        self.lab.test('a', 'fdd-1', 220, 30)
        self.step(2)
        self.lab.test('a', 'fdd-2', 200, 1)
        self.step(1.1)
        self.assertNotIn('fdd-2', self.lab.jobs)
        self.assertIn('fdd-1', self.lab.jobs)
        self.lab.test('a', 'fdd-1', 300, None, update=True)
        self.assertEqual(self.lab.jobs['fdd-1']['end'], 130)
        self.step(27)
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'stopped')
        self.assertIn('ALL STOP token', self.link.sent)

    def test_global_stop_and_switch_clear_all_jobs_no_resume(self):
        self.lab.test('a', 'fdd-1', 220, None)
        self.player.tick()
        self.player.stop()
        self.assertFalse(self.lab.jobs)
        self.lab.test('a', 'fdd-2', 200, None)
        self.player.tick()
        self.player.switch('VIRTUAL')
        self.assertFalse(self.lab.jobs)
        self.player.switch('REAL')
        sent = list(self.link.sent)
        self.step()
        self.assertEqual(self.link.sent, sent)

    def test_session_lease_and_failed_stop_never_restart(self):
        self.lab.test('a', 'fdd-1', 220, None)
        self.player.tick()
        self.link.fail_stop = True
        self.now += 4
        self.lab.expire()
        self.assertIsNone(self.lab.session)
        self.assertFalse(self.lab.jobs)
        self.assertTrue(self.app.real.unknown)
        self.assertNotEqual(self.player.state, 'playing')
        self.assertIn('STOP', self.player.error)

    def test_tick_also_enforces_lease_without_broadcast_worker(self):
        self.lab.test('a', 'fdd-1', 220, None)
        self.player.tick()
        self.now += 4
        self.player.tick()
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'stopped')
        self.assertEqual(self.player.owner, 'orchestra')

    def test_wrong_session_cannot_start_stop_update_or_take_ownership(self):
        for operation in (lambda: self.lab.test('b','fdd-1',220,None),
                          lambda: self.lab.stop_device('b','fdd-1'),
                          lambda: self.lab.enter('b')):
            with self.assertRaises(ValueError): operation()
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.lab.session, 'a')

    def test_offline_power_off_unhomed_disabled_and_muted_block_start(self):
        self.link.device_status['FDD:1']['homed'] = '0'
        with self.assertRaisesRegex(OutputError, 'homing'): self.lab.test('a','fdd-1',220,None)
        self.link.device_status['FDD:1']['homed'] = '1'
        self.link.controller_status['atx'] = 'OFF'
        with self.assertRaisesRegex(OutputError, 'ATX OFF'): self.lab.test('a','fdd-1',220,None)
        self.link.controller_status['atx'] = 'ON'
        with self.assertRaises(ValueError): self.lab.test('a','fdd-8',220,None)
        self.app.router.muted.add('fdd-1')
        with self.assertRaisesRegex(ValueError, 'Mute'): self.lab.test('a','fdd-1',220,None)
        self.app.router.muted.clear()
        self.app.real.link = None
        with self.assertRaisesRegex(OutputError, 'Brak połączenia'): self.lab.test('a','fdd-1',220,None)
        self.assertFalse(self.lab.jobs)

    def test_invalid_numbers_ranges_and_modulations_are_rejected_before_output(self):
        for hz, duration, mod in [(True,1,None),(float('nan'),1,None),(220,0,None),
                                  (220,3601,None),(220,float('inf'),None),(90,None,None),
                                  (400,None,dict(mode='sine',depth=20)),
                                  (220,None,dict(mode='sine',period=.01)),
                                  (220,None,dict(mode='noise'))]:
            with self.assertRaises(ValueError): self.lab.test('a','fdd-1',hz,duration,mod)
        self.assertEqual(self.link.sent, [])
        self.assertFalse(self.lab.jobs)

    def test_modulation_stays_in_profile_and_no_late_catchup_burst(self):
        self.lab.test('a','fdd-1',220,None,dict(mode='sine',depth=10,period=4))
        self.player.tick()
        self.step(1)
        self.assertEqual(self.link.sent[-1], 'FDD 1 PLAY 230.00')
        sent = len(self.link.sent)
        self.step(30)
        self.assertLessEqual(len(self.link.sent)-sent, 1)
        for line in self.link.sent:
            if ' PLAY ' in line: self.assertTrue(210 <= float(line.split()[-1]) <= 230)
        self.assertEqual(self.lab.snapshot()['active']['fdd-1']['duration'], None)

    def test_modulation_cannot_cross_disjoint_profile_bands(self):
        from dataclasses import replace
        original = self.app.registry.profile('DVD_STEPPER_1')
        quantities = dict(original.quantities)
        quantities['continuousRotation'] = replace(quantities['continuousRotation'], value=False)
        profile = replace(original, quantities=quantities)
        with patch.object(self.app.registry,'profile',return_value=profile):
            with self.assertRaises(ValueError):
                self.lab.test('a','DVD_STEPPER_1',230,None,dict(mode='triangle',depth=50))

    def test_hdd_remains_one_shot_and_rate_limited(self):
        for duration, mod in [(None,None),(1,dict(mode='sine'))]:
            with self.assertRaisesRegex(ValueError,'HDD'): self.lab.test('a','hdd_vcm-1',200,duration,mod)
        self.lab.test('a','hdd_vcm-1',200,1)
        self.player.tick()
        self.step(.01)
        self.assertEqual(self.link.sent.count('HDD 1 HIT'), 1)
        with self.assertRaises(ValueError): self.lab.test('a','hdd_vcm-1',200,1)

    def test_failed_write_clears_jobs_and_marks_unknown(self):
        self.lab.test('a','fdd-1',220,None)
        self.link.fail_write = True
        self.player.tick()
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'paused')
        self.assertTrue(self.app.real.unknown)

    def test_link_loss_during_static_tone_cancels_without_auto_resume(self):
        self.lab.test('a','fdd-1',220,None)
        self.player.tick()
        self.app.real.lost('disconnected')
        self.step()
        self.assertFalse(self.lab.jobs)
        replacement = Link()
        self.app.real.attach(replacement)
        self.step()
        self.assertFalse(any(' PLAY ' in line for line in replacement.sent))

    def test_service_owner_cancels_tests(self):
        self.lab.test('a','fdd-1',220,None)
        self.player.tick()
        self.player.select_owner('service')
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'stopped')

    def test_virtual_renews_bounded_tones_and_stops_only_selected_device(self):
        self.player.switch('VIRTUAL')
        packets = []
        def emit(packet):
            packets.append(packet)
            if packet['type'] == 'audio_cancel': self.app.virtual.acknowledge('a',packet['token'])
        self.app.virtual.emit = emit
        self.app.virtual.owner = 'a'
        self.lab.test('a','fdd-1',220,None)
        self.player.tick()
        epoch = self.player.epoch
        self.lab.test('a','fdd-2',300,None)
        self.step()
        self.assertEqual(self.player.epoch, epoch)
        audio = [p for p in packets if p['type'] == 'audio']
        self.assertTrue(all(c['duration'] <= .5 for p in audio for c in p['commands']))
        self.lab.stop_device('a','fdd-1')
        self.assertEqual(packets[-1]['deviceId'], 'fdd-1')
        self.assertEqual(list(self.lab.jobs), ['fdd-2'])
        self.assertFalse(any(' PLAY ' in line for line in self.link.sent))
        self.player.stop()

    def test_power_off_cancels_and_does_not_restore_tests(self):
        self.lab.test('a','fdd-1',220,None)
        self.player.tick()
        self.app.service.run('power_off')
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.link.controller_status['atx'], 'OFF')
        self.step()
        self.assertNotEqual(self.player.state, 'playing')

    def test_catalog_exposes_laboratory_ranges_without_changing_arrangement(self):
        devices = {d['id']:d for d in self.app.registry.catalog()}
        self.assertEqual(devices['fdd-1']['labBands'], [[100,410]])
        self.assertEqual(devices['DVD_STEPPER_1']['bands'], [])
        self.assertGreater(devices['DVD_STEPPER_1']['labBands'][0][1], 600)
