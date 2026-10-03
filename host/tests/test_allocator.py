"""Auto Arranger: alokacja glosow, polityki overflow i determinizm.

Testy celowo uzywaja malych, syntetycznych plikow MIDI - kazdy sprawdza
JEDNA regule alokatora, a nie brzmienie konkretnego utworu.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback import allocator  # noqa: E402
from playback.allocator import ManualPin  # noqa: E402
from playback.orchestra import BALANCED, OrchestraConfig, default_orchestra  # noqa: E402
from playback.analysis import MidiAnalysis  # noqa: E402
from playback.performance import PerformancePlan  # noqa: E402
from test_web import TICKS_PER_SECOND, write_midi  # noqa: E402

import mido  # noqa: E402


def write_drums(path: Path, notes, name: str = 'Drums') -> Path:
    """Perkusja na kanale 10 (indeks 9) - tylko takie tracki sa HDD."""
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage('set_tempo', tempo=500_000, time=0))

    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('track_name', name=name, time=0))

    events = []

    for start, end, note in notes:
        events.append((round(start * TICKS_PER_SECOND), 0, note))
        events.append((round(end * TICKS_PER_SECOND), 1, note))

    previous = 0

    for tick, kind, note in sorted(events):
        track.append(mido.Message('note_on' if kind == 0 else 'note_off', channel=9,
                                  note=note, velocity=100 if kind == 0 else 0,
                                  time=tick - previous))
        previous = tick

    midi.save(path)

    return path


def write_tracks(path: Path, tracks, name: str = 'Song') -> Path:
    """Kilka trackow naraz: [(nazwa, kanal, [(start, end, note), ...]), ...]."""
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage('set_tempo', tempo=500_000, time=0))

    for track_name, channel, notes in tracks:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name=track_name, time=0))
        events = []

        for start, end, note in notes:
            events.append((round(start * TICKS_PER_SECOND), 0, note))
            events.append((round(end * TICKS_PER_SECOND), 1, note))

        previous = 0

        for tick, kind, note in sorted(events):
            track.append(mido.Message('note_on' if kind == 0 else 'note_off',
                                      channel=channel, note=note,
                                      velocity=100 if kind == 0 else 0,
                                      time=tick - previous))
            previous = tick

    midi.save(path)

    return path


def device(ident: str, kind: str, profile: str) -> dict:
    return {'id': ident, 'type': kind, 'name': ident, 'track': None, 'role': '',
            'volume': 0.6, 'pan': 0.0, 'mute': False, 'solo': False, 'transpose': 0,
            'gate': 1.0, 'profile': profile, 'mode': 'virtual', 'overrides': {}}


class AllocatorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def source(self, notes, name='Song') -> MidiSource:
        path = write_midi(self.tmp / f'{name}.mid', notes, name=name)

        return MidiSource(path)

    def orchestra(self, fdd=3, vhs=1, hdd=0, **policy) -> OrchestraConfig:
        devices = [device(f'fdd-{i}', 'FDD', 'FDD_CURRENT') for i in range(1, fdd + 1)]
        devices += [device(f'vhs-{i}', 'VHS', 'VHS_CURRENT') for i in range(1, vhs + 1)]
        devices += [device(f'hdd-{i}', 'HDD_VCM', 'WD_CAVIAR_CURRENT') for i in range(1, hdd + 1)]

        return OrchestraConfig(devices=devices, policy={**BALANCED, **policy})

    def plan(self, notes, config=None, pins=None, name='Song') -> PerformancePlan:
        return allocator.allocate(self.source(notes, name), config or self.orchestra(),
                                  pins=pins)

    @staticmethod
    def by_id(plan) -> dict:
        return {event.id: event for event in plan.events}


class TestFreeDeviceIsAlwaysUsed(AllocatorTestCase):
    """Przypadek 1: FDD1 zajete, FDD2 wolne -> nuta gra na FDD2, nie DROP."""

    def test_note_goes_to_any_free_device(self):
        source = self.source([(0.0, 1.0, 60), (0.1, 0.4, 64)], name='Two')
        plan = allocator.allocate(source, self.orchestra(fdd=2, vhs=0))
        events = self.by_id(plan)

        self.assertEqual(plan.report()['totals']['dropped'], 0)
        first = events['1:0']
        second = events['1:1']
        self.assertNotEqual(first.device_id, second.device_id)
        self.assertEqual(second.outcome, 'REASSIGNED')
        self.assertEqual(second.start, second.actual_start)

    def test_preferred_device_busy_still_plays_elsewhere(self):
        # Ta sama wysokosc na jednym urzadzeniu wymaga przerwy, wiec druga
        # nuta MUSI trafic na inne urzadzenie - inaczej bylby to DROP.
        source = self.source([(0.0, 0.5, 60), (0.05, 0.5, 60)], name='Repeat')
        plan = allocator.allocate(source, self.orchestra(fdd=2, vhs=0))

        self.assertEqual(plan.report()['totals']['dropped'], 0)
        self.assertEqual(len({event.device_id for event in plan.events}), 2)


class TestMicroDelay(AllocatorTestCase):
    """Przypadek 2: wszystkie FDD zajete, jedno zwalnia w oknie delayu."""

    def test_short_wait_becomes_delayed_not_dropped(self):
        # Trzy dlugie nuty zajmuja 3 FDD; czwarta startuje 10 ms przed
        # zwolnieniem pierwszego urzadzenia.
        notes = [(0.0, 0.5, 60), (0.0, 0.5, 64), (0.0, 0.5, 67), (0.49, 0.8, 72)]
        plan = allocator.allocate(self.source(notes, name='Chord'),
                                  self.orchestra(fdd=3, vhs=0, maxMicroDelayMs=30.0))
        last = self.by_id(plan)['1:3']

        self.assertEqual(last.outcome, 'DELAYED')
        self.assertAlmostEqual(last.actual_start, 0.5, places=3)
        self.assertAlmostEqual(last.delay, 0.01, places=3)
        self.assertEqual(plan.report()['totals']['dropped'], 0)

    def test_wait_beyond_window_is_not_delayed(self):
        # Urzadzenie zwalnia sie po 300 ms, a budzet delayu to 30 ms.
        notes = [(0.0, 1.0, 60), (0.0, 1.0, 64), (0.0, 1.0, 67), (0.7, 1.4, 72)]
        plan = allocator.allocate(self.source(notes, name='Slow'),
                                  self.orchestra(fdd=3, vhs=0, maxMicroDelayMs=30.0,
                                                 allowVoiceSteal=False))
        last = self.by_id(plan)['1:3']

        self.assertEqual(last.outcome, 'DROPPED')
        self.assertEqual(last.reason, 'ALL_DEVICES_BUSY_AND_NO_DELAY')


class TestLeadProtection(AllocatorTestCase):
    """Przypadek 3: konflikt lead + akompaniament -> lead przezywa."""

    def test_lead_keeps_the_lead_device(self):
        # Track 0: dluga linia melodyczna (lead). Track 1: akordy.
        melody = [(index * 0.5, index * 0.5 + 0.45, 72 + (index % 5)) for index in range(8)]
        chords = [(index * 0.5, index * 0.5 + 0.45, 48) for index in range(8)]
        source = self.source(melody, name='Lead')

        # Dwie sciezki wymagaja dwoch trackow - dopisujemy akompaniament.
        path = write_midi(self.tmp / 'Both.mid', melody, name='Vocal')
        source = MidiSource(path)
        plan = allocator.allocate(source, self.orchestra(fdd=2, vhs=1))

        report = plan.report()

        self.assertGreater(report['tonal']['played'], 0)
        self.assertEqual(report['totals']['dropped'], 0)

    def test_harmony_pin_to_vhs_is_ignored(self):
        """Reczna regula nie moze zlamac rozdzialu rol: VHS zostaje dla leadu."""
        source = self.source([(0.0, 1.0, 60)], name='One')
        config = self.orchestra(fdd=1, vhs=1)
        plan = allocator.allocate(source, config,
                                  pins={'1:0': ManualPin(device_id='vhs-1', rule_id='pin')})

        self.assertNotEqual(plan.events[0].device_id, 'vhs-1')
        self.assertEqual(plan.events[0].device_id, 'fdd-1')


class TestPercussionPool(AllocatorTestCase):
    """Przypadki 4 i 5: pula HDD - reassignment i drop dopiero gdy brak opcji."""

    def test_kick_falls_back_to_free_hdd(self):
        # Dwa uderzenia blizej niz cykl HDD (~105 ms) - drugie idzie na HDD2.
        notes = [(0.0, 0.05, 36), (0.087, 0.137, 36)]
        source = MidiSource(write_drums(self.tmp / 'Kick.mid', notes))
        plan = allocator.allocate(source, self.orchestra(fdd=1, vhs=0, hdd=3))
        events = plan.events

        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0].device_id, events[1].device_id)
        self.assertEqual(events[1].outcome, 'REASSIGNED')
        self.assertEqual(plan.report()['totals']['dropped'], 0)

    def test_all_hammers_busy_drops(self):
        # Cztery uderzenia w tej samej chwili, trzy mlotki - czwarte musi wypasc,
        # bo cykl HDD jest duzo dluzszy niz okno micro-delayu.
        notes = [(0.0, 0.05, note) for note in (36, 38, 42, 46)]
        source = MidiSource(write_drums(self.tmp / 'All.mid', notes))
        plan = allocator.allocate(source, self.orchestra(fdd=1, vhs=0, hdd=3),
                                  midi_analysis=None)

        self.assertEqual(plan.report()['totals']['dropped'], 1)
        dropped = [event for event in plan.events if event.outcome == 'DROPPED']
        self.assertEqual(dropped[0].reason, 'ALL_HAMMERS_BUSY')


class TestDeterminism(AllocatorTestCase):
    """Przypadek 6: ten sam input zawsze daje ten sam plan."""

    def test_same_input_gives_identical_plan(self):
        notes = [(index * 0.13, index * 0.13 + 0.4, 55 + (index * 7) % 25)
                 for index in range(60)]
        first = self.plan(notes, name='Det')
        second = self.plan(notes, name='Det')

        self.assertEqual([event.as_dict() for event in first.events],
                         [event.as_dict() for event in second.events])
        self.assertEqual(first.report()['totals'], second.report()['totals'])

    def test_device_order_does_not_depend_on_dict_iteration(self):
        notes = [(0.0, 0.4, 60), (0.0, 0.4, 64), (0.0, 0.4, 67)]
        config = self.orchestra(fdd=3, vhs=1)
        plan = allocator.allocate(self.source(notes, name='Chord'), config)
        devices = [event.device_id for event in plan.events]

        # Akord (rola harmony) trafia wylacznie na pule FDD - VHS nie jest
        # nawet na liscie kandydatow, wiec nie moze przejac akordu.
        self.assertEqual(devices, ['fdd-1', 'fdd-2', 'fdd-3'])


class TestInvariantNoDropWhenDeviceFree(AllocatorTestCase):
    """Podstawowy invariant v1, sprawdzony na losowej siatce nut."""

    def test_random_dense_material_never_drops_with_a_free_device(self):
        notes = []

        for index in range(120):
            start = index * 0.017

            for offset, pitch in enumerate((48, 55, 60, 64, 67)):
                if (index + offset) % 3:
                    notes.append((start, start + 0.12, pitch))

        path = write_midi(self.tmp / 'Dense.mid', notes, name='Dense')
        source = MidiSource(path)
        config = self.orchestra(fdd=3, vhs=1, hdd=0, maxMicroDelayMs=30.0)
        plan = allocator.allocate(source, config)

        for event in plan.events:
            if event.outcome != 'DROPPED':
                continue

            # DROP jest dozwolony tylko wtedy, gdy w chwili startu zadne
            # kompatybilne urzadzenie nie bylo wolne.
            others = [e for e in plan.events
                      if e.id != event.id and e.device_id is not None
                      and e.role != 'percussion' and e.outcome != 'DROPPED']
            busy = [e for e in others
                    if e.actual_start <= event.start + 1e-6 < e.end - 1e-6]
            self.assertGreaterEqual(len(busy), len(config.devices),
                                    f'{event.id} dropniete, choc byly wolne glosy')


if __name__ == '__main__':
    unittest.main()


# ============================================================
# VHS = DEDICATED_LEAD_ONLY (twardy rozdzial pul)
# ============================================================


def analysis_with(roles: dict[str, str], lead_track: int | None = None) -> MidiAnalysis:
    """Analiza z jawnymi rolami - testujemy allocator, nie heurystyke."""
    return MidiAnalysis(tracks=[], lead_track=lead_track, lead_confidence=1.0,
                        bass_track=None, bass_confidence=0.0, roles=roles,
                        lead_notes=tuple(sorted(key for key, role in roles.items()
                                                if role == 'lead')))


class TestVhsIsLeadOnly(AllocatorTestCase):
    """VHS nie nalezy do puli akompaniamentu w ZADNEJ sytuacji."""

    def allocate(self, notes, roles, config=None, **kwargs):
        source = self.source(notes, name=kwargs.pop('name', 'VhsSong'))

        return allocator.allocate(source, config or self.orchestra(fdd=3, vhs=1),
                                  midi_analysis=analysis_with(roles), **kwargs)

    def test_1_lead_note_goes_to_vhs(self):
        plan = self.allocate([(0.0, 0.5, 72)], {'1:0': 'lead'})

        self.assertEqual(plan.events[0].device_id, 'vhs-1')
        self.assertEqual(plan.events[0].role, 'lead')
        self.assertEqual(plan.events[0].outcome, 'ACCEPTED')

    def test_2_harmony_never_touches_vhs_even_when_everything_is_free(self):
        notes = [(0.0, 0.5, 60), (0.0, 0.5, 64), (0.0, 0.5, 67), (2.0, 2.5, 71)]
        roles = {f'1:{index}': 'harmony' for index in range(4)}
        plan = self.allocate(notes, roles)
        devices = {event.device_id for event in plan.events}

        self.assertTrue(devices <= {'fdd-1', 'fdd-2', 'fdd-3'}, devices)
        self.assertNotIn('vhs-1', devices)
        self.assertEqual(plan.report()['devices'][-1]['deviceId'], 'vhs-1')
        vhs = next(item for item in plan.report()['devices'] if item['deviceId'] == 'vhs-1')
        self.assertEqual(vhs['notes'], 0)

    def test_3_harmony_while_all_fdd_busy_never_falls_back_to_vhs(self):
        # Trzy dlugie nuty zajmuja 3 FDD, czwarta startuje tuz po nich.
        notes = [(0.0, 2.0, 60), (0.0, 2.0, 64), (0.0, 2.0, 67), (0.05, 2.0, 71)]
        roles = {f'1:{index}': 'harmony' for index in range(4)}
        plan = self.allocate(notes, roles, config=self.orchestra(fdd=3, vhs=1,
                                                                 allowVoiceSteal=False))
        last = self.by_id(plan)['1:3']

        self.assertIn(last.outcome, ('DELAYED', 'ARPEGGIATED', 'DROPPED'))
        self.assertNotEqual(last.device_id, 'vhs-1')
        self.assertFalse(any(event.device_id == 'vhs-1' for event in plan.events))

    def test_4_bass_never_touches_vhs(self):
        plan = self.allocate([(0.0, 0.5, 36), (1.0, 1.5, 38)], {'1:0': 'bass', '1:1': 'bass'})

        self.assertTrue(all(event.device_id in ('fdd-1', 'fdd-2', 'fdd-3')
                            for event in plan.events))
        self.assertTrue(all(event.role == 'bass' for event in plan.events))

    def test_5_overlapping_lead_stays_on_vhs(self):
        # Druga nuta leadu startuje, gdy pierwsza jeszcze brzmi: VHS skraca
        # poprzednia i gra dalej. Melodia NIGDY nie spada na FDD.
        notes = [(0.0, 1.0, 72), (0.5, 1.0, 74)]
        roles = {'1:0': 'lead', '1:1': 'lead'}
        plan = self.allocate(notes, roles)
        first = self.by_id(plan)['1:0']
        second = self.by_id(plan)['1:1']

        self.assertEqual(first.device_id, 'vhs-1')
        self.assertEqual(second.device_id, 'vhs-1')
        self.assertEqual(first.outcome, 'SHORTENED')
        self.assertEqual(second.outcome, 'STOLEN')
        self.assertAlmostEqual(first.actual_duration, 0.5, places=3)
        self.assertAlmostEqual(second.actual_start, 0.5, places=3)

    def test_6_accompaniment_cannot_steal_the_lead_voice(self):
        # Lead trzyma VHS; harmonia nie moze go stad wygryzc.
        notes = [(0.0, 2.0, 72), (0.5, 0.6, 60), (0.5, 0.6, 64), (0.5, 0.6, 67),
                 (0.5, 0.6, 71)]
        roles = {'1:0': 'lead'}
        roles.update({f'1:{index}': 'harmony' for index in range(1, 5)})
        plan = self.allocate(notes, roles)
        lead = self.by_id(plan)['1:0']

        self.assertEqual(lead.device_id, 'vhs-1')
        self.assertEqual(lead.outcome, 'ACCEPTED')
        self.assertEqual(lead.actual_duration, 2.0)
        self.assertFalse(any(event.device_id == 'vhs-1' and event.role != 'lead'
                             for event in plan.events))

    def test_empty_vhs_when_lead_is_silent(self):
        """Lead milczy w drugiej polowie - VHS ma pozostac cichy."""
        notes = [(0.0, 0.5, 72)]
        roles = {'1:0': 'lead'}
        plan = self.allocate(notes + [(3.0, 3.5, 60), (3.0, 3.5, 64), (3.0, 3.5, 67)],
                             {**roles, '1:1': 'harmony', '1:2': 'harmony', '1:3': 'harmony'})
        vhs = [event for event in plan.events if event.device_id == 'vhs-1']

        self.assertEqual(len(vhs), 1)
        self.assertEqual(vhs[0].id, '1:0')
        self.assertTrue(all(event.actual_start < 1.0 for event in vhs))

    def test_invariant_every_vhs_event_is_lead(self):
        """Globalny invariant: VHS => LEAD, bez wyjatkow."""
        notes = []
        roles = {}

        for index in range(30):
            notes.append((index * 0.25, index * 0.25 + 0.2, 72 + (index % 7)))
            roles[f'1:{index}'] = 'lead'

        for index in range(30, 90):
            offset = (index - 30) * 0.1
            notes.append((offset, offset + 0.15, 48 + (index % 12)))
            roles[f'1:{index}'] = 'bass' if index % 5 == 0 else 'harmony'

        plan = self.allocate(notes, roles)

        for event in plan.events:
            if event.device_id == 'vhs-1':
                self.assertEqual(event.role, 'lead', f'{event.id} na VHS z rola {event.role}')


class TestJigsawLeadIsClean(AllocatorTestCase):
    """Przypadek 6 dla prawdziwego utworu: na VHS wylacznie wykryty lead."""

    SONG = (Path(__file__).resolve().parents[2]
            / 'midi' / '0087-09-radiohead_2007-jigsaw_falling_into_place.mid')

    def setUp(self):
        super().setUp()

        if not self.SONG.is_file():
            self.skipTest(f'brak pliku benchmarkowego {self.SONG.name}')

    def test_every_vhs_event_comes_from_the_detected_lead(self):
        from playback import analysis as analysis_module

        source = MidiSource(self.SONG)
        profile = analysis_module.analyze(source)
        plan = allocator.allocate(source, default_orchestra(), midi_analysis=profile)

        self.assertIsNotNone(profile.lead_track)
        self.assertGreater(len(profile.lead_notes), 0)
        vhs = [event for event in plan.events if event.device_id == 'vhs-1']

        self.assertGreater(len(vhs), 0, 'lead musi trafic na VHS')

        for event in vhs:
            self.assertEqual(event.role, 'lead', f'{event.id} nie jest leadem')
            self.assertEqual(event.track, profile.lead_track,
                             f'{event.id} pochodzi z tracku {event.track}, nie z leadu')
            self.assertIn(event.id, profile.lead_notes)

        # I odwrotnie: zaden lead nie moze wyladowac poza VHS.
        outside = [event for event in plan.events
                   if event.role == 'lead' and event.device_id not in (None, 'vhs-1')]
        self.assertEqual(outside, [])

    def test_lead_preservation_is_total(self):
        from playback import analysis as analysis_module

        source = MidiSource(self.SONG)
        profile = analysis_module.analyze(source)
        plan = allocator.allocate(source, default_orchestra(), midi_analysis=profile)
        lead = [event for event in plan.events if event.role == 'lead']

        self.assertTrue(lead)
        self.assertTrue(all(event.played for event in lead),
                        [event.id for event in lead if not event.played])

    def test_vhs_is_idle_for_a_third_of_the_song(self):
        """Dedykowany VHS swiadomie nie gra, gdy nie ma leadu."""
        from playback import analysis as analysis_module

        source = MidiSource(self.SONG)
        profile = analysis_module.analyze(source)
        plan = allocator.allocate(source, default_orchestra(), midi_analysis=profile)
        report = plan.report()
        vhs = next(item for item in report['devices'] if item['deviceId'] == 'vhs-1')

        self.assertLess(vhs['utilization'], 0.8)
        self.assertEqual(vhs['notes'], len([e for e in plan.events if e.device_id == 'vhs-1']))
