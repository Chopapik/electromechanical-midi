"""Testy warstwy webowej: REST, WebSocket i sterowanie silnikiem.

Uzywaja TestClient (bez sieci) i FakeTransport (bez Arduino).
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from playback.engine import PlaybackEngine, PlaybackState  # noqa: E402
from web.server import create_app  # noqa: E402

TPB = 480
TEMPO = 500_000
TICKS_PER_SECOND = TPB * 1_000_000 // TEMPO


class FakeTransport:
    def __init__(self):
        self.port = "/dev/fake"
        self.label = "Fake"
        self.events: list[str] = []

    def send(self, command: str) -> None:
        self.events.append(command)

    def play(self, hz: float) -> None:
        self.events.append(f"PLAY {hz:.2f}")

    def stop(self) -> None:
        self.events.append("STOP")

    def ping(self) -> None:
        self.events.append("PING")

    def poll_lines(self) -> list[str]:
        return []

    def close(self) -> None:
        pass


def write_midi(path: Path, notes, name: str = "Test") -> Path:
    midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name=name, time=0))

    events = []

    for start, end, note in notes:
        events.append((round(start * TICKS_PER_SECOND), 0, note))
        events.append((round(end * TICKS_PER_SECOND), 1, note))

    events.sort(key=lambda event: (event[0], event[1]))

    previous = 0

    for tick, kind, note in events:
        delta = tick - previous
        previous = tick
        track.append(
            mido.Message(
                "note_on" if kind == 0 else "note_off",
                note=note,
                velocity=100 if kind == 0 else 0,
                time=delta,
            )
        )

    midi.save(path)

    return path


def read_until_state(websocket, timeout: float = 3.0) -> dict:
    """Czyta wiadomosci z WS az trafi na stan (albo zwraca ostatni blad)."""
    deadline = time.monotonic() + timeout
    last = None

    while time.monotonic() < deadline:
        message = websocket.receive_json()

        if message.get("type") == "state":
            return message["state"]

        last = message

        if message.get("type") == "error":
            raise AssertionError(f"blad z serwera: {message}")

    raise AssertionError(f"nie doczekalem sie stanu (ostatnie: {last})")


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.midi_dir = Path(self._tmp.name)
        self.transport = FakeTransport()

        write_midi(
            self.midi_dir / "song.mid",
            [(0.0, 1.0, 60), (2.0, 3.0, 64), (3.0, 3.5, 67)],
            name="Piano",
        )
        write_midi(self.midi_dir / "other.midi", [(0.0, 4.0, 48)], name="Bas")
        (self.midi_dir / "notatka.txt").write_text("to nie midi")

        self.engine = PlaybackEngine(connect_fn=lambda port: self.transport, keepalive=0.2)
        self.app = create_app(
            midi_dir=self.midi_dir,
            engine=self.engine,
            connect_on_start=False,
        )

        self._client = TestClient(self.app)
        self.client = self._client.__enter__()
        self.assertTrue(self.engine.connect())

    def tearDown(self):
        self._client.__exit__(None, None, None)
        self._tmp.cleanup()


class TestRest(WebTestCase):
    def test_telemetry_is_read_only_and_empty_before_loading(self):
        before = self.engine.snapshot()
        response = self.client.get('/api/telemetry')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['events'], [])
        self.assertIsNone(response.json()['file'])
        after = self.engine.snapshot()
        for field in ('file', 'state', 'position', 'arrangementRevision', 'arrangementActive'):
            self.assertEqual(before[field], after[field])
        self.assertIsNone(self.engine._plan)

    def test_telemetry_projects_renderer_and_frequency_curves_without_changing_plan(self):
        from playback.orchestra import web_startup_config
        self.engine.configure_virtual(web_startup_config())
        midi = mido.MidiFile(self.midi_dir / 'song.mid')
        midi.tracks[1].insert(2, mido.Message('pitchwheel', pitch=4096, time=240))
        midi.save(self.midi_dir / 'song.mid')
        self.engine.load_file(self.midi_dir / 'song.mid')
        plan = self.engine._plan
        before = plan.as_dict() if hasattr(plan, 'as_dict') else repr(plan)
        self.engine.seek(.5)
        self.engine.pause()
        state = self.engine.snapshot()
        view = self.client.get('/api/telemetry').json()
        self.assertEqual(view['file'], 'song.mid')
        self.assertEqual(view['revision'], state['arrangementRevision'])
        self.assertTrue(view['events'])
        acoustic = [e for e in self.engine._virtual.events if e.kind in ('tone', 'hit', 'tray')]
        self.assertEqual(len(view['events']), len(acoustic))
        self.assertEqual(sorted(e.time for e in acoustic), [e['start'] for e in view['events']])
        tone = next(e for e in view['events'] if e['kind'] == 'tone')
        original = next(e for e in acoustic if e.device == tone['deviceId'] and e.time == tone['start'] and e.kind == 'tone')
        self.assertEqual(tone['frequencyCurve']['values'], list(original.tonal_articulation.frequency.values))
        self.assertGreater(len(set(tone['frequencyCurve']['values'])), 1)
        self.assertEqual(tone['note'], round(__import__('pitch').hz_to_midi(original.hz)))
        self.assertEqual(tone['profile'], original.tonal_articulation.profile)
        self.assertEqual(tone['track'], original.source_track)
        self.assertEqual(view['activity'], {k: [list(row) for row in rows] for k, rows in self.engine._virtual.activity.items()})
        self.assertIs(plan, self.engine._plan)
        self.assertEqual(before, plan.as_dict() if hasattr(plan, 'as_dict') else repr(plan))
        after = self.engine.snapshot()
        self.assertEqual(after['position'], state['position'])
        self.assertEqual(after['state'], state['state'])

    def test_arrangement_api_save_load_and_mismatch(self):
        self.engine.load_file(self.midi_dir / 'song.mid')
        initialized = self.client.post('/api/arrangement/initialize')
        self.assertEqual(initialized.status_code, 200)
        document = initialized.json()['arrangement']
        document['devices'] = [{'id': 'hdd', 'type': 'HDD_VCM'}]
        document['rules'] = [{'id': 'kick', 'source': {'track': 1, 'includeNotes': [60]},
                              'destination': {'deviceId': 'hdd'}}]
        updated = self.client.put('/api/arrangement', json=document)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['notes'][0]['routes'][0]['deviceId'], 'hdd')
        self.assertEqual(self.client.post('/api/arrangement/save').status_code, 200)
        saved = self.client.get('/api/arrangement/saved').json()
        self.assertEqual(saved['file'], 'song.orchestra.json')
        self.assertEqual(saved['arrangement']['rules'][0]['id'], 'kick')
        self.engine.load_file(self.midi_dir / 'song.mid')
        restored = self.client.post('/api/arrangement/initialize')
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['arrangement']['rules'][0]['id'], 'kick')
        document['midi']['tracks'][1]['name'] = 'wrong'
        mismatch = self.client.put('/api/arrangement', json=document)
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()['detail']['mismatches'][0]['kind'], 'track')

    def test_virtual_preset_round_trip(self):
        config = {'name': 'Two FDD', 'devices': [
            {'id': 'a', 'type': 'FDD', 'track': 1},
            {'id': 'b', 'type': 'FDD', 'track': 1},
        ]}
        response = self.client.put('/api/virtual/presets/Two FDD', json=config)
        self.assertEqual(response.status_code, 200)
        saved = self.client.get('/api/virtual/presets').json()['presets']['Two FDD']
        self.assertEqual([d['id'] for d in saved['devices']], ['a', 'b'])
        self.assertEqual(self.client.delete('/api/virtual/presets/Two FDD').status_code, 200)
        self.assertEqual(self.client.get('/api/virtual/presets').json()['presets'], {})

    def test_four_dvd_instances_survive_virtual_preset_save_and_load(self):
        config = {'name': 'DVD overflow', 'devices': [
            {'id': f'dvd-{number}', 'type': 'DVD_SLED', 'profile': 'DVD_REFERENCE',
             'mode': 'virtual', 'volume': .2}
            for number in range(1, 5)
        ]}
        response = self.client.put('/api/virtual/presets/DVD overflow', json=config)
        self.assertEqual(response.status_code, 200)
        saved = self.client.get('/api/virtual/presets').json()['presets']['DVD overflow']
        self.assertEqual([item['id'] for item in saved['devices']],
                         ['dvd-1', 'dvd-2', 'dvd-3', 'dvd-4'])
        self.assertTrue(all(item['volume'] == .2 and item['mode'] == 'virtual'
                            for item in saved['devices']))

    def test_lista_plikow(self):
        response = self.client.get("/api/files")

        self.assertEqual(response.status_code, 200)
        names = [entry["name"] for entry in response.json()["files"]]

        self.assertEqual(names, ["other.midi", "song.mid"])

    def test_metadane_pliku(self):
        response = self.client.get("/api/files/song.mid")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["name"], "song.mid")
        self.assertAlmostEqual(data["duration"], 3.5, places=2)
        self.assertEqual(len(data["tracks"]), 2)

        # Track 0 to konduktor (bez nut), track 1 to Piano.
        piano = data["tracks"][1]
        self.assertEqual(piano["name"], "Piano")
        self.assertEqual(piano["noteCount"], 3)
        self.assertFalse(piano["polyphonic"])

    def test_plik_poza_katalogiem_jest_odrzucany(self):
        for name in ("../host/player.py", "..%2Fsecret", ".ukryty"):
            response = self.client.get(f"/api/files/{name}")

            self.assertIn(response.status_code, (400, 404), name)

    def test_brak_pliku(self):
        self.assertEqual(self.client.get("/api/files/nie-ma.mid").status_code, 404)

    def test_stan_poczatkowy(self):
        state = self.client.get("/api/state").json()

        self.assertEqual(state["state"], "stopped")
        self.assertEqual(state["position"], 0.0)
        self.assertTrue(state["hardware"]["connected"])

    def test_porty(self):
        data = self.client.get("/api/ports").json()

        self.assertIn("ports", data)
        self.assertIn("current", data)

    def test_konfiguracja(self):
        data = self.client.get("/api/config").json()

        self.assertIn("low", data["transposeModes"])
        self.assertIn("highest", data["strategies"])


class TestWebSocket(WebTestCase):
    def test_repeated_file_selection_does_not_reset_playback(self):
        from unittest.mock import patch
        self.engine.load_file(self.midi_dir / 'song.mid', 1)
        self.engine.play()
        self.engine.seek(1.0)
        revision = self.engine.snapshot()['arrangementRevision']
        with self.client.websocket_connect('/ws') as websocket:
            read_until_state(websocket)
            with patch.object(self.engine, 'load_file') as load:
                websocket.send_json({'action': 'set_file', 'file': 'song.mid'})
                state = read_until_state(websocket)
                self.assertEqual(state['state'], 'playing')
                self.assertGreaterEqual(state['position'], 1.0)
                self.assertEqual(state['arrangementRevision'], revision)
                load.assert_not_called()

    def test_play_response_marks_completed_command(self):
        self.engine.load_file(self.midi_dir / "song.mid", 1)
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)
            websocket.send_json({"action": "play"})
            for _ in range(20):
                message = websocket.receive_json()
                if message.get("completedAction") == "play":
                    self.assertEqual(message["state"]["state"], "playing")
                    break
            else:
                self.fail("missing completed play response")


    def test_pierwsza_wiadomosc_to_stan(self):
        with self.client.websocket_connect("/ws") as websocket:
            state = read_until_state(websocket)

            self.assertEqual(state["state"], "stopped")

    def test_wybor_pliku_i_tracku(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            state = read_until_state(websocket)

            self.assertEqual(state["file"], "song.mid")
            self.assertEqual(state["track"], 1)
            self.assertEqual(state["trackName"], "Piano")
            self.assertAlmostEqual(state["duration"], 3.5, places=2)

    def test_play_seek_pause_stop_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)
            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "play"})
            state = read_until_state(websocket)
            self.assertEqual(state["state"], "playing")

            websocket.send_json({"action": "seek", "position": 2.5})
            state = read_until_state(websocket)
            self.assertEqual(state["state"], "playing")
            self.assertGreaterEqual(state["position"], 2.4)
            # 2.5 s to srodek nuty E4 (2.0-3.0) - musi byc slyszalna.
            self.assertEqual(state["noteName"], "E4")

            websocket.send_json({"action": "pause"})
            state = read_until_state(websocket)
            self.assertEqual(state["state"], "paused")
            self.assertIsNone(state["noteName"])

            websocket.send_json({"action": "resume"})
            state = read_until_state(websocket)
            self.assertEqual(state["state"], "playing")

            websocket.send_json({"action": "stop"})
            state = read_until_state(websocket)
            self.assertEqual(state["state"], "stopped")
            self.assertEqual(state["position"], 0.0)

    def test_zmiana_transpozycji(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)
            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_transpose", "mode": "low"})
            state = read_until_state(websocket)

            self.assertEqual(state["transpose"], "low")

    def test_nieznana_akcja_daje_blad(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "zagraj_to"})
            message = websocket.receive_json()

            self.assertEqual(message["type"], "error")

    def test_zly_json_daje_blad(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_text("to nie jest json")
            message = websocket.receive_json()

            self.assertEqual(message["type"], "error")

    def test_brak_pliku_w_set_file(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "nie-ma.mid"})
            message = websocket.receive_json()

            self.assertEqual(message["type"], "error")

    def test_seek_w_trakcie_grania_gra_nute_w_toku(self):
        """Najwazniejszy przypadek: seek w srodek trwajacej nuty."""
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)
            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "play"})
            read_until_state(websocket)

            self.transport.events.clear()
            websocket.send_json({"action": "seek", "position": 2.4})
            state = read_until_state(websocket)

            self.assertEqual(state["noteName"], "E4")
            # Arduino dostaje STOP + PLAY tej nuty, i nic wiecej.
            self.assertEqual(
                [
                    event
                    for event in self.transport.events
                    if event.startswith(("PLAY", "STOP"))
                ],
                ["STOP", "PLAY 329.63"],
            )


class TestSilnikWWeb(WebTestCase):
    def test_stan_jest_jeden_dla_wielu_klientow(self):
        """Dwa WebSockety nie moga uruchomic dwoch niezaleznych schedulerow."""
        with self.client.websocket_connect("/ws") as first:
            read_until_state(first)

            with self.client.websocket_connect("/ws") as second:
                read_until_state(second)

                first.send_json({"action": "set_file", "file": "song.mid", "track": 1})
                read_until_state(first)

                first.send_json({"action": "play"})
                read_until_state(first)

                self.assertIs(self.engine.state, PlaybackState.PLAYING)

                # Drugi klient widzi ten sam stan (nie ma drugiego playera).
                second.send_json({"action": "snapshot"})
                state = read_until_state(second)

                self.assertEqual(state["state"], "playing")
                self.assertEqual(state["file"], "song.mid")


if __name__ == "__main__":
    unittest.main()


class TestDrumWeb(WebTestCase):
    """Sterowanie VHS drum przez WebSocket + stan w /api/state."""

    def drum_actions(self) -> list[str]:
        return [event for event in self.transport.events if event.startswith("DRUM")]

    def test_stan_poczatkowy_zawiera_drum(self):
        state = self.client.get("/api/state").json()

        self.assertIn("drum", state)

        drum = state["drum"]
        self.assertEqual(drum["value"], 0)
        self.assertFalse(drum["running"])
        self.assertTrue(drum["connected"])
        self.assertEqual(drum["minHz"], 20)
        self.assertEqual(drum["maxHz"], 2000)

    def test_polaczenie_zeruje_beben(self):
        self.assertIn("DRUM 0", self.transport.events)

    def test_set_drum_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum", "value": 80})
            state = read_until_state(websocket)

            self.assertEqual(state["drum"]["value"], 80)
            self.assertTrue(state["drum"]["running"])
            self.assertIn("DRUM 80", self.transport.events)

    def test_stop_drum_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum", "value": 90})
            read_until_state(websocket)

            websocket.send_json({"action": "stop_drum"})
            state = read_until_state(websocket)

            self.assertEqual(state["drum"]["value"], 0)
            self.assertFalse(state["drum"]["running"])
            self.assertEqual(self.transport.events[-1], "DRUM 0")

    def test_start_drum_uzywa_ostatniej_wartosci(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum", "value": 110})
            read_until_state(websocket)
            websocket.send_json({"action": "stop_drum"})
            read_until_state(websocket)

            websocket.send_json({"action": "start_drum"})
            state = read_until_state(websocket)

            self.assertEqual(state["drum"]["value"], 110)

    def test_set_drum_poza_zakresem_daje_blad(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum", "value": 999})
            message = websocket.receive_json()

            self.assertEqual(message["type"], "error")
            self.assertNotIn("DRUM 999", self.transport.events)

    def test_set_drum_tone_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum_tone", "hz": 400})
            state = read_until_state(websocket)

            self.assertEqual(state["drum"]["toneHz"], 400)
            self.assertIn("DRUMF 400", self.transport.events)

    def test_set_drum_tone_zero_to_dc(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum_tone", "hz": 0})
            state = read_until_state(websocket)

            self.assertEqual(state["drum"]["toneHz"], 0)
            self.assertIn("DRUMF 0", self.transport.events)

    def test_set_drum_tone_poza_zakresem_daje_blad(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum_tone", "hz": 9999})
            message = websocket.receive_json()

            self.assertEqual(message["type"], "error")

    def test_rozłączenie_zeruje_stan_bebna_w_api(self):
        self.engine.set_drum(120)
        self.engine.disconnect()

        state = self.client.get("/api/state").json()["drum"]

        self.assertFalse(state["connected"])
        self.assertFalse(state["running"])
        self.assertEqual(state["value"], 0)
        self.assertIsNone(state["output"])

    def test_reconnect_zeruje_beben(self):
        self.engine.set_drum(120)
        self.engine.disconnect()

        self.transport.events.clear()
        self.assertTrue(self.engine.connect())

        self.assertIn("DRUM 0", self.transport.events)
        self.assertEqual(self.engine.snapshot()["drum"]["value"], 0)

    def test_start_utworu_zeruje_reczny_beben(self):
        """Transport jest nadrzedny: PLAY/PAUSE/STOP zawsze zeruja beben."""
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum", "value": 100})
            read_until_state(websocket)

            websocket.send_json({"action": "set_drum_tone", "hz": 300})
            read_until_state(websocket)

            websocket.send_json({"action": "play"})
            state = read_until_state(websocket)

            self.assertEqual(state["state"], "playing")
            self.assertEqual(state["drum"]["value"], 0)
            self.assertIn("DRUM 0", self.transport.events)

            websocket.send_json({"action": "stop"})
            state = read_until_state(websocket)

            self.assertEqual(state["state"], "stopped")
            self.assertEqual(state["drum"]["value"], 0)


class TestUpload(WebTestCase):
    """Wgrywanie MIDI z przegladarki (POST /api/files)."""

    def midi_bytes(self, notes=None) -> bytes:
        import io

        midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
        conductor = mido.MidiTrack()
        midi.tracks.append(conductor)
        conductor.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name="Wgrany", time=0))

        for start, end, note in (notes or [(0.0, 0.5, 60)]):
            track.append(
                mido.Message("note_on", note=note, velocity=100,
                             time=round(start * TICKS_PER_SECOND))
            )
            track.append(
                mido.Message("note_off", note=note, velocity=0,
                             time=round((end - start) * TICKS_PER_SECOND))
            )

        buffer = io.BytesIO()
        midi.save(file=buffer)

        return buffer.getvalue()

    def upload(self, name: str, data: bytes):
        return self.client.post(
            "/api/files", files={"file": (name, data, "audio/midi")}
        )

    def test_wgranie_poprawnego_pliku(self):
        response = self.upload("nowy.mid", self.midi_bytes())

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["name"], "nowy.mid")
        self.assertTrue((self.midi_dir / "nowy.mid").is_file())

        names = [entry["name"] for entry in body["files"]]
        self.assertIn("nowy.mid", names)

    def test_wgrany_plik_ma_metadane_i_da_sie_wybrac(self):
        self.upload("melodia.mid", self.midi_bytes([(0.0, 1.0, 64)]))

        meta = self.client.get("/api/files/melodia.mid").json()

        self.assertEqual(meta["tracks"][1]["name"], "Wgrany")
        self.assertEqual(meta["tracks"][1]["noteCount"], 1)

    def test_wgrany_plik_mozna_odtworzyc(self):
        self.upload("grany.mid", self.midi_bytes())

        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "grany.mid", "track": 1})
            state = read_until_state(websocket)

            self.assertEqual(state["file"], "grany.mid")
            self.assertEqual(state["track"], 1)

    def test_odrzuca_inne_rozszerzenie(self):
        response = self.upload("wirus.exe", self.midi_bytes())

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.midi_dir / "wirus.exe").exists())

    def test_odrzuca_plik_ktory_nie_jest_midi(self):
        response = self.upload("fake.mid", b"to zdecydowanie nie jest MIDI")

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.midi_dir / "fake.mid").exists())

    def test_odrzuca_pusty_plik(self):
        response = self.upload("pusty.mid", b"")

        self.assertEqual(response.status_code, 400)

    def test_nie_nadpisuje_istniejacego_pliku(self):
        first = self.upload("kolizja.mid", self.midi_bytes())
        second = self.upload("kolizja.mid", self.midi_bytes([(0.0, 2.0, 67)]))

        self.assertEqual(first.json()["name"], "kolizja.mid")
        self.assertEqual(second.json()["name"], "kolizja (2).mid")
        self.assertTrue((self.midi_dir / "kolizja.mid").is_file())
        self.assertTrue((self.midi_dir / "kolizja (2).mid").is_file())

    def test_sciezka_w_nazwie_jest_obcinana(self):
        response = self.upload("../../zly.mid", self.midi_bytes())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "zly.mid")
        self.assertTrue((self.midi_dir / "zly.mid").is_file())

    def test_za_duzy_plik(self):
        from web.server import MAX_UPLOAD_BYTES

        response = self.upload("wielki.mid", b"x" * (MAX_UPLOAD_BYTES + 10))

        self.assertEqual(response.status_code, 413)


class TestHddWeb(WebTestCase):
    """Sterowanie perkusja HDD przez WebSocket + stan w /api/state."""

    def test_stan_poczatkowy_zawiera_hdd(self):
        state = self.client.get("/api/state").json()

        self.assertIn("hdd", state)

        hdd = state["hdd"]
        self.assertIsNone(hdd["midiTrack"])
        self.assertIsNone(hdd["midiTrackName"])
        self.assertEqual(hdd["count"], 0)

    def test_set_hdd_track_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_hdd_track", "track": 1})
            state = read_until_state(websocket)

            self.assertEqual(state["hdd"]["midiTrack"], 1)
            self.assertIsNotNone(state["hdd"]["midiTrackName"])

    def test_set_hdd_track_none_wylacza(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)
            websocket.send_json({"action": "set_hdd_track", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_hdd_track", "track": None})
            state = read_until_state(websocket)

            self.assertIsNone(state["hdd"]["midiTrack"])


class TestHddNoteWeb(WebTestCase):
    """Wybor nuty perkusyjnej HDD przez WebSocket."""

    def test_set_hdd_note_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)
            websocket.send_json({"action": "set_hdd_track", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_hdd_note", "note": 40})
            state = read_until_state(websocket)

            self.assertEqual(state["hdd"]["note"], 40)

            websocket.send_json({"action": "set_hdd_note", "note": None})
            state = read_until_state(websocket)

            self.assertIsNone(state["hdd"]["note"])


class TestHddRateWeb(WebTestCase):
    """Limiter gestosci HDD przez WebSocket."""

    def test_set_hdd_rate_przez_websocket(self):
        with self.client.websocket_connect("/ws") as websocket:
            read_until_state(websocket)

            websocket.send_json({"action": "set_file", "file": "song.mid", "track": 1})
            read_until_state(websocket)
            websocket.send_json({"action": "set_hdd_track", "track": 1})
            read_until_state(websocket)

            websocket.send_json({"action": "set_hdd_rate", "rate": 1})
            state = read_until_state(websocket)

            self.assertEqual(state["hdd"]["rate"], 1)

            websocket.send_json({"action": "set_hdd_rate", "rate": None})
            state = read_until_state(websocket)

            self.assertIsNone(state["hdd"]["rate"])
