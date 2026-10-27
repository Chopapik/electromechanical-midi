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
        for key, state in self.link.device_status.items():
            if key.startswith('FDD:'): state['track0'] = '1'
        self.lab.enter('a')
        self.link.sent.clear()

    def start(self, session, ident, *args, **kwargs):
        self.lab.test(session, ident, *args, **kwargs)
        if self.app.router.mode == 'REAL' and self.app.registry.by_id[ident]['type'] == 'FDD':
            self.player.tick()  # Request a fresh post-HOME status.
            self.player.tick()  # Receive the complete status and start tone.

    def step(self, seconds=.1):
        self.now += seconds
        self.lab.touch('a')
        self.player.tick()

    def test_two_continuous_devices_share_output_without_stopping_each_other(self):
        self.start('a', 'fdd-1', 300, None)
        self.player.tick()
        self.start('a', 'fdd-2', 200, None)
        self.player.tick()
        self.assertEqual(self.link.sent, ['FDD 1 STOP', 'FDD 1 HOME', 'FDD 1 PLAY 300.00',
                                          'FDD 2 STOP', 'FDD 2 HOME', 'FDD 2 PLAY 200.00'])
        for _ in range(120): self.step(1)
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(len(self.lab.jobs), 2)
        self.assertEqual(len(self.link.sent), 6)  # Static REAL tone needs no renew commands.
        self.lab.stop_device('a', 'fdd-1')
        self.assertEqual(self.link.sent[-1], 'FDD 1 STOP')
        self.assertIn('fdd-2', self.lab.jobs)
        self.assertEqual(self.player.state, 'playing')

    def test_independent_finite_deadlines_and_live_update_preserves_duration(self):
        self.start('a', 'fdd-1', 220, 30)
        self.step(2)
        self.start('a', 'fdd-2', 200, 1)
        self.step(1.1)
        self.assertNotIn('fdd-2', self.lab.jobs)
        self.assertIn('fdd-1', self.lab.jobs)
        self.start('a', 'fdd-1', 300, None, update=True)
        self.assertEqual(self.lab.jobs['fdd-1']['end'], 130)
        self.step(27)
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'stopped')
        self.assertIn('ALL STOP token', self.link.sent)

    def test_global_stop_and_switch_clear_all_jobs_no_resume(self):
        self.start('a', 'fdd-1', 220, None)
        self.player.tick()
        self.player.stop()
        self.assertFalse(self.lab.jobs)
        self.start('a', 'fdd-2', 200, None)
        self.player.tick()
        self.player.switch('VIRTUAL')
        self.assertFalse(self.lab.jobs)
        self.player.switch('REAL')
        sent = list(self.link.sent)
        self.step()
        self.assertEqual(self.link.sent, sent)

    def test_session_lease_and_failed_stop_never_restart(self):
        self.start('a', 'fdd-1', 220, None)
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
        self.start('a', 'fdd-1', 220, None)
        self.player.tick()
        self.now += 4
        self.player.tick()
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'stopped')
        self.assertEqual(self.player.owner, 'orchestra')

    def test_wrong_session_cannot_start_stop_update_or_take_ownership(self):
        for operation in (lambda: self.start('b','fdd-1',220,None),
                          lambda: self.lab.stop_device('b','fdd-1'),
                          lambda: self.lab.enter('b')):
            with self.assertRaises(ValueError): operation()
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.lab.session, 'a')

    def test_offline_power_off_unhomed_disabled_and_muted_block_start(self):
        self.link.controller_status['atx'] = 'OFF'
        with self.assertRaisesRegex(OutputError, 'ATX OFF'): self.start('a','fdd-1',220,None)
        self.link.controller_status['atx'] = 'ON'
        self.app.registry.by_id['fdd-8']['realEnabled'] = False
        with self.assertRaises(ValueError): self.start('a','fdd-8',220,None)
        self.app.router.muted.add('fdd-1')
        with self.assertRaisesRegex(ValueError, 'Mute'): self.start('a','fdd-1',220,None)
        self.app.router.muted.clear()
        self.app.real.link = None
        with self.assertRaisesRegex(OutputError, 'Brak połączenia'): self.start('a','fdd-1',220,None)
        self.assertFalse(self.lab.jobs)

    def test_invalid_numbers_ranges_and_modulations_are_rejected_before_output(self):
        for hz, duration, mod in [(True,1,None),(float('nan'),1,None),(220,0,None),
                                  (220,3601,None),(220,float('inf'),None),(25,None,None),
                                  (400,None,dict(mode='sine',depth=20)),
                                  (220,None,dict(mode='sine',period=.01)),
                                  (220,None,dict(mode='noise'))]:
            with self.assertRaises(ValueError): self.start('a','fdd-1',hz,duration,mod)
        self.assertEqual(self.link.sent, [])
        self.assertFalse(self.lab.jobs)

    def test_low_fdd_frequencies_reach_real_output_after_homing(self):
        for ident, lane in [('fdd-1', 1), ('fdd-8', 8)]:
            for hz in (80, 81, 100):
                with self.subTest(ident=ident, hz=hz):
                    self.start('a', ident, hz, None)
                    self.player.tick()
                    self.assertIn(f'FDD {lane} HOME', self.link.sent)
                    self.assertIn(f'FDD {lane} PLAY {hz:.2f}', self.link.sent)
                    self.lab.stop_device('a', ident)

    def test_low_fdd_frequencies_reach_virtual_output_unchanged(self):
        self.player.switch('VIRTUAL')
        packets = []
        def emit(packet):
            packets.append(packet)
            if packet['type'] == 'audio_cancel':
                self.app.virtual.acknowledge('a', packet['token'])
        self.app.virtual.emit = emit
        self.app.virtual.owner = 'a'
        for hz in (80, 81, 100):
            self.start('a', 'fdd-1', hz, None)
            self.player.tick()
            tones = [c for packet in packets if packet['type'] == 'audio'
                     for c in packet['commands'] if c['kind'] == 'tone']
            self.assertEqual(tones[-1]['hz'], hz)
            self.lab.stop_device('a', 'fdd-1')
        for hz in (0, 25, 40, 50, 75, 79.99):
            with self.assertRaises(ValueError):
                self.start('a', 'fdd-1', hz, None)

    def test_modulation_stays_in_profile_and_no_late_catchup_burst(self):
        self.start('a','fdd-1',220,None,dict(mode='sine',depth=10,period=4))
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
                self.start('a','DVD_STEPPER_1',230,None,dict(mode='triangle',depth=50))

    def test_hdd_remains_one_shot_and_rate_limited(self):
        for duration, mod in [(None,None),(1,dict(mode='sine'))]:
            with self.assertRaisesRegex(ValueError,'HDD'): self.start('a','hdd_vcm-1',200,duration,mod)
        self.start('a','hdd_vcm-1',200,1)
        self.player.tick()
        self.step(.01)
        self.assertEqual(self.link.sent.count('HDD 1 HIT'), 1)
        with self.assertRaises(ValueError): self.start('a','hdd_vcm-1',200,1)

    def test_failed_write_clears_jobs_and_marks_unknown(self):
        self.start('a','fdd-1',220,None)
        self.lab.test('a','fdd-1',300,None,update=True)
        self.link.fail_write = True
        self.player.tick()
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.player.state, 'paused')
        self.assertTrue(self.app.real.unknown)

    def test_link_loss_during_static_tone_cancels_without_auto_resume(self):
        self.start('a','fdd-1',220,None)
        self.player.tick()
        self.app.real.lost('disconnected')
        self.step()
        self.assertFalse(self.lab.jobs)
        replacement = Link()
        self.app.real.attach(replacement)
        self.step()
        self.assertFalse(any(' PLAY ' in line for line in replacement.sent))

    def test_service_owner_cancels_tests(self):
        self.start('a','fdd-1',220,None)
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
        self.start('a','fdd-1',220,None)
        self.player.tick()
        epoch = self.player.epoch
        self.start('a','fdd-2',300,None)
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
        self.start('a','fdd-1',220,None)
        self.player.tick()
        self.app.service.run('power_off')
        self.assertFalse(self.lab.jobs)
        self.assertEqual(self.link.controller_status['atx'], 'OFF')
        self.step()
        self.assertNotEqual(self.player.state, 'playing')

    def test_catalog_exposes_laboratory_ranges_without_changing_arrangement(self):
        devices = {d['id']:d for d in self.app.registry.catalog()}
        self.assertEqual(devices['fdd-1']['labBands'], [[80,410]])
        self.assertEqual(devices['DVD_STEPPER_1']['bands'], [])
        self.assertGreater(devices['DVD_STEPPER_1']['labBands'][0][1], 600)

    def test_start_always_homes_only_target_and_waits_for_fresh_track0(self):
        self.lab.test('a','fdd-1',220,5)
        self.assertEqual(self.link.sent,['FDD 1 STOP','FDD 1 HOME'])
        self.assertTrue(self.lab.snapshot()['active']['fdd-1']['homing'])
        self.player.tick()  # Cached homed=1 must not start playback.
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
        self.link.device_status['FDD:1'].update(homed='0',homing='1',track0='0')
        self.player.tick()
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
        self.now+=2;self.lab.touch('a')
        self.link.device_status['FDD:1'].update(homed='1',homing='0',track0='1')
        self.player.tick();self.player.tick()
        self.assertEqual(self.link.sent[-1],'FDD 1 PLAY 220.00')
        self.assertEqual(self.lab.jobs['fdd-1']['end'],107)
        self.assertFalse(self.lab.snapshot()['active']['fdd-1']['homing'])

    def test_homed_flag_without_track0_does_not_start(self):
        self.link.device_status['FDD:1']['track0']='0'
        self.lab.test('a','fdd-1',220,5);self.player.tick();self.player.tick()
        self.assertTrue(self.lab.jobs['fdd-1']['homing'])
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))

    def test_extended_target_uses_diag_and_does_not_rehome_on_update(self):
        self.lab.test('a','fdd-8',220,None);self.player.tick()
        self.assertEqual(self.link.status_generation,0)
        self.assertIn('DIAG FDD END',self.link.lines)
        self.player.tick()
        self.assertEqual(self.link.sent,['FDD 8 STOP','FDD 8 HOME','FDD 8 PLAY 220.00'])
        self.lab.test('a','fdd-8',300,None,update=True);self.step()
        self.assertEqual(self.link.sent.count('FDD 8 HOME'),1)
        self.assertEqual(self.link.sent[-1],'FDD 8 PLAY 300.00')

    def test_stop_during_homing_never_starts_delayed_tone(self):
        self.lab.test('a','fdd-1',220,None);self.player.tick()
        self.lab.stop_device('a','fdd-1')
        self.step();self.step()
        self.assertFalse(self.lab.jobs)
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))

    def test_homing_timeout_stops_instead_of_starting(self):
        self.link.device_status['FDD:1'].update(homed='0',homing='1',track0='0')
        self.lab.test('a','fdd-1',220,None);self.player.tick()
        self.step(10.1)
        self.assertFalse(self.lab.jobs)
        self.assertIn('homing TRACK0',self.player.error)
        self.assertIn('ALL STOP token',self.link.sent)
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))

    def test_home_failed_error_aborts_without_play(self):
        self.lab.test('a','fdd-1',220,None)
        self.link.lines.append('ERR HOME_FAILED FDD=1');self.player.tick()
        self.assertFalse(self.lab.jobs)
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))

    def test_homing_second_drive_keeps_first_running(self):
        self.start('a','fdd-1',220,None);self.link.sent.clear()
        self.link.device_status['FDD:8'].update(homed='0',homing='1',track0='0')
        self.lab.test('a','fdd-8',220,None);self.player.tick();self.step(.3)
        self.assertEqual(self.link.sent,['FDD 8 STOP','FDD 8 HOME'])
        self.assertFalse(self.lab.jobs['fdd-1']['homing'])
        self.assertTrue(self.lab.jobs['fdd-8']['homing'])
        self.lab.stop_device('a','fdd-8');self.step()
        self.assertIn('fdd-1',self.lab.jobs)
        self.assertFalse(any(s.startswith('FDD 1 STOP') or s.startswith('ALL STOP') for s in self.link.sent))

    def test_offline_or_power_off_cannot_issue_home(self):
        self.link.controller_status['atx']='OFF'
        with self.assertRaises(OutputError):self.lab.test('a','fdd-1',220,None)
        self.assertEqual(self.link.sent,[])
        self.app.real.link=None
        with self.assertRaises(OutputError):self.lab.test('a','fdd-1',220,None)
        self.assertEqual(self.link.sent,[])

    def test_simultaneous_base_and_extended_home_require_both_complete_queries(self):
        self.lab.test('a','fdd-1',220,None)
        self.lab.test('a','fdd-8',220,None)
        self.player.tick()
        self.link.lines.remove('DIAG FDD END')
        self.player.tick()
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
        self.link.lines.append('DIAG FDD END');self.player.tick()
        self.assertIn('FDD 1 PLAY 220.00',self.link.sent)
        self.assertIn('FDD 8 PLAY 220.00',self.link.sent)

    def test_restart_cannot_accept_response_to_previous_home_query(self):
        self.lab.test('a','fdd-1',220,None);self.player.tick()
        self.lab.test('a','fdd-1',300,None);self.player.tick()
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
        self.player.tick()
        self.assertEqual(self.link.sent[-1],'FDD 1 PLAY 300.00')

    def test_homing_failure_reports_only_fault_not_whole_status_dump(self):
        self.lab.test('a','fdd-1',220,None)
        self.link.lines.extend(['STATUS BEGIN','STATUS FDD 1 homing=0','ERR HOME_FAILED FDD=1','STATUS END'])
        self.player.tick()
        self.assertIn('HOME_FAILED FDD=1',self.player.error)
        self.assertNotIn('STATUS BEGIN',self.player.error)
        self.assertNotIn('STATUS FDD',self.player.error)
        self.assertFalse(self.lab.jobs)
