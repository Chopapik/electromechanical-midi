"""Autodetection uses USB identity, not generic macOS serial ports."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from floppy_link import esp32_upload_ports, resolve_port, scan_ports, SerialLinkError


def port(device, vid=None, description='n/a', manufacturer=None):
    return SimpleNamespace(device=device, vid=vid, pid=0x43 if vid else None,
                           description=description, product=None, manufacturer=manufacturer)


class PortDetectionTest(unittest.TestCase):
    def test_forwarded_orbstack_serial_is_detected_without_fixed_port_name(self):
        with patch.dict('os.environ', {'ORCHESTRA_SERIAL_DIR': '/host-dev'}), \
             patch('floppy_link.list_ports.comports', return_value=[]), \
             patch('floppy_link.Path.glob', side_effect=[[
                 Path('/host-dev/cu.Bluetooth-Incoming-Port'),
                 Path('/host-dev/cu.usbmodem987')], [], []]), \
             patch('floppy_link.Path.is_char_device', return_value=True):
            ports = scan_ports()
            self.assertEqual(ports[0].device, '/host-dev/cu.usbmodem987')
            self.assertGreater(ports[0].score, ports[1].score)

    def test_forwarded_regular_files_are_not_serial_devices(self):
        with patch.dict('os.environ', {'ORCHESTRA_SERIAL_DIR': '/host-dev'}), \
             patch('floppy_link.list_ports.comports', return_value=[]), \
             patch('floppy_link.Path.glob', return_value=[Path('/host-dev/cu.fake')]), \
             patch('floppy_link.Path.is_char_device', return_value=False):
            self.assertEqual(scan_ports(), [])

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

    def test_forwarded_cp2102_without_vid_is_eligible_for_esp32_upload(self):
        with patch.dict('os.environ', {'ORCHESTRA_SERIAL_DIR': '/host-dev'}), \
             patch('floppy_link.list_ports.comports', return_value=[]), \
             patch('floppy_link.Path.glob', side_effect=[[
                 Path('/host-dev/cu.Bluetooth-Incoming-Port'),
                 Path('/host-dev/cu.usbserial-0001')], [], []]), \
             patch('floppy_link.Path.is_char_device', return_value=True):
            ports = esp32_upload_ports()
            self.assertEqual([p.device for p in ports], ['/host-dev/cu.usbserial-0001'])

    def test_forwarded_uno_usbmodem_is_rejected_for_esp32_upload(self):
        with patch.dict('os.environ', {'ORCHESTRA_SERIAL_DIR': '/host-dev'}), \
             patch('floppy_link.list_ports.comports', return_value=[]), \
             patch('floppy_link.Path.glob', side_effect=[[
                 Path('/host-dev/cu.usbmodem987')], [], []]), \
             patch('floppy_link.Path.is_char_device', return_value=True):
            self.assertEqual(esp32_upload_ports(), [])

    def test_cp2102_vid_selects_esp32_upload_port(self):
        ports = [SimpleNamespace(device='/dev/cu.usbserial-1', vid=0x10C4, label='CP2102', score=60),
                 SimpleNamespace(device='/dev/cu.usbmodem1', vid=0x2341, label='Uno', score=100)]
        self.assertEqual([p.device for p in esp32_upload_ports(ports)], ['/dev/cu.usbserial-1'])
