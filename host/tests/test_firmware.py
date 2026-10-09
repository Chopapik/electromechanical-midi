import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware import run_firmware, PROJECT


class FirmwareTest(unittest.TestCase):


    def test_fixed_uno_project_and_explicit_port(self):
        with patch('firmware.subprocess.run', return_value=Mock(returncode=0, stdout='ok')) as run:
            run_firmware('/tool/pio', '/dev/uno')
        self.assertEqual(run.call_args.args[0], ['/tool/pio', 'run', '-d', str(PROJECT),
                         '-e', 'uno', '--target', 'upload', '--upload-port', '/dev/uno'])




    def test_timeout_reported(self):
        with patch('firmware.subprocess.run', side_effect=subprocess.TimeoutExpired('pio', 180)):
            with self.assertRaisesRegex(RuntimeError, '180 s'):
                run_firmware('pio')
