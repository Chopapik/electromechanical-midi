"""Session-leased live tests through Player/Router; no separate transport."""
import math
from playback.hardware_profiles import HardwareNote, HardwareDeviceState, evaluate
from .compiler import ExecutionCommand


class Laboratory:
    interval = .1  # One batched update per 100 ms, never catch up missed samples.

    def __init__(self, registry, player):
        self.registry = registry
        self.player = player
        self.session = None
        self.lease = 0.
        self.history = {}
        self.jobs = {}
        player.laboratory = self

    def enter(self, session):
        with self.player.lock:
            if self.session and self.session != session:
                raise ValueError('Laboratorium jest używane przez inną przeglądarkę')
            self.player.select_owner('lab')
            self.session = session
            self.touch(session)

    def touch(self, session):
        if session == self.session:
            self.lease = self.player.clock() + 3

    def leave(self, session):
        with self.player.lock:
            if session == self.session:
                self.player.select_owner('orchestra')
                self.session = None

    def expire(self):
        with self.player.lock:
            if self.session and self.player.clock() > self.lease:
                try:
                    self.leave(self.session)
                except Exception:
                    # Player.stop retains its error/unknown state; expiry must
                    # not terminate the application's broadcast worker.
                    self.session = None

    def cancel(self):
        self.jobs.clear()

    def require_session(self, session):
        if session != self.session or self.player.owner != 'lab':
            raise ValueError('Wejdź do Laboratory w tej przeglądarce')

    @staticmethod
    def number(value, name, lo, hi):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(name + f': zakres {lo}–{hi}')
        return value

    def test(self, session, ident, hz, duration, modulation=None, *, update=False):
        with self.player.lock:
            self.require_session(session)
            previous = self.jobs.get(ident) if update else None
            if update and (previous is None or previous['kind'] == 'hit'):
                raise ValueError('Test urządzenia nie jest aktywny')
            if previous: duration = previous['duration']
            self.number(hz, 'Częstotliwość', .001, 20000)
            if duration is not None:
                self.number(duration, 'Czas testu (s)', .1, 3600)
            d = self.registry.by_id[ident]
            p = self.registry.profile(ident)
            if not d['enabled'] or p is None:
                raise ValueError('Urządzenie bez zatwierdzonego profilu')
            if (self.player.router.mode == 'REAL'
                    and not d.get('realEnabled', d['enabled'])):
                raise ValueError('Urządzenie dostępne tylko w VIRTUAL; REAL wymaga kwalifikacji')
            if ident in self.player.router.muted:
                raise ValueError('Urządzenie jest wyciszone — wyłącz Mute w Settings')
            modulation = modulation or {}
            if not isinstance(modulation, dict):
                raise ValueError('Nieprawidłowa modulacja')
            mode = modulation.get('mode', 'off')
            if mode not in ('off', 'sine', 'triangle'):
                raise ValueError('Nieznana modulacja częstotliwości')
            depth = self.number(modulation.get('depth', 0), 'Głębokość (Hz)', 0, 10000)
            period = self.number(modulation.get('period', 4), 'Okres modulacji (s)', 1, 60)
            kind = 'hit' if d['type'] == 'HDD_VCM' else 'tone'
            if kind == 'hit' and (duration is None or mode != 'off'):
                raise ValueError('HDD: tylko pojedyncze uderzenie bez modulacji')
            now = self.player.clock()
            history = self.history.setdefault(ident, HardwareDeviceState())
            ev = None
            for frequency in ([hz] if mode == 'off' else [hz-depth, hz, hz+depth]):
                ev = evaluate(p, HardwareNote(None if kind == 'hit' else frequency, duration or 1, now), history)
                if not ev.authorized or ev.ready_at > now:
                    raise ValueError('Profil nie dopuszcza testu: ' + ', '.join(ev.reasons))
            # A sweep must stay inside one authorized band, including its interior.
            bands = p.get('allowedBandsHz') if not p.get('continuousRotation') else None
            if kind == 'tone' and mode != 'off' and bands:
                ratio = p.get('pitchRatio') or 1
                if not any(lo*ratio <= hz-depth and hz+depth <= hi*ratio for lo, hi in bands):
                    raise ValueError('Modulacja przekracza przerwę między dozwolonymi pasmami')
            command = ExecutionCommand(0, ident, kind, .5, hz)
            self.player.router.ready([command])  # ATX, calibration, connection, capabilities.
            if kind == 'hit':
                duration = max(.1, ev.transition_time)
                history.hit_times.append(now)
                history.hit_times[:] = [t for t in history.hit_times if now-t <= (p.get('burstWindowMs') or 1000)/1000]
                history.ready_at = now + max(duration, (p.get('nominalStartToStartMs') or 0)/1000)
            if self.player.state != 'playing':
                self.player.epoch += 1
                self.player.origin = now
                self.player.error = None
                self.player.state = 'playing'
            self.jobs[ident] = dict(hz=hz, duration=duration, start=now,
                                    end=None if duration is None else now+duration,
                                    mode=mode, depth=depth, period=period, kind=kind,
                                    next=now, last=None, currentHz=hz)
            if previous:
                self.jobs[ident].update(start=previous['start'], end=previous['end'])
            self.touch(session)

    def stop_device(self, session, ident):
        with self.player.lock:
            self.require_session(session)
            if ident not in self.registry.by_id:
                raise ValueError('Nieznane urządzenie')
            # VIRTUAL cancellation is acknowledged; REAL uses existing STOP/error handling.
            self.jobs.pop(ident, None)
            try:
                self.player.router.output.stop_device(ident)
            except Exception:
                self.player.stop()
                raise
            if not self.jobs:
                self.player.stop()
            self.touch(session)

    def tick(self):
        now = self.player.clock()
        if not self.session:
            self.player.stop()
            return
        if now > self.lease:
            self.leave(self.session)
            return
        commands = []
        virtual = self.player.router.mode == 'VIRTUAL'
        if not virtual:
            real = self.player.router.real
            if not real.link or real.unknown:
                raise ValueError('Laboratorium: utracono BLE lub stan sprzętu jest nieznany')
            real.require_power()
        for ident, job in list(self.jobs.items()):
            if ident in self.player.router.muted or (job['end'] is not None and now >= job['end']):
                self.player.router.output.stop_device(ident)
                del self.jobs[ident]
                continue
            if now < job['next']:
                continue
            phase = (now-job['start']) / job['period']
            wave = math.sin(2*math.pi*phase) if job['mode'] == 'sine' else 1-4*abs((phase+.25) % 1-.5)
            hz = job['hz'] + (job['depth']*wave if job['mode'] != 'off' else 0)
            if job['kind'] == 'hit':
                send = job['last'] is None
            else:
                ev = evaluate(self.registry.profile(ident), HardwareNote(hz, .5, now))
                if not ev.authorized:
                    raise ValueError('Profil nie dopuszcza modulacji: ' + ', '.join(ev.reasons))
                send = virtual or job['last'] is None or abs(hz-job['last']) >= .05
            if send:
                remaining = .5 if job['end'] is None else min(.5, job['end']-now)
                commands.append(ExecutionCommand(now-self.player.origin+(.04 if virtual else 0), ident,
                                                 job['kind'], remaining, hz,
                                                 articulation={'kind':'laboratory', 'sustain':1}))
                job['last'] = hz
            job['currentHz'] = hz
            job['next'] = now + self.interval
        if commands:
            self.player.router.dispatch(commands, epoch=self.player.epoch,
                                        origin=self.player.origin, serverTime=now)
        if not self.jobs:
            self.player.stop()

    def snapshot(self):
        with self.player.lock:
            now = self.player.clock()
            return {'active': {ident: {k: j[k] for k in ('hz', 'currentHz', 'duration', 'mode', 'depth', 'period')} |
                              {'elapsed': max(0, now-j['start']), 'remaining': None if j['end'] is None else max(0, j['end']-now)}
                              for ident, j in self.jobs.items()}}
