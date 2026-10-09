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
from playback.orchestra import default_orchestra  # noqa: E402
from test_allocator import write_drums  # noqa: E402
from midi_fixtures import write_midi  # noqa: E402




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
