"""Autodetection uses USB identity, not generic macOS serial ports."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from floppy_link import resolve_port, SerialLinkError


def port(device, vid=None, description='n/a', manufacturer=None):
    return SimpleNamespace(device=device, vid=vid, pid=0x43 if vid else None,
                           description=description, product=None, manufacturer=manufacturer)


class PortDetectionTest(unittest.TestCase):
    def test_uno_is_selected_without_prompt_among_macos_system_ports(self):
        ports = [port('/dev/cu.debug-console'), port('/dev/cu.Bluetooth-Incoming-Port'),
                 port('/dev/cu.usbmodem14101', 0x2341, 'IOUSBHostDevice', 'Arduino (www.arduino.cc)')]
        with patch('floppy_link.list_ports.comports', return_value=ports):
            self.assertEqual(resolve_port(interactive=False).device, '/dev/cu.usbmodem14101')

    def test_two_unos_remain_ambiguous_instead_of_picking_arbitrarily(self):
        with patch('floppy_link.list_ports.comports', return_value=[
                port('/dev/cu.usbmodem1', 0x2341), port('/dev/cu.usbmodem2', 0x2341)]):
            with self.assertRaises(SerialLinkError):
                resolve_port(interactive=False)

    def test_explicit_port_still_overrides_autodetection(self):
        with patch('floppy_link.list_ports.comports', return_value=[port('/dev/cu.usbmodem1', 0x2341)]):
            self.assertEqual(resolve_port('/dev/custom', interactive=False).device, '/dev/custom')
