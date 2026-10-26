"""Strategy separation and legacy device imports remain compatible."""
import copy
import subprocess
import sys
import unittest
from pathlib import Path
import test_runtime as helpers
from playback.device_models import DeviceInstance
from playback.virtual import VirtualDeviceInstance
from runtime.planning_pipeline import ArrangementStrategy


class PipelineContractTests(unittest.TestCase):
    def test_allocation_strategy_does_not_mutate_requested_config(self):
        registry=helpers.DeviceRegistry()
        for preset in ('balanced','universal','fdd_expressive_solo','fdd_legato','adaptive_legato'):
            registry.document['parameters']['arrangementPreset']=preset
            config=registry.configuration();before=copy.deepcopy(config.as_dict())
            strategy=ArrangementStrategy.for_preset(preset)
            allocated=strategy.allocation_config(config)
            self.assertEqual(config.as_dict(),before)
            self.assertEqual(config.policy['arrangementPreset'],preset)
            self.assertEqual(allocated.policy['arrangementPreset'],strategy.allocation)
            self.assertIsNot(allocated.policy,config.policy)

    def test_legacy_device_class_is_the_neutral_model(self):
        self.assertIs(DeviceInstance,VirtualDeviceInstance)
        self.assertIsInstance(VirtualDeviceInstance.parse({'id':'fdd','type':'FDD'}),DeviceInstance)

    def test_loading_device_model_does_not_load_preview_renderer(self):
        host=Path(__file__).resolve().parents[1]
        source="import sys;sys.path.insert(0,sys.argv[1]);import playback.device_models;assert 'playback.virtual' not in sys.modules"
        subprocess.run([sys.executable,'-c',source,str(host)],check=True,capture_output=True)
