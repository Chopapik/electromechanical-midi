"""Test-only acoustic regression oracle. Never imported by application code."""
import dataclasses, math, struct, tempfile, wave
from array import array
from pathlib import Path
from playback.virtual import *
class WavePreview:
    """Disposable host-side PCM preview. Renderer consumes only accepted mechanical events."""
    RATE = 22050

    def __init__(self, *, clocked: bool = False):
        self.clocked = clocked
        self._audio_anchor = None
        self._audio_start = None
        self._audio_end = 0.0
        self._audio_diagnostic = ''
        self.audio_events = []
        self.master_volume = 1.0
        self.process: subprocess.Popen | None = None
        self.path: Path | None = None

    def stop(self):
        self._audio_start = None
        self._audio_anchor = None
        if self.process is not None:
            self.process.terminate()
            try: self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired: self.process.kill()
            self.process = None

    def close(self):
        self.stop()
        if hasattr(self, '_slice'):
            self._slice.unlink(missing_ok=True)
            del self._slice
        if self.path:
            self.path.unlink(missing_ok=True)
            self.path = None

    def _plan(self, orchestra: VirtualOrchestra, n: int) -> list[tuple]:
        """Zdarzenia do policzenia: (urzadzenie, profil, event, start, dlugosc).

        Instancje 'real' graja na prawdziwym sprzecie - podglad audio ich nie
        dubluje. Dzieki temu 'hybrid' nie brzmi podwojnie.
        """
        by_id = {d.id: d for d in orchestra.devices}
        ordinary = []
        hdd = {}
        tonal = {}
        self.tonal_stats = {'events': [], 'retriggers': 0, 'suppressedReinforcement': 0}
        self.hdd_stats = {'events': [], 'chokes': 0, 'suppressedReinforcement': 0}
        for event in orchestra.events:
            d = by_id[event.device]
            if not d.in_preview:
                continue
            # Reversals describe actuator travel, not an additional MIDI sound.
            # The former synthetic 1700 Hz knock dominated sustained FDD notes.
            # Keep mechanical events/statistics, but omit that uncalibrated audio.
            if event.kind == 'reversal':
                continue
            if event.kind == 'tone':
                tonal.setdefault(d.id, []).append(event)
            elif d.type == 'HDD_VCM' and event.kind == 'hit':
                if event.hdd_articulation is None:
                    raise ValueError('HDD hit is missing its domain articulation')
                hdd.setdefault(d.id, []).append(event)
            else:
                start = int(event.time * self.RATE)
                length = min(n - start, int((event.duration if event.kind in ('tone', 'tray') else .12) * self.RATE))
                if length > 0:
                    ordinary.append((d, effective_profile(d), event, start, length))
        for ident, tones in tonal.items():
            d = by_id[ident]
            tones.sort(key=lambda e: (e.time, e.reinforcement))
            next_primary = None
            upcoming = [None]*len(tones)
            for i in range(len(tones)-1, -1, -1):
                upcoming[i] = next_primary
                if not tones[i].reinforcement: next_primary = tones[i]
            lane = []
            for i, event in enumerate(tones):
                start = int(event.time*self.RATE)
                art = event.tonal_articulation
                if art is None:
                    # Manual legacy simulation has no semantic PerformancePlan.
                    art = TonalArticulation('CONTINUOUS', d.type, .006, .1, .7, .035,
                        event.duration, .5, .15, (event.velocity/127)**.65,
                        source_duration=event.duration, velocity=event.velocity,
                        frequency=Curve((0.,),(event.hz,)))
                art = apply_tonal_mode(art, orchestra.tonal_mode)
                duration = art.gate+art.release
                if event.reinforcement:
                    if lane and not lane[-1][2].reinforcement and lane[-1][3]+lane[-1][4]>start:
                        self.tonal_stats['suppressedReinforcement'] += 1
                        continue
                    if upcoming[i]: duration=min(duration, max(0.,upcoming[i].time-event.time))
                    duration=min(duration,event.duration) # never extend extra beyond its reservation
                length=min(n-start,int(duration*self.RATE))
                if length<=0: continue
                if lane and lane[-1][3]+lane[-1][4]>start:
                    previous=lane[-1]
                    lane[-1]=(*previous[:4], max(0,start-previous[3]))
                    self.tonal_stats['retriggers']+=1
                event=dataclasses.replace(event,tonal_articulation=art)
                lane.append((d,effective_profile(d),event,start,length))
            for row in lane:
                event,start,length=row[2:]
                self.tonal_stats['events'].append(dict(event.tonal_articulation.debug(),
                    sourceId=event.source_id, track=event.source_track, start=event.time,
                    deviceId=ident, reinforcement=event.reinforcement, audioDuration=length/self.RATE,
                    truncated=length<int((event.tonal_articulation.gate+event.tonal_articulation.release)*self.RATE)))
            ordinary.extend(row for row in lane if row[4]>0)
        for ident, hits in hdd.items():
            d = by_id[ident]
            hits.sort(key=lambda e: (e.time, e.reinforcement))
            primary_indices = [i for i, event in enumerate(hits) if not event.reinforcement]
            primary_gaps = {}
            for position, i in enumerate(primary_indices):
                neighbors = [primary_indices[j] for j in (position-1, position+1)
                             if 0 <= j < len(primary_indices)]
                primary_gaps[i] = min((abs(hits[i].time-hits[j].time) for j in neighbors), default=math.inf)
            adapted = []
            for i, event in enumerate(hits):
                gaps = [abs(event.time - hits[j].time) for j in (i-1, i+1) if 0 <= j < len(hits)]
                # An optional extra must not change a normal hit's timbre/decay.
                gap = min(gaps, default=math.inf) if event.reinforcement else primary_gaps[i]
                art = adapt_hdd(event.hdd_articulation, gap, orchestra.hdd_mode == 'raw')
                adapted.append(dataclasses.replace(event, hdd_articulation=art))
            next_primaries = [None] * len(adapted)
            next_primary = None
            for i in range(len(adapted) - 1, -1, -1):
                next_primaries[i] = next_primary
                if not adapted[i].reinforcement:
                    next_primary = adapted[i]
            lane = []
            for i, event in enumerate(adapted):
                start = int(event.time * self.RATE)
                length = min(n - start, int(event.hdd_articulation.duration * self.RATE))
                if length <= 0:
                    continue
                # Acoustic extras cannot interrupt a normal actuator gesture/tail.
                if event.reinforcement and lane and not lane[-1][2].reinforcement and lane[-1][3] + lane[-1][4] > start:
                    self.hdd_stats['suppressedReinforcement'] += 1
                    continue
                if event.reinforcement:
                    next_primary = next_primaries[i]
                    if next_primary is not None:
                        length = min(length, max(0, int(next_primary.time * self.RATE) - start))
                if lane and lane[-1][3] + lane[-1][4] > start:
                    previous = lane[-1]
                    lane[-1] = (*previous[:4], max(0, start - previous[3]))
                    self.hdd_stats['chokes'] += 1
                lane.append((d, effective_profile(d), event, start, length))
            for item in lane:
                event, start, length = item[2:]
                art = event.hdd_articulation
                self.hdd_stats['events'].append({
                    'deviceId': ident, 'sourceId': event.source_id, 'reinforcement': event.reinforcement,
                    'note': event.source_note, 'channel': event.source_channel, 'track': event.source_track,
                    'start': event.time, 'duration': length / self.RATE, 'articulation': art.kind,
                    'pitchBand': art.pitch_band, 'resonanceHz': art.resonance, 'decay': art.decay,
                    'raw': art.raw, 'choked': length < int(art.duration * self.RATE),
                })
            ordinary.extend(item for item in lane if item[4] > 0)
        return ordinary

    def _render_python(self, plan: list[tuple], n: int, mix_count: int) -> tuple:
        """Wersja bez zaleznosci: ~2-4 mln probek/s, wiec dlugi utwor trwa."""
        from playback.tray import tray_sound
        left = array('f', [0]) * n
        right = array('f', [0]) * n
        for d, profile, event, start, length in plan:
            gain = .12 * d.volume / max(1, mix_count)
            gl, gr = gain * (1 - max(0, d.pan)), gain * (1 + min(0, d.pan))
            for i in range(length):
                t = i / self.RATE
                if event.kind == 'tray':
                    sample = tray_sound(t, event.duration, event.velocity, profile, d.id, event.direction)
                elif event.kind == 'reversal':
                    sample = math.exp(-t * 85) * math.sin(2 * math.pi * 1700 * t)
                elif d.type == 'HDD_VCM' and event.kind == 'hit':
                    sample = sample_hdd(t, event.hdd_articulation, d.id)
                    sample *= min(1., (length - 1 - i) / max(1, int(.006 * self.RATE)))
                elif event.kind == 'hit':
                    resonance = 230 if d.type == 'HDD_VCM' else (profile.get('resonanceHz') or 440)
                    sample = math.exp(-t * 32) * (math.sin(2 * math.pi * resonance * t) + .25 * math.sin(2 * math.pi * resonance * 3 * t))
                    exponent = profile.get('velocityExponent') or .6
                    sample *= (event.velocity / 127) ** exponent
                elif event.kind == 'tone' and event.tonal_articulation is not None:
                    sample = render_tonal(t, event.tonal_articulation, event.hz, (length-1)/self.RATE)
                elif d.type == 'VHS':
                    sample = (math.sin(2 * math.pi * event.hz * t) + .2 * math.sin(2 * math.pi * event.hz * 3 * t)) * min(1, t * 40)
                else:
                    # Every audible cycle derives from a mechanical STEP impulse train.
                    rate = event.hz
                    pulse = math.exp(-((t * rate) % 1) * (14 if d.type == 'FDD' else 9))
                    resonance = 900 if d.type == 'FDD' else (1300 if d.type == 'DVD_SLED' else 600)
                    sample = pulse * (.55 + .45 * math.sin(2 * math.pi * resonance * t))
                left[start+i] += sample * gl; right[start+i] += sample * gr

        return left, right

    def _render_numpy(self, np, plan: list[tuple], n: int, mix_count: int) -> tuple:
        """Ta sama matematyka, wektorowo.

        Zmierzone (aranzacja 6 urzadzen): 5.7 s -> 0.20 s, a przy 40
        urzadzeniach 23.8 s -> 0.85 s. Zysk jest WYLACZNIE na pierwszym
        renderze po wczytaniu/edycji - kolejne `Play` korzysta z gotowego WAV.
        """
        left = np.zeros(n, dtype=np.float32)
        right = np.zeros(n, dtype=np.float32)
        for d, profile, event, start, length in plan:
            t = np.arange(length, dtype=np.float32) / self.RATE
            if event.kind == 'tray':
                from playback.tray import tray_sound
                sample = tray_sound(t, event.duration, event.velocity, profile, d.id, event.direction, np)
            elif event.kind == 'reversal':
                sample = np.exp(-t * 85) * np.sin(2 * np.pi * 1700 * t)
            elif d.type == 'HDD_VCM' and event.kind == 'hit':
                sample = sample_hdd(t, event.hdd_articulation, d.id, np)
                sample *= np.minimum(1., np.maximum(0., (length - 1 - np.arange(length)) / max(1, int(.006 * self.RATE))))
            elif event.kind == 'hit':
                resonance = 230 if d.type == 'HDD_VCM' else (profile.get('resonanceHz') or 440)
                sample = np.exp(-t * 32) * (np.sin(2 * np.pi * resonance * t) + .25 * np.sin(2 * np.pi * resonance * 3 * t))
                sample = sample * (event.velocity / 127) ** (profile.get('velocityExponent') or .6)
            elif event.kind == 'tone' and event.tonal_articulation is not None:
                sample = render_tonal(t, event.tonal_articulation, event.hz, (length-1)/self.RATE, np)
            elif d.type == 'VHS':
                sample = (np.sin(2 * np.pi * event.hz * t) + .2 * np.sin(2 * np.pi * event.hz * 3 * t)) * np.minimum(1, t * 40)
            else:
                rate = event.hz
                pulse = np.exp(-((t * rate) % 1) * (14 if d.type == 'FDD' else 9))
                resonance = 900 if d.type == 'FDD' else (1300 if d.type == 'DVD_SLED' else 600)
                sample = pulse * (.55 + .45 * np.sin(2 * np.pi * resonance * t))
            gain = .12 * d.volume / max(1, mix_count)
            gl, gr = gain * (1 - max(0, d.pan)), gain * (1 + min(0, d.pan))
            left[start:start+length] += sample * gl
            right[start:start+length] += sample * gr

        return left, right

    @staticmethod
    def _write(path: Path, left, right, n: int, np=None) -> None:
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(WavePreview.RATE)
            if np is not None:
                frames = np.empty(n * 2, dtype='<i2')
                frames[0::2] = (np.clip(left, -1, 1) * 32767).astype('<i2')
                frames[1::2] = (np.clip(right, -1, 1) * 32767).astype('<i2')
                wav.writeframes(frames.tobytes())
                return
            chunk = bytearray()
            for a, b in zip(left, right):
                chunk.extend(struct.pack('<hh', int(max(-1, min(1, a))*32767), int(max(-1, min(1, b))*32767)))
                if len(chunk) >= 65536:
                    wav.writeframes(chunk); chunk.clear()
            if chunk: wav.writeframes(chunk)

    def render(self, orchestra: VirtualOrchestra, duration: float):
        self.close()
        self.master_volume = orchestra.master_volume
        n = int((duration + .25) * self.RATE)
        # Dodatkowe ciche DVD nie obnizaja poziomu dotychczasowych FDD/VHS/HDD.
        mix_count = max(1, len([d for d in orchestra.devices
                                if d.mode in ('virtual', 'hybrid') and d.type not in ('DVD_SLED', 'DVD_TRAY')]))
        plan = self._plan(orchestra, n)
        # Exact audible intervals, including tails, chokes and suppressed extras.
        self.audio_events = [dataclasses.replace(row[2], duration=row[4] / self.RATE) for row in plan]

        try:
            import numpy as np
        except ImportError:
            np = None

        left, right = (self._render_numpy(np, plan, n, mix_count) if np is not None
                       else self._render_python(plan, n, mix_count))

        with tempfile.NamedTemporaryFile(prefix='virtual-orchestra-', suffix='.wav', delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self._write(path, left, right, n, np)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.path = path
