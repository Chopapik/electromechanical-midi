#!/usr/bin/env python3
"""Benchmark Auto Arrangera: dynamiczna pula glosow vs statyczny routing.

Porownuje dwa tryby na TYM SAMYM pliku MIDI i TEJ SAMEJ orkiestrze:

  * ``static`` - dawny sposob: kazdy track przypiety do jednego urzadzenia.
    Nuta trafia na zajete urzadzenie => DROP, nawet gdy inne stoi puste.
  * ``auto``   - Auto Arranger: pule urzadzen, reassignment, micro-delay,
    arpeggiacja, voice steal.

Uruchomienie:
    .venv/bin/python scripts/benchmark.py [plik.mid ...]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

from midi_source import MidiSource  # noqa: E402
from playback import allocator, analysis  # noqa: E402
from playback.arrangement import Arrangement, midi_identity  # noqa: E402
from playback import duplicates  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402
from playback.virtual import VirtualOrchestra  # noqa: E402

DEFAULT_SONGS = ('midi/0087-09-radiohead_2007-jigsaw_falling_into_place.mid',)


def static_baseline(source: MidiSource, devices: list[dict]) -> dict:
    """Dawny routing: track -> jedno urzadzenie, bez ratowania nuty."""
    tonal = [d for d in devices if d['type'] in ('FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS')]
    percussive = [d for d in devices if d['type'] in ('HDD_VCM', 'SOLENOID_RESONATOR')]
    rules = []
    tonal_index = 0
    percussive_index = 0

    for track in source.tracks:
        if not track.note_count:
            continue

        if track.is_drums:
            if not percussive:
                continue

            target = percussive[percussive_index % len(percussive)]
        else:
            if not tonal:
                continue

            target = tonal[tonal_index % len(tonal)]
            tonal_index += 1

        percussive_index += 1 if track.is_drums else 0
        rules.append({'id': f'track-{track.index}', 'source': {'track': track.index},
                      'destination': {'deviceId': target['id']}, 'transform': {}})

    document = {'schemaVersion': 1, 'midi': midi_identity(source),
                'name': source.path.stem, 'devices': devices, 'rules': rules}
    arrangement = Arrangement.parse(document, source)
    routes, _ = arrangement.route(source)
    orchestra = VirtualOrchestra(arrangement.devices, 'static')
    orchestra.simulate(source, routes)

    counters = Counter()
    per_device = {}

    for device_id, report in orchestra.report.items():
        counters['played'] += report['played']
        counters['dropped'] += report['dropped']
        counters['folded'] += report['folded']
        counters['delayed'] += report['delayed']
        per_device[device_id] = report['activeTime']

    counters['requested'] = sum(counters[key] for key in ('played', 'dropped'))

    return {'counters': counters, 'activity': per_device}


def lead_metrics(plan) -> dict:
    """Ile z wykrytego leadu przezylo i czy VHS jest czysty."""
    lead = [event for event in plan.events if event.role == 'lead']
    played = [event for event in lead if event.played]
    vhs = [event for event in plan.events if event.device_id == 'vhs-1']
    report = plan.report()
    device = next((item for item in report['devices'] if item['deviceId'] == 'vhs-1'), None)

    return {
        'requested': len(lead),
        'played': len(played),
        'dropped': len(lead) - len(played),
        'delayed': len([e for e in lead if e.outcome in ('DELAYED', 'ARPEGGIATED')]),
        'preservation': len(played) / len(lead) if lead else 1.0,
        'vhsNotes': len(vhs),
        'vhsUtilization': device['utilization'] if device else 0.0,
        'nonLeadOnVhs': len([e for e in vhs if e.role != 'lead']),
    }


def describe(label: str, source: MidiSource, devices: list[dict], auto: bool) -> dict:
    if auto:
        plan = allocator.allocate(source, default_orchestra())
        report = plan.report()
        totals = report['totals']
        activity = {item['deviceId']: item['activeTime'] for item in report['devices']}
        result = {
            'requested': totals['requested'], 'played': totals['played'],
            'dropped': totals['dropped'], 'dropRate': totals['dropRate'],
            'reassigned': totals['reassigned'], 'delayed': totals['delayed'],
            'arpeggiated': totals['arpeggiated'], 'stolen': totals['voiceSteals'],
            'shortened': totals['shortened'], 'folded': totals['folded'],
            'meanDelayMs': totals['meanDelayMs'], 'maxDelayMs': totals['maxDelayMs'],
            'duration': report['duration'],
            'devices': report['devices'],
            'activity': activity,
            'tonal': report['tonal'], 'percussion': report['percussion'],
            'lead': lead_metrics(plan),
        }
    else:
        baseline = static_baseline(source, devices)
        counters = baseline['counters']
        requested = counters['requested'] or 1
        result = {
            'requested': counters['requested'], 'played': counters['played'],
            'dropped': counters['dropped'], 'dropRate': counters['dropped'] / requested,
            'reassigned': 0, 'delayed': counters['delayed'], 'arpeggiated': 0,
            'stolen': 0, 'shortened': 0, 'folded': counters['folded'],
            'meanDelayMs': 0.0, 'maxDelayMs': 0.0, 'duration': 0.0,
            'devices': [], 'activity': baseline['activity'],
            'tonal': None, 'percussion': None,
        }

    print(f'  {label}')
    print(f'    requested   {result["requested"]:6d}')
    print(f'    played      {result["played"]:6d}')
    print(f'    dropped     {result["dropped"]:6d}   (drop rate {result["dropRate"] * 100:5.1f}%)')
    print(f'    reassigned  {result["reassigned"]:6d}   <- uratowane innym wolnym urzadzeniem')
    print(f'    delayed     {result["delayed"]:6d}   (mean {result["meanDelayMs"]:.1f} ms, max {result["maxDelayMs"]:.1f} ms)')
    print(f'    arpeggiated {result["arpeggiated"]:6d}')
    print(f'    voice steals{result["stolen"]:6d}   (shortened {result["shortened"]})')
    print(f'    folded      {result["folded"]:6d}')

    if 'lead' in result:
        lead = result['lead']
        print(f'    LEAD: requested {lead["requested"]}, played {lead["played"]}, '
              f'dropped {lead["dropped"]}, delayed {lead["delayed"]}, '
              f'preservation {lead["preservation"] * 100:.1f}%')
        print(f'    VHS: notes {lead["vhsNotes"]}, utilization {lead["vhsUtilization"]:.2f}, '
              f'non-lead events on VHS {lead["nonLeadOnVhs"]}')

    if result['devices']:
        print('    per device:')

        for item in result['devices']:
            print(f'      {item["deviceId"]:12s} {item["type"]:8s} notes={item["notes"]:5d} '
                  f'active={item["activeTime"]:6.1f}s util={item["utilization"]:.2f}')

    return result


def duplicate_comparison(source: MidiSource) -> None:
    """Przed/po sklejeniu double-trackingu - ten sam plik, ta sama orkiestra."""
    report = duplicates.detect(source)
    normalized = duplicates.normalize(source, report)
    print('  DUPLICATE DETECTION')

    if not report.groups:
        print('    brak grup - plik nie ma zdublowanych partii')
    else:
        print(f'    groupsFound {len(report.groups)}, tracksCollapsed {report.collapsed_tracks}, '
              f'events {report.raw_tonal_events} -> {report.logical_tonal_events} '
              f'(-{report.events_removed})')
        for group in report.groups:
            names = ' + '.join(group.names[index] for index in group.tracks)
            print(f'      {names}')
            print(f'        confidence {group.confidence:.3f}  primary track {group.primary}')
            for track in group.duplicates:
                similarity = next((pair for pair in report.pairs
                                   if {pair.track_a, pair.track_b} == {group.primary, track}), None)
                detail = (f'pitch {similarity.pitch_agreement:.3f} '
                          f'timing-mad {similarity.offset_mad_s * 1000:.2f} ms' if similarity else '')
                print(f'        + track {track} {group.names[track]}: '
                      f'offset {group.median_offsets[track] * 1000:+.2f} ms '
                      f'[{group.verdicts[track]}] {detail}')

    before = allocator.allocate(source, default_orchestra())
    after = allocator.allocate(normalized, default_orchestra())
    report_before, report_after = before.report(), after.report()

    kpi = report_after['duplicates']
    print()
    print(f'    {"metric":28s} {"before":>12s} {"after":>12s}')
    rows = [
        ('tonal requested', report_before['tonal']['requested'], report_after['tonal']['requested']),
        ('accompaniment demand [s]',
         kpi.get('accompanimentDemandSecondsBefore'), kpi.get('accompanimentDemandSecondsAfter')),
        ('demand / accompaniment capacity', kpi.get('demandCapacityBefore'), kpi.get('demandCapacityAfter')),
        ('played', report_before['totals']['played'], report_after['totals']['played']),
        ('dropped', report_before['totals']['dropped'], report_after['totals']['dropped']),
        ('drop rate', round(report_before['totals']['dropRate'], 3),
         round(report_after['totals']['dropRate'], 3)),
        ('shortened', report_before['totals']['shortened'], report_after['totals']['shortened']),
        ('voice steals', report_before['totals']['voiceSteals'], report_after['totals']['voiceSteals']),
        ('delayed + arpeggiated',
         report_before['totals']['delayed'] + report_before['totals']['arpeggiated'],
         report_after['totals']['delayed'] + report_after['totals']['arpeggiated']),
        ('silent gap count', report_before['continuity']['silentGapCount'],
         report_after['continuity']['silentGapCount']),
        ('orchestra silent [s]', report_before['continuity']['orchestraSilentTime'],
         report_after['continuity']['orchestraSilentTime']),
        ('max silent gap [ms]', report_before['continuity']['maxSilentGapMs'],
         report_after['continuity']['maxSilentGapMs']),
        ('planned coverage', report_before['continuity']['plannedCoverage'],
         report_after['continuity']['plannedCoverage']),
    ]

    for label, left, right in rows:
        print(f'    {label:28s} {str(left):>12s} {str(right):>12s}')
    print()


def articulation_comparison(source: MidiSource) -> None:
    """Przed/po mechanicznej artykulacji FDD - ten sam plan, inna dlugosc NOTE_OFF."""
    from playback.orchestra import BALANCED
    from playback import allocator

    normalized = duplicates.normalize(source)
    base = default_orchestra()
    off = allocator.allocate(normalized, type(base)(
        devices=base.devices, policy={**BALANCED, 'mechanicalSustain': False}))
    on = allocator.allocate(normalized, base)
    before, after = off.report(), on.report()
    stats = on.articulation

    print('  FDD MECHANICAL SUSTAIN')
    print(f'    params: preferred {stats["params"]["preferredMechanicalSustainMs"]} ms, '
          f'release {stats["params"]["releaseGapMs"]} ms, '
          f'max extension {stats["params"]["maxSustainExtensionMs"]} ms')
    print(f'    notes extended {stats["extended"]}, mean +{stats["meanExtensionMs"]} ms, '
          f'max +{stats["maxExtensionMs"]} ms, added {stats["addedSeconds"]} s')

    rows = [
        ('played', before['totals']['played'], after['totals']['played']),
        ('dropped', before['totals']['dropped'], after['totals']['dropped']),
        ('source tonal coverage', before['continuity']['plannedCoverage'],
         after['continuity']['plannedCoverage']),
        ('long gaps >150 ms', before['continuity']['longGapCount'],
         after['continuity']['longGapCount']),
        ('silent gap count', before['continuity']['silentGapCount'],
         after['continuity']['silentGapCount']),
        ('median gap [ms]', before['continuity']['medianSilentGapMs'],
         after['continuity']['medianSilentGapMs']),
        ('total silence [s]', before['continuity']['orchestraSilentTime'],
         after['continuity']['orchestraSilentTime']),
        ('accompaniment continuity', before['continuity']['accompanimentContinuity'],
         after['continuity']['accompanimentContinuity']),
        ('FDD coverage', before['continuity']['fddCoverage'],
         after['continuity']['fddCoverage']),
        ('FDD utilization',
         round(sum(d['utilization'] for d in before['devices'] if d['type'] == 'FDD'), 3),
         round(sum(d['utilization'] for d in after['devices'] if d['type'] == 'FDD'), 3)),
        ('mean performed [ms]',
         round(sum(e.actual_duration for e in off.events if e.device_type == 'FDD')
               / max(1, len([e for e in off.events if e.device_type == 'FDD'])) * 1000, 1),
         round(sum(e.actual_duration for e in on.events if e.device_type == 'FDD')
               / max(1, len([e for e in on.events if e.device_type == 'FDD'])) * 1000, 1)),
    ]
    print()
    print(f'    {"metric":26s} {"before":>12s} {"after":>12s}')
    for label, left, right in rows:
        print(f'    {label:26s} {str(left):>12s} {str(right):>12s}')
    print()


def main(argv: list[str]) -> int:
    songs = argv[1:] or list(DEFAULT_SONGS)

    for song in songs:
        path = Path(song)

        if not path.is_file():
            print(f'pominieto (brak pliku): {song}')
            continue

        source = MidiSource(path)
        orchestra = default_orchestra()
        profile = analysis.analyze(source)

        print('=' * 72)
        print(f'{path.name}')
        print('=' * 72)
        print(f'  orkiestra   {len(orchestra.devices)} urzadzen: '
              f'{", ".join(f"{d['type']}({d['id']})" for d in orchestra.devices)}')
        print(f'  nut w pliku {sum(t.note_count for t in source.tracks)}')
        lead = source.tracks[profile.lead_track].name if profile.lead_track is not None else '-'
        bass = source.tracks[profile.bass_track].name if profile.bass_track is not None else '-'
        print(f'  wykryty lead track {profile.lead_track} ({lead}), '
              f'bas track {profile.bass_track} ({bass})')
        print(f'  role: {dict(Counter(profile.roles.values()))}')
        print()

        duplicate_comparison(source)
        articulation_comparison(source)

        before = describe('STATIC (dawny routing)', source, orchestra.devices, auto=False)
        print()
        after = describe('AUTO (pula glosow)', source, orchestra.devices, auto=True)
        print()

        rescued = after['played'] - before['played']
        print(f'  => wiecej zagranych nut: {rescued:+d} '
              f'({after["played"] / max(1, before["played"]) * 100 - 100:+.1f}%)')
        print(f'  => drop rate {before["dropRate"] * 100:.1f}% -> {after["dropRate"] * 100:.1f}%')
        print()

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
