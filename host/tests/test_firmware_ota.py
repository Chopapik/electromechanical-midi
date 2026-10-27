import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ecdsa import SigningKey,NIST256p
from firmware_ota import prepare_build,read_key


class OtaBuildTests(unittest.TestCase):
    def test_private_key_persists_and_only_public_key_enters_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'settings/key';project=root/'firmware';project.mkdir()
            with patch.dict(os.environ,{'ORCHESTRA_OTA_KEY':str(path)}):
                key=prepare_build(project)
                self.assertEqual(key,read_key());self.assertEqual(len(key),32)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                header=project/'.generated/ble_ota_key.h';before=header.read_text()
                values=bytes(int(n) for n in before.split('{')[1].split('}')[0].split(','))
                self.assertEqual(values,b'\x04'+SigningKey.from_string(key,curve=NIST256p).verifying_key.to_string())
                self.assertNotIn('installationKey[32]',before)
                self.assertEqual(prepare_build(project),key)
                self.assertEqual(header.read_text(),before)

    def test_invalid_private_key_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'key';path.write_bytes(b'bad')
            with patch.dict(os.environ,{'ORCHESTRA_OTA_KEY':str(path)}):
                with self.assertRaises(RuntimeError):prepare_build(root)
            self.assertEqual(path.read_bytes(),b'bad')
