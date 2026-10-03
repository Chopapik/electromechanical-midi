"""Domyslny przeplyw: MIDI -> Auto Arranger -> plan -> Virtual Orchestra.

Sprawdza Definition of Done v1: uzytkownik wrzuca MIDI, NIE importuje
zadnego JSON-a, a orkiestra sama przygotowuje i wykonuje plan.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback import allocator  # noqa: E402
from playback.engine import PlaybackEngine, PlaybackState  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402
from test_allocator import write_drums  # noqa: E402
from test_web import write_midi  # noqa: E402


class TestDefaultFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Melodia + akompaniament + perkusja, bez zadnego JSON-a.
        self.path = write_midi(self.tmp / 'Song.mid', [
            (0.0, 0.4, 72), (0.5, 0.9, 74), (1.0, 1.4, 76), (1.5, 1.9, 77),
            (2.0, 2.4, 79), (2.5, 2.9, 81), (3.0, 3.4, 83), (3.5, 3.9, 84),
        ], name='Lead Vocal')
        self.drums = write_drums(self.tmp / 'Drums.mid', [
            (0.0, 0.05, 36), (0.5, 0.55, 38), (1.0, 1.05, 42), (1.5, 1.55, 36),
        ])

    def tearDown(self):
        self._tmp.cleanup()

    def engine(self):
        engine = PlaybackEngine(auto_arrange=True, wait_ready=False)
        engine.start()

        return engine

    def test_load_without_json_builds_a_plan(self):
        engine = self.engine()

        try:
            engine.load_file(self.path)
            view = engine.arrangement_view()
            document = view['arrangement']

            self.assertIsNotNone(document, 'plan musi powstac bez importu JSON-a')
            self.assertEqual(document['origin'], 'auto')
            self.assertEqual(document['rules'], [], 'auto-aranzacja nie wymaga regul')
            self.assertEqual(sorted(d['type'] for d in document['devices']),
                             ['DVD_SLED'] * 4 + ['FDD'] * 3 + ['HDD_VCM'] * 3 + ['VHS'])
            self.assertGreater(len(view['notes']), 0)
            self.assertIsNotNone(view['report'])
        finally:
            engine.shutdown()

    def test_snapshot_exposes_origin_and_totals(self):
        engine = self.engine()

        try:
            engine.load_file(self.path)
            snapshot = engine.snapshot()

            self.assertTrue(snapshot['arrangementActive'])
            self.assertEqual(snapshot['arrangementOrigin'], 'auto')
            self.assertEqual(snapshot['arrangementTotals']['requested'], 8)
            self.assertIsNotNone(snapshot['arrangementHardware'])
        finally:
            engine.shutdown()

    def test_playback_runs_on_the_generated_plan(self):
        engine = self.engine()

        try:
            engine.load_file(self.path)
            engine.play()

            self.assertEqual(engine.state, PlaybackState.PLAYING)
            # Renderer nie podejmuje wlasnych decyzji: zaakceptowane zdarzenia
            # symulacji musza zgadzac sie co do jednego z planem.
            played = engine._plan.report()['totals']['played']
            accepted = sum(report['accepted'] for report in engine._virtual.report.values())

            self.assertEqual(accepted, played)
            self.assertEqual(sum(report['dropped'] for report in engine._virtual.report.values()), 0)
        finally:
            engine.shutdown()

    def test_manual_json_is_only_an_override(self):
        engine = self.engine()

        try:
            engine.load_file(self.path)
            auto = engine.arrangement_view()['report']['totals']

            document = engine.arrangement_view()['arrangement']
            document['devices'] = document['devices'][:1]

            engine.set_arrangement(document)
            view = engine.arrangement_view()

            self.assertEqual(view['arrangement']['origin'], 'manual')
            self.assertEqual(len(view['arrangement']['devices']), 1)
            # Mniej urzadzen = gorszy plan, ale nadal bez bledu.
            self.assertGreaterEqual(view['report']['totals']['dropRate'], auto['dropRate'])
        finally:
            engine.shutdown()

    def test_saved_arrangement_beside_midi_is_loaded_automatically(self):
        engine = self.engine()

        try:
            engine.load_file(self.path)
            document = engine.arrangement_view()['arrangement']
            document['devices'] = document['devices'][:2]
            engine.set_arrangement(document)
            saved = Path(self.path).with_suffix('.orchestra.json')
            saved.write_text(__import__('json').dumps(document), encoding='utf-8')

            engine.load_file(self.path)

            self.assertTrue(engine.has_arrangement_override())
            self.assertEqual(len(engine.arrangement_view()['arrangement']['devices']), 2)
        finally:
            engine.shutdown()


class TestAllocatorBeatsStaticRouting(unittest.TestCase):
    """Regresja: pula glosow musi wygrywac ze statycznym routingiem."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_more_notes_survive_than_with_pinned_tracks(self):
        from playback.arrangement import Arrangement, midi_identity
        from playback.virtual import VirtualOrchestra

        notes = []

        for index in range(200):
            start = index * 0.05

            for pitch in (48, 55, 60, 64, 67):
                notes.append((start, start + 0.2, pitch))

        path = write_midi(self.tmp / 'Dense.mid', notes, name='Dense')
        source = MidiSource(path)
        orchestra = default_orchestra()

        # Statyczny routing: kazdy "track" (tu jeden) na jedno urzadzenie.
        static = Arrangement.parse({
            'schemaVersion': 1, 'midi': midi_identity(source), 'name': 'static',
            'devices': orchestra.devices,
            'rules': [{'id': 'all', 'source': {'track': 1},
                       'destination': {'deviceId': 'fdd-1'}, 'transform': {}}],
        }, source)
        routes, _ = static.route(source)
        legacy = VirtualOrchestra(static.devices, 'static')
        legacy.simulate(source, routes)
        static_played = sum(report['played'] for report in legacy.report.values())

        plan = allocator.allocate(source, orchestra)
        auto_played = plan.report()['totals']['played']

        self.assertGreater(auto_played, static_played,
                           'pula glosow musi zagrac wiecej niz przypiety track')


if __name__ == '__main__':
    unittest.main()
