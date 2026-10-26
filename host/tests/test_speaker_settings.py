"""Speaker preferences persistence and atomic failures, independently of registry."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.speaker_settings import SpeakerSettingsStore
from runtime.registry import DeviceRegistry


class SpeakerSettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'nested'/'speakers.json'
        self.saved={'vhs-1':{'volume':.8,'realAmplitude':22,'waveform':'pulse'},
                    'pc-speaker-fx':{'volume':1,'realAmplitude':50,'waveform':'pulse'}}

    def test_same_path_environment_and_json_format(self):
        with patch.dict(os.environ,{'ORCHESTRA_SPEAKER_SETTINGS':str(self.path)}):
            store=SpeakerSettingsStore()
            self.assertEqual(store.path,self.path)
            self.assertEqual(store.load(),{})
            store.save(self.saved)
            self.assertEqual(store.load(),self.saved)
            self.assertEqual(self.path.read_text(),json.dumps(self.saved,indent=2))
            registry=DeviceRegistry()
            self.assertEqual(registry.volume_path,self.path)
            self.assertEqual(registry.by_id['vhs-1']['volume'],.8)

    def test_replace_failure_keeps_previous_file_and_registry_value(self):
        store=SpeakerSettingsStore(self.path);store.save(self.saved)
        before=self.path.read_bytes();registry=DeviceRegistry(volume_path=self.path)
        with patch.object(Path,'replace',side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError,'replace failed'):
                registry.set_volume('vhs-1','REAL',50)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(registry.by_id['vhs-1']['realAmplitude'],22)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_serialization_failure_also_cleans_temporary_file(self):
        store=SpeakerSettingsStore(self.path);store.save(self.saved)
        before=self.path.read_bytes()
        with patch('runtime.speaker_settings.json.dump',side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError,'write failed'):store.save(self.saved)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])
