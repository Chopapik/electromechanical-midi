"""The refactoring guard runs offline and catches exact command regressions."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from scripts import refactoring_baseline as baseline


class RefactoringBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'baseline.jsonl.gz'
        data = baseline.fixture_bytes('phrases')
        self.manifest = [{'id': 'phrases', 'fixture': 'phrases',
                          'sha256': hashlib.sha256(data).hexdigest()}]

    def capture(self):
        return baseline.run(self.path, manifest=self.manifest,
                            presets=['balanced', 'adaptive_legato'], progress=lambda _: None)

    def test_capture_verify_and_diagnostics_are_excluded(self):
        self.assertEqual(self.capture(), 6)
        with gzip.open(self.path, 'rt') as stream:
            rows = [json.loads(line) for line in stream]
        self.assertEqual(len(rows[0]['contract']['catalog']), 13)
        self.assertEqual(rows[0]['configuration']['values']['speakerPreferences'], {})
        self.assertEqual(len(rows[0]['configuration']['fingerprint']), 64)
        self.assertIn('STRICT_TRACKS', rows[3]['case'])
        self.assertIn('DISABLED_PARTNERS', rows[5]['case'])
        self.assertIn('reason', rows[1]['execution']['events'][0])
        self.assertIn('executionArticulation', rows[1]['execution'])
        rows[1]['diagnostics']['planningSeconds'] = -999
        with gzip.open(self.path, 'wt') as stream:
            for row in rows:
                stream.write(json.dumps(row)+'\n')
        self.assertEqual(baseline.run(self.path, verify=True, progress=lambda _: None), 6)
        self.assertEqual(baseline.run(self.path, verify=True, only_presets=['adaptive_legato'],
                                     only_cases=['*/AUTO'], progress=lambda _: None), 1)
        with self.assertRaisesRegex(ValueError, 'No cases matched'):
            baseline.run(self.path, verify=True, only_cases=['missing'], progress=lambda _: None)
        rows[1]['execution']['timeline']['commands'][0]['hz'] += .0000000000001
        with gzip.open(self.path, 'wt') as stream:
            for row in rows:
                stream.write(json.dumps(row)+'\n')
        with self.assertRaisesRegex(ValueError, r'timeline.commands\[0\].hz'):
            baseline.run(self.path, verify=True, progress=lambda _: None)

    def test_sha_and_missing_files_fail_without_capture(self):
        self.manifest[0]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Source SHA mismatch'):
            self.capture()
        self.assertFalse(self.path.exists())
        manifest = [{'id': 'missing', 'path': str(self.path.parent/'missing.mid'), 'sha256': '0'*64}]
        with self.assertRaises(FileNotFoundError):
            baseline.run(self.path, manifest=manifest, progress=lambda _: None)
        self.assertFalse(self.path.exists())

    def test_capture_never_overwrites_and_float_comparison_is_exact(self):
        self.path.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual(self.path.read_bytes(), b'keep me')
        self.assertIsNotNone(baseline.first_difference(1., math.nextafter(1., 2.)))
        self.assertIsNotNone(baseline.first_difference(-0., 0.))
        self.assertIn('[1]', baseline.first_difference([1, 2], [1]))
        self.assertIn('[0]', baseline.first_difference([1, 2], [3]))

    def test_prefix_is_deterministic_and_closes_long_notes(self):
        data = baseline.fixture_bytes('phrases')
        derived = baseline.prefix_bytes(data, 1.)
        self.assertEqual(derived, baseline.prefix_bytes(data, 1.))
        path = Path(self.tmp.name)/'short.mid'
        path.write_bytes(derived)
        source = baseline.MidiSource(path)
        notes = [note for track in source.tracks for note in source.notes(track.index)]
        self.assertTrue(notes)
        self.assertLessEqual(max(note.end for note in notes), 1.)
