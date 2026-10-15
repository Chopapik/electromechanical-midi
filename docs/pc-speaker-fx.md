# Vocal PC Speaker and independent FX speaker

Main PC Speaker remains GPIO 25 (`VHS`). PC Speaker FX uses GPIO 26 (`VHS2`),
LEDC channel 2; channel 0 is the primary speaker. Channels 0 and 1 share a
frequency timer in this Arduino ESP32 runtime, so FX deliberately uses channel 2.
Connect GPIO 26 to the second speaker driver's signal input and share ground.
A passive low-impedance speaker requires a suitable driver; do not connect it
directly across GPIO and ground. This output expects a passive tone transducer
or amplified input, not an active buzzer with its own oscillator.

The app includes updated ESP32 firmware, but the controller must be flashed via
the existing firmware screen before using FX in REAL. Capability `speaker_fx=1`
and a `STATUS VHS2` record identify support. Old firmware can still play plans
without FX; a plan requiring FX is refused with an update message. No automatic
flash is performed. Main output keeps AMP 50; both virtual speakers keep the
quiet square waveform and device volume controls. Existing VHS wire commands
remain compatible.

Independent commands: `VHS2 ENABLE 1`, `VHS2 AMP 50`, `VHS2 FREQ 830.61`,
`VHS2 STOP`. Both channels stop on ALL STOP, watchdog, disable and mode change.
Strict Tracks prohibits tone commands on the FX channel, just as on the main.

Strong lyric alignment (>=85%), >=20 notes, near-monophony, <=15% overlap,
melodic steps and a vocal register add evidence to semantic vocal detection.
Bass and named backing voices are excluded from this extra evidence. The
existing high-confidence selection and margin remain required.

FX allocation requires a separate available speaker and a semantic/manual lead.
A non-vocal, non-bass, high monophonic Pipe/Synth Effects/Synth Lead track with
>=8 notes, mean pitch 76..96 and density <=3 notes/s qualifies. It retains MIDI
onsets and pitch and uses a dedicated monophonic reservation. Without a confident
lead, ordinary heuristic routing remains. DVD Lead + Low FDD retains its existing
main-voice preference; FX is separately available. Strict Tracks uses only FDD.

Counting Stars supplied MIDI: lead channel 4 is recognized through lyrics; FX
channel 8 plays 830.61, 987.77, 830.61, 739.99 Hz near 34.5..36.5 seconds.
See reports/counting-stars-speakers.json for allocation results. Local MIDI is
copied into the library but stays ignored by Git.

## Shared pulse shape and volume settings

Settings contains one shared PWM duty control per speaker, used by REAL and
VIRTUAL, plus independent VIRTUAL gain. REAL volume and pulse width were always
the same LEDC PWM duty parameter; the former REAL volume slider is now labelled
accurately as pulse width, rather than presenting two independent controls.
Range 0..128 corresponds to 0..50% duty; 50% is square, narrow pulses sound
brighter, 0% is silence. Duties above 50% mirror the pulse spectrum. Existing
AMP 50 remains 19.53125% duty, with no firmware or command changes.

Web Audio uses an AC Fourier pulse series with 64 harmonics and the same
`realAmplitude/256` duty as LEDC. It is band-limited by Web Audio; this does not
claim measured identical speaker response. Existing voices change pulse shape
without changing pitch, onset or the performance plan. Volume and zero-duty
silence use a short mix ramp. Each speaker includes a waveform preview.
REAL updates AMP on active speakers and otherwise applies it on the next note,
without starting idle output. Existing MIDI envelopes remain in VIRTUAL.

Settings are saved atomically in the `speaker-settings` Docker volume at
`/app/settings/speaker-volumes.json`, independently of the built application.
They survive container rebuilds and restarts. Native runtime may override the
path with ORCHESTRA_SPEAKER_SETTINGS. No additional firmware change is required
for pulse adjustment; the second speaker still requires FX-capable firmware.

The VIRTUAL UI gain range remains 0..100%, mapped to gain 0..2.5: new 100%
is old 250%, old 100% is new 40%. Existing stored gains are unchanged, so the
update preserves current loudness and only rescales slider positions. Only
PC Speakers accept the expanded gain range.

## Sine, triangle and sawtooth with S8050 speaker drivers

Each speaker has a persisted shared waveform choice: pulse, sine, triangle,
sawtooth. Web Audio uses native oscillators for the latter three and the pulse
Fourier series for pulse. REAL uses 40 kHz LEDC PWM amplitude modulation, sampled
by an ESP Timer task every 50 us (20 kHz), through the existing S8050 switch.
This is a modulated PWM signal, not an analog sine directly on the GPIO. Speaker
response and carrier filtering determine the resulting acoustic waveform; they
require physical verification. No analog base-drive assumption is made.

The oscillator integrates elapsed microseconds, skips contended/late samples
and never produces catch-up bursts. Audio callbacks do not access SPI or motor
state. A shared speaker mutex serializes STOP and sample writes, preventing an
old sample from restoring output after STOP. Boot, disable, ALL STOP and watchdog
set both outputs to zero. Ordinary pulse mode keeps the original LEDC tone path.
The new shapes preserve the configured mean PWM duty with samples clamped to
0..255, without claiming equal measured current or thermal safety.

New firmware advertises speaker_waves=1. Old firmware still supports pulse, but
REAL playback of other shapes is refused with an update message. Selecting a
shape in VIRTUAL works without hardware; selection remains shared when changing
to REAL. No automatic flashing is performed. Configuration avoids waveform
commands on disabled/Strict Tracks speaker channels.
