"""Small static boundary checks do not import or execute application modules."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from check_architecture import check_source,check,main


class ArchitectureTests(unittest.TestCase):
    def codes(self,source,path='host/runtime/example.py'):
        return [finding.code for finding in check_source(source,path)]

    def test_undefined_global_in_nested_function_is_rejected(self):
        findings=check_source('def load():\n    return MAX_UPLOAD_BYTES\n','host/web/library.py')
        self.assertEqual([finding.code for finding in findings],['undefined-global'])
        self.assertIn('MAX_UPLOAD_BYTES',findings[0].detail)

    def test_module_globals_imports_builtins_and_closures_are_supported(self):
        source=('from pathlib import Path\nLIMIT=5\n'
                'def outer():\n    local=2\n'
                '    def inner():\n        return len(str(local+LIMIT))+len(Path(__file__).name)\n'
                '    return inner\n')
        self.assertEqual(self.codes(source),[])

    def test_forward_definitions_and_type_checking_imports_are_supported(self):
        source=('from __future__ import annotations\nfrom typing import TYPE_CHECKING\n'
                'if TYPE_CHECKING:\n    from .device_models import DeviceInstance\n'
                'def create(device: DeviceInstance):\n    return later(device)\n'
                'def later(device):\n    return device\n')
        self.assertEqual(self.codes(source,'host/playback/example.py'),[])

    def test_runtime_cannot_import_http_controller_even_inside_function(self):
        source='def perform():\n    from host.web.server import create_app\n    return create_app\n'
        self.assertEqual(self.codes(source),['import-boundary'])

    def test_planning_cannot_import_live_transport_or_runtime(self):
        for source in ('import ble_link\n','from runtime.player import Player\n',
                       'from ..runtime import player\n','import host.web.server\n'):
            with self.subTest(source=source):
                self.assertTrue(all(code=='import-boundary' for code in
                                    self.codes(source,'host/playback/example.py')))
                self.assertTrue(self.codes(source,'host/playback/example.py'))

    def test_exact_existing_fingerprint_import_is_an_explicit_exception(self):
        source='from runtime.compiler import compile_plan\n'
        self.assertEqual(self.codes(source,'host/playback/universal_recovery.py'),[])
        self.assertEqual(self.codes('import runtime.compiler\n','host/playback/universal_recovery.py'),
                         ['import-boundary'])
        self.assertEqual(self.codes(source,'host/playback/example.py'),['import-boundary'])

    def test_neutral_models_cannot_import_preview_in_either_relative_form(self):
        for source in ('from .virtual import VirtualOrchestra\n','from . import virtual\n',
                       'import playback.virtual\n'):
            with self.subTest(source=source):
                self.assertIn('import-boundary',self.codes(source,'host/playback/device_models.py'))
        self.assertEqual(self.codes('from .device_models import DeviceInstance\n',
                                    'host/playback/virtual.py'),[])

    def test_library_and_contracts_do_not_depend_on_http_or_application(self):
        for path in ('host/web/library.py','host/web/contracts.py'):
            for source in ('from fastapi import HTTPException\n','import runtime.application\n'):
                with self.subTest(path=path,source=source):
                    self.assertEqual(self.codes(source,path),['import-boundary'])

    def test_wildcard_and_invalid_syntax_are_explicit_failures(self):
        self.assertIn('wildcard-import',self.codes('from math import *\n'))
        self.assertEqual(self.codes('def invalid(:\n'),['syntax'])

    def test_cli_reports_findings_and_does_not_accept_empty_coverage(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            root=Path(directory)
            self.assertEqual(main(['--root',str(root)]),1)
            path=root/'host/runtime/example.py';path.parent.mkdir(parents=True)
            path.write_text('LIMIT=5\n')
            self.assertEqual(main(['--root',str(root)]),0)
            path.write_text('def example():\n    return nonexistent\n')
            self.assertEqual(main(['--root',str(root)]),1)

    def test_current_application_has_no_unresolved_globals_or_new_boundary_violations(self):
        findings,count=check(ROOT)
        self.assertGreater(count,40)
        self.assertEqual(findings,[],'\n'.join(map(str,findings)))
