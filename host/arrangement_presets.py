"""Public preset catalog. IDs describe existing strategies, never select algorithms."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ArrangementPreset:
    id: str
    label: str
    descriptions: tuple[str, ...]
    ui_order: int


_FIXED_GATE = ('Eksperyment globalny FDD: każdy zachowany ton trwa 200 ms; '
               'gęstsze ataki są pomijane, aby zostawić 3 ms przerwy.')
_EXPRESSIVE_START = ('Cztery głosy w parach FDD1–2, 3–4, 5–6 i 7–8. '
                     'Długość nut wynika z rytmu i tempa. ')
_EXPRESSIVE_END = (' Nuty zachowują moment wejścia z MIDI. '
                   'Eksperyment wymaga odsłuchu REAL.')

# Keep the original backend validation order: offline baselines record it.
# ui_order retains the independently established Settings presentation order.
PRESETS = (
    ArrangementPreset('balanced', 'Balanced', (_FIXED_GATE,), 5),
    ArrangementPreset('fdd_quality', 'FDD Quality · eksperymentalny', (_FIXED_GATE,), 10),
    ArrangementPreset('dvd_lead_low_fdd', 'DVD Lead + Low FDD · eksperymentalny', (_FIXED_GATE,), 12),
    ArrangementPreset('fdd_quality_adaptive', 'FDD Quality Adaptive · eksperymentalny', (_FIXED_GATE,), 11),
    ArrangementPreset('instrument_roles', 'FDD Riffs + DVD Tło', (_FIXED_GATE,
        'FDD: krótkie nuty i zmiany wysokości. DVD: długie tło. PC Speaker: wokal, '
        'PC Speaker FX: ozdobniki. Perkusja bez zmian.'), 6),
    ArrangementPreset('instrument_roles_unison', 'FDD Riffs + DVD Tło · Pary Unisono', (_FIXED_GATE,
        'FDD1+2 i FDD3+4: dwie partie, każda grana wspólnie tą samą nutą. Pary '
        'utrzymują frazy i przejmują aktywne partie podczas pauz. DVD: długie tło.'), 7),
    ArrangementPreset('instrument_roles_duet', 'FDD Riffs + DVD Tło · Pary Dwugłos', (_FIXED_GATE,
        'FDD1+2 i FDD3+4: do dwóch różnych nut MIDI z jednej partii na parę. '
        'Pojedyncza linia: unisono. DVD: długie tło. Dwie niezależne partie FDD jednocześnie.'), 9),
    ArrangementPreset('instrument_roles_unison4', '2×4 FDD Unisono · eksperymentalny', (_FIXED_GATE,
        'FDD1–4 grają pierwszy głos, a FDD5–8 drugi. Każda grupa gra wewnętrznie '
        'tę samą nutę, start i długość. Grupy śledzą różne partie lub dwa głosy jednej '
        'partii. Universal rozdziela melodie, tło DVD i speakery; HDD preferują osobne role rytmiczne.'), 8),
    ArrangementPreset('fdd_expressive', 'FDD Expressive · 4 partie + akcenty', (
        _EXPRESSIVE_START+'Akcent dołącza drugą stację na krótszy czas.'+_EXPRESSIVE_END,), 1),
    ArrangementPreset('fdd_expressive_solo', 'FDD Expressive · bez kopii akcentów', (
        _EXPRESSIVE_START+'Porównanie A/B: identyczne główne nuty i pozostałe instrumenty '
        'jak w wersji z akcentami; usunięte tylko dodatkowe kopie akcentów.'+_EXPRESSIVE_END,), 2),
    ArrangementPreset('adaptive_legato', 'Adaptive Legato · ochrona rytmu', (
        'Lokalna ochrona krótkich, rytmicznych fraz i powtórzeń; płynne partie '
        'zachowują legato. Cztery stałe pary FDD1–2, 3–4, 5–6 i 7–8 grają '
        'wewnętrznie tę samą wysokość, start i długość nuty. Druga stacja dołącza '
        'także w spokojnych fragmentach, jeśli jest włączona, unisono jest dozwolone '
        'i pozwalają ograniczenia sprzętowe. Zbyt szybkie nuty nadal podlegają '
        'ograniczeniom FDD. DVD, speakery i HDD zachowują plan Expressive. '
        'Eksperymentalna heurystyka — wymaga odsłuchu REAL.',), 3),
    ArrangementPreset('fdd_legato', 'FDD Legato · ciągłe frazy', (
        'Ciągłe frazy na stałych FDD: zmiany wysokości bez STOP, łączenie powtórzeń '
        'i uproszczenie szybkich przebiegów. Mocne fragmenty wzmacnia druga stacja '
        'w każdej parze — do ośmiu FDD jednocześnie, z pełnym wybrzmieniem. DVD, '
        'speakery i HDD zachowują plan Expressive. Eksperyment do odsłuchu REAL; '
        'mniej źródłowych ataków i dłuższa ciągła praca napędów.',), 4),
    ArrangementPreset('universal', 'Universal · adaptacyjny', (_FIXED_GATE,
        'Lokalne frazy, wokal i ozdobniki; długie tło DVD. FDD uwzględnia odstęp '
        'ataków przed wyborem urządzenia.'), 0),
)
PRESET_IDS = tuple(preset.id for preset in PRESETS)


def is_preset(value):
    return isinstance(value, str) and value in PRESET_IDS
