# FDD octave-down listening experiment

All four configured FDD devices now use `transpose: -12` and a preferred
folding window of 100–205 Hz (previously 200–410 Hz). Shifting both the input
and its folding window prevents octave folding from undoing the transposition.
For example, a previously performed C4 at 261.626 Hz becomes C3 at 130.813 Hz.
Source MIDI notes remain unchanged. The setting applies to all arrangement
presets, paired voices, optional FDD reinforcement and STRICT TRACKS.

The hardware profile's temporary allowed musical window is 100–410 Hz, so
the prior calibrated upper endpoint and explicit lab/calibration tones remain
available. Arrangement candidates intersect this physical profile with the
device's narrower preferred 100–205 Hz window. Pair revoicing and adaptive
recovery use that same intersection. Strict routing now honors device transpose.

The 100 Hz musical lower bound is a user-requested experiment, not a newly
measured mechanical minimum. Measured stable bands, the 410 Hz upper endpoint,
2439 us execution step limit, 72-step travel and reversal settings are retained.
The common minimum 120 ms between FDD attacks remains active. Firmware and
the transpose settings of DVD, speakers and percussion are unchanged.

Tests cover the halved folding result across MIDI pitches 24–108 in all fold
modes, all presets, strict routing, unison copies, expression frequencies and
complete FDD physical chronologies. Both outputs consume the same timeline.

To end the listening experiment, set the four FDD transposes back to zero and
remove their preferred-range overrides (restoring the default 200–410 Hz
window). The previous musical-profile lower bound was 200 Hz and can likewise
be restored; it was a working musical setting rather than a measured minimum.
