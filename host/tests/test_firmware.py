import subprocess
import sys
import unittest
import tempfile
import io
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware import run_firmware, PROJECT


class FirmwareTest(unittest.TestCase):
    def test_streams_carriage_return_progress_and_rejects_failed_process(self):
        class Process:
            def __init__(self,code):
                self.stdout=io.StringIO('Writing at 0x1000 (37 %)\rWriting at 0x2000 (100 %)\n')
                self.code=code
            def wait(self): return self.code
            def kill(self): pass
        lines=[]
        with patch('firmware.subprocess.Popen',return_value=Process(0)):
            run_firmware('pio','/dev/fake',target='esp32',on_line=lines.append)
        self.assertEqual(len(lines),2)
        self.assertIn('37 %',lines[0])
        with patch('firmware.subprocess.Popen',return_value=Process(1)):
            with self.assertRaisesRegex(RuntimeError,'Writing at'):
                run_firmware('pio','/dev/fake',target='esp32',on_line=lines.append)


    def test_fixed_uno_project_and_explicit_port(self):
        with patch('firmware.subprocess.run', return_value=Mock(returncode=0, stdout='ok')) as run:
            run_firmware('/tool/pio', '/dev/uno')
        self.assertEqual(run.call_args.args[0], ['/tool/pio', 'run', '-d', str(PROJECT),
                         '-e', 'uno', '--target', 'upload', '--upload-port', '/dev/uno'])




    def test_timeout_reported(self):
        with patch('firmware.subprocess.run', side_effect=subprocess.TimeoutExpired('pio', 180)):
            with self.assertRaisesRegex(RuntimeError, '180 s'):
                run_firmware('pio')
