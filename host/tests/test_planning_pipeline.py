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
from playback.arrangement_strategy import FddGrouping, HardwareAllocationStrategy
from arrangement_presets import PRESET_IDS


class PipelineContractTests(unittest.TestCase):
    def test_allocation_strategy_does_not_mutate_requested_config(self):
        registry=helpers.DeviceRegistry()
        for preset in PRESET_IDS:
            registry.document['parameters']['arrangementPreset']=preset
            config=registry.configuration();before=copy.deepcopy(config.as_dict())
            strategy=ArrangementStrategy.for_preset(preset)
            allocated=strategy.allocation_config(config)
            self.assertEqual(config.as_dict(),before)
            self.assertEqual(config.policy['arrangementPreset'],preset)
            self.assertEqual(allocated.policy['arrangementPreset'],strategy.allocation)
            self.assertIsNot(allocated.policy,config.policy)

    def test_hardware_strategy_preserves_requested_configuration(self):
        registry = helpers.DeviceRegistry()
        for preset in PRESET_IDS:
            with self.subTest(preset=preset):
                registry.document['parameters']['arrangementPreset'] = preset
                config = registry.configuration()
                before = copy.deepcopy(config.as_dict())
                strategy = HardwareAllocationStrategy.for_config(config, FddGrouping())
                self.assertEqual(config.as_dict(), before)
                self.assertEqual(strategy.requested_config.policy['arrangementPreset'], preset)

    def test_legacy_grouping_retains_bool_and_integer_distinction(self):
        self.assertEqual(FddGrouping.from_legacy(True).size, 4)
        self.assertEqual(FddGrouping.from_legacy(2).size, 2)
        self.assertFalse(FddGrouping.from_legacy(False).enabled)

    def test_legacy_device_class_is_the_neutral_model(self):
        self.assertIs(DeviceInstance,VirtualDeviceInstance)
        self.assertIsInstance(VirtualDeviceInstance.parse({'id':'fdd','type':'FDD'}),DeviceInstance)

    def test_loading_device_model_does_not_load_preview_renderer(self):
        host=Path(__file__).resolve().parents[1]
        source="import sys;sys.path.insert(0,sys.argv[1]);import playback.device_models;assert 'playback.virtual' not in sys.modules"
        subprocess.run([sys.executable,'-c',source,str(host)],check=True,capture_output=True)
