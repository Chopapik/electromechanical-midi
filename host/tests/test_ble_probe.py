"""The quiet probe has no arbitrary command or actuator execution path."""
import unittest
from unittest.mock import Mock
from scripts.probe_ble_ping import Gateway, validate_command, probe


class QuietProbeTests(unittest.TestCase):
    def test_gateway_releases_socket_when_reader_cleanup_fails(self):
        gateway = Gateway.__new__(Gateway)
        gateway.reader = Mock()
        gateway.socket = Mock()
        gateway.reader.close.side_effect = OSError('reader closed')
        with self.assertRaises(OSError): gateway.close()
        gateway.socket.close.assert_called_once()

    def test_only_ping_and_correlated_stop_are_permitted(self):
        for command in ('PING','ALL STOP 0','ALL STOP 4294967295'):
            validate_command(command)
        for command in ('POWER ON','POWER OFF','POWER STATUS','PLAY 220','FDD 1 PLAY 50',
                        'FDD 1 HOME','HDD 1 HIT','VHS AMP 50','PING\nFDD 1 PLAY 50',
                        'ALL STOP','ALL STOP x','ALL STOP 12345678901','ALL STOP ١'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_command(command)

    def gateway(self, fail=None):
        class Fake:
            def __init__(self):self.commands=[];self.now=10.;self.pings=0
            def exchange(self, command, expected):
                validate_command(command);self.commands.append(command)
                if command=='PING':
                    self.pings+=1
                    if fail==self.pings:raise OSError('BLE failed')
                if fail=='stop':raise OSError('No STOP ACK')
                self.now+=.010
            def sleep(self, seconds):self.now+=seconds
        return Fake()

    def test_no_power_or_motion_and_stop_ack_before_and_after(self):
        gateway = self.gateway()
        result = probe(gateway, 3, .1, clock=lambda:gateway.now, sleep=gateway.sleep)
        self.assertTrue(result['initialStopConfirmed'] and result['finalStopConfirmed'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['samplesMs'], [10,10,10])
        self.assertEqual(gateway.commands[1:-1], ['PING']*3)
        self.assertNotEqual(gateway.commands[0],gateway.commands[-1])

    def test_missing_initial_stop_ack_aborts_without_ping(self):
        gateway = self.gateway(fail='stop')
        result = probe(gateway, 3, .1, clock=lambda:gateway.now, sleep=gateway.sleep)
        self.assertFalse(result['initialStopConfirmed'])
        self.assertEqual(len(gateway.commands),1)
        self.assertTrue(result['error'])

    def test_first_error_aborts_without_retries_or_false_final_stop(self):
        gateway = self.gateway(fail=2)
        result = probe(gateway, 10, .1, clock=lambda:gateway.now, sleep=gateway.sleep)
        self.assertTrue(result['initialStopConfirmed'])
        self.assertFalse(result['finalStopConfirmed'])
        self.assertEqual(gateway.pings,2)
        self.assertEqual(result['samplesMs'],[10])
        self.assertTrue(result['error'])
