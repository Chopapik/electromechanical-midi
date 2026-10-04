# Idle Device Reinforcement — software A/B

## Architektura i konfiguracja

Jedno wejście `apply_reinforcement` po normalnym allocatorze. Istniejący DVD sweep został przeniesiony i uogólniony na zgodne cele tonalne. W tym samym pass działają polityki uderzeń HDD i mechanicznych ruchów tray. Gdy enabled=false, adapter wykonuje dokładnie wcześniejszy DVD sweep i wcześniejszą selekcję tray (zgodność wsteczna, a nie dwa równocześnie aktywne systemy).

Pass jest celowo **po articulation PRIMARY**: rezerwuje rzeczywiste wykonawcze przedłużenia FDD. Nie zmienia articulation ani routing PRIMARY. Duble tonalne są kopiami już granej wysokości, bez nowego folding/transpozycji/harmonii. FDD używa preferowanego zakresu profilu. Nieznany zakres DVD zachowuje obecne możliwości profilu; bass z nieznanym zakresem jest odrzucany. VHS domyślnie wyłączony.

Zgodność: ten sam track daje duży bonus; semantyczna rola, GM instrument/family i powiązane STRINGS/PAD/BACKING pomagają. Rola OTHER nie jest traktowana jako dowód zgodności różnych znanych rodzin GM. Affinity urządzenia pochodzi z jego jawnego track albo najczęściej wykonywanej PRIMARY partii (czas ważony). Rodzina pochodzi z istniejącej klasyfikacji; program to dominujący program logical track, nie pełna rekonstrukcja zmian program_change dla każdej nuty.

Tacki wybierają mechaniczne Crash/Splash/Ride/sparse Open Hat w ramach wspólnego limitu kopii. Następnie wolny HDD może zdublować mocny (velocity ≥105) crash/splash/tom/kick/snare, z minimum score i 250 ms cooldown. Zamknięty hi-hat nie dostaje dubli HDD. Tray ma pierwszeństwo jako charakterystyczny mechanical accent; nie dodajemy równocześnie kopii HDD i tray przy domyślnym limicie 1.

Scoring tonalny: istniejące importance/priority + affinity + GM bonuses; penalty gęstego fragmentu i drugiej kopii. Niewłaściwa rola/zakres to reject. Mały bonus utrzymania kopii ogranicza churn. Duble <40 ms są usuwane; nie powstaje lawina krótkich kliknięć.

DEFAULT enabled=false — łatwy A/B oraz dokładna zgodność dotychczasowego brzmienia. Włączanie: ORCHESTRA → **Idle device reinforcement**. UI pokazuje max copies, reservation, minimum score i klasy urządzeń. JSON umożliwia też minDurationMs/cooldown/VHS. Gdy global mode jest aktywny, zastępuje legacy DVD mode; global OFF przywraca stary wybór DVD oraz trayEnabled.

```json
{
  "idleReinforcement": {
    "enabled": true,
    "maxCopiesPerEvent": 1,
    "lookAheadMs": 80.0,
    "deviceTypes": [
      "FDD",
      "DVD_SLED",
      "HDD_VCM",
      "DVD_TRAY"
    ],
    "minScore": 75.0,
    "minDurationMs": 40.0,
    "percussionCooldownMs": 250.0,
    "vhsEnabled": false
  }
}
```

Limit maxCopiesPerEvent=1 domyślnie; konfigurowalny 0–2. Dla tonów limit jest równoczesny (jedna PRIMARY nuta może dostać kolejne fragmenty kopii po różnych przerwach). Dla uderzeń limit dotyczy wszystkich dodatkowych ruchów tej samej źródłowej nuty. Druga tonalna kopia dostaje penalty. Średnia copies liczona z maksymalnej jednoczesnej liczby kopii per reinforced źródło; nie ze sztucznej liczby fragmentów.

Trace zawiera eventKind, sourceEventId/sourceDevice/targetDevice, reason, score, semanticCompatibility, rolę, GM. SOURCE VIEW i licznik MIDI nie zawierają kopii. DEVICE/SIMULATION VIEW ma przerywany obrys, inspector PRIMARY vs REINFORCEMENT z powodem i score. Virtual Orchestra pokazuje reinforcement events/time dla każdej klasy.

## Ochrona PRIMARY

- PRIMARY list jest immutable: benchmark porównuje pełne as_dict, nie tylko played/dropped.
- Rezerwacja kończy dopuszczalny dubel przed przyszłym PRIMARY o lookAheadMs (domyślnie 80 ms). Używa performedDuration i cyklu HDD.
- Dubel tonalny jest przycinany na granicy rezerwacji i końcu źródłowej nuty. Uderzenie HDD jest odrzucane, jeśli cały cykl nie mieści się przed rezerwacją.
- Busy/cooldown dotyczą dodatkowych uderzeń; PRIMARY nigdy nie jest przesuwany ani usuwany z ich powodu.
- Wszystkie duble tylko w preview; nie dodano żadnych komend firmware/serial.

## Zbiór i inwarianty

34 lokalne pliki, 20 unikalnych SHA-256. Cały dostępny zbiór, normalizacja identyczna. Brak Pink Floyd — Echoes; nie zastępujemy go innym MIDI i nie podajemy fikcyjnego wyniku.

| Metryka PRIMARY | BEFORE | AFTER |
|---|---:|---:|
| requested | 90878 | 90878 |
| played | 86823 | 86823 |
| dropped | 4055 | 4055 |
| drop rate | 4.4620% | 4.4620% |

Pełne przypisania, starty, durations, outcome i articulation PRIMARY identyczne. Sprawdzono brak kolizji z cyklami PRIMARY i max concurrent copies=1 w każdym utworze.

### Reinforcement całego zbioru

| Typ | BEFORE events | AFTER events | Średnie utilization BEFORE | AFTER | Δ pp |
|---|---:|---:|---:|---:|---:|
| FDD | 0 | 2816 | 60.825% | 63.862% | +3.038 |
| DVD_SLED | 8380 | 17113 | 32.153% | 43.965% | +11.812 |
| HDD_VCM | 0 | 1085 | 15.800% | 16.448% | +0.648 |
| DVD_TRAY | 545 | 545 | 1.255% | 1.255% | +0.000 |
| VHS | 0 | 0 | 48.850% | 48.850% | +0.000 |

Łącznie 8925→21559 reinforcement events. Średnie równoczesne copies per reinforced source: 1.000→1.000.

Utilization to suma PRIMARY mechanicznego czasu (HDD busy cycle) i czasu dodatkowych zdarzeń / PRIMARY długość utworu. W tabeli typów uśredniamy instancje; w A/B denominator jest identyczny. Czas resonance tail audio nie jest nową nutą.

### Wszystkie utwory

| MIDI | PRIMARY played/drop/rate (oba) | Reinforcement B→A | FDD/DVD/HDD/tray/VHS AFTER | Max simultaneous extras | Średnie copies AFTER |
|---|---|---|---|---:|---:|
| 0002-02-radiohead_1993-creep-[k] (2).mid | 4525/0/0.00% | 149→1891 | 363/1487/6/35/0 | 5 | 1.000 |
| 0031-12-radiohead_1995-street_spirit_(fade_out)-[k].mid | 3598/24/0.66% | 68→2679 | 593/2016/61/9/0 | 5 | 1.000 |
| 0032-01-radiohead_1997-airbag-[k].mid | 6446/870/11.89% | 126→1945 | 45/1894/0/6/0 | 4 | 1.000 |
| 0036-05-radiohead_1997-let_down-[k].mid | 6645/645/8.85% | 762→936 | 51/869/0/16/0 | 4 | 1.000 |
| 0041-10-radiohead_1997-no_surprises-[k] (2).mid | 5114/318/5.85% | 639→832 | 121/670/20/21/0 | 5 | 1.000 |
| 0054-02-radiohead_2001-pyramid_song.mid | 2503/0/0.00% | 381→94 | 2/75/0/17/0 | 2 | 1.000 |
| 0063-01-radiohead_2003-2+2=5-[k].mid | 6034/380/5.92% | 993→1333 | 24/1176/3/130/0 | 5 | 1.000 |
| 0071-09-radiohead_2003-there_there-[k] (2).mid | 8324/181/2.13% | 323→1393 | 118/1268/0/7/0 | 4 | 1.000 |
| 0080-02-radiohead_2007-bodysnatchers-[k] (2).mid | 9269/95/1.01% | 983→2158 | 14/2140/0/4/0 | 4 | 1.000 |
| 0081-03-radiohead_2007-nude.mid | 2757/62/2.20% | 250→430 | 53/360/6/11/0 | 3 | 1.000 |
| 0087-09-radiohead_2007-jigsaw_falling_into_place (2).mid | 7270/191/2.56% | 1435→1228 | 45/1173/0/10/0 | 4 | 1.000 |
| Mitski - Washing Machine Heart (cover) [MIDIfind.com].mid | 927/0/0.00% | 0→485 | 485/0/0/0/0 | 2 | 1.000 |
| PSX_Bios_zb.mid | 85/0/0.00% | 0→5 | 0/5/0/0/0 | 2 | 1.000 |
| Pink - Try [MIDIfind.com].mid | 6781/326/4.59% | 1021→1536 | 14/1500/0/22/0 | 3 | 1.000 |
| Pink_Floyd_-_Time.mid | 5816/328/5.34% | 598→1836 | 508/857/413/58/0 | 5 | 1.000 |
| Queen - Bohemian Rhapsody (2).mid | 5612/313/5.28% | 779→1548 | 9/956/475/108/0 | 5 | 1.000 |
| Radiohead — Sail to the Moon [MIDIfind.com] (1) (2).mid | 1955/2/0.10% | 219→589 | 125/456/0/8/0 | 3 | 1.000 |
| Stay_Shakespears_Sister.mid | 3035/320/9.54% | 199→633 | 238/211/101/83/0 | 4 | 1.000 |
| range-test.mid | 73/0/0.00% | 0→0 | 0/0/0/0/0 | 0 | 0.000 |
| test.mid | 54/0/0.00% | 0→8 | 8/0/0/0/0 | 1 | 1.000 |

### Utilization każdej instancji, cały zbiór

| Urządzenie | BEFORE % | AFTER % | Nadal idle s | Primary-idle reinforceable s | Niewykorzystany reinforceable s |
|---|---:|---:|---:|---:|---:|
| fdd-1 | 61.780 | 64.850 | 1546.013 | 321.433 | 186.529 |
| fdd-2 | 62.920 | 65.800 | 1504.253 | 404.506 | 278.036 |
| fdd-3 | 61.000 | 64.140 | 1577.488 | 450.031 | 312.313 |
| fdd-4 | 57.600 | 60.660 | 1730.377 | 511.171 | 376.820 |
| DVD_STEPPER_1 | 37.620 | 56.630 | 1907.461 | 1524.448 | 241.954 |
| DVD_STEPPER_2 | 33.880 | 47.410 | 2313.242 | 1749.790 | 749.011 |
| DVD_STEPPER_3 | 28.550 | 39.890 | 2643.819 | 1748.590 | 1053.670 |
| DVD_STEPPER_4 | 28.560 | 31.930 | 2993.793 | 1575.818 | 1219.012 |
| vhs-1 | 48.850 | 48.850 | 2249.631 | 0.000 | 0.000 |
| hdd_vcm-1 | 20.010 | 20.340 | 3503.916 | 14.805 | 0.525 |
| hdd_vcm-2 | 15.850 | 16.540 | 3671.076 | 31.588 | 1.348 |
| hdd_vcm-3 | 21.310 | 21.540 | 3450.996 | 23.492 | 13.307 |
| hdd_vcm-4 | 6.030 | 7.370 | 4074.171 | 108.944 | 49.724 |
| DVD_TRAY_1 | 1.270 | 1.270 | 4342.725 | 125.964 | 70.277 |
| DVD_TRAY_2 | 1.240 | 1.240 | 4343.887 | 125.964 | 71.440 |

### Per-utwór szczegółowy trace/statistics

Poniższe dane dla każdego MIDI zawierają wszystkie wymagane podziały: semantic role, GM family/instrument, rejection reasons oraz utilization każdej instancji BEFORE→AFTER.

#### 0002-02-radiohead_1993-creep-[k] (2).mid

- Semantic role: {"PERCUSSION": 41, "GUITAR": 1850}
- GM family: {"GM percussion": 41, "Guitar": 1850}
- GM instrument (program tonalny / note GM percussion): {"47": 2, "45": 2, "43": 1, "48": 1, "26": 613, "30": 1237, "49": 20, "57": 15}
- Rejections: {"deviceBusy": 31391, "deviceNeededSoon": 15857, "incompatibleRole": 13390, "outOfRange": 7749, "cooldown": 20, "maxCopiesReached": 7972, "scoreTooLow": 3844, "fragmentTooShort": 111}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 36.29 | 39.74 | 38.142 |
| fdd-2 | 28.32 | 32.94 | 47.382 |
| fdd-3 | 34.31 | 35.87 | 42.423 |
| fdd-4 | 35.75 | 35.75 | 0.000 |
| DVD_STEPPER_1 | 3.53 | 52.36 | 7.888 |
| DVD_STEPPER_2 | 3.16 | 12.32 | 99.157 |
| DVD_STEPPER_3 | 2.96 | 12.88 | 100.208 |
| DVD_STEPPER_4 | 3.23 | 6.02 | 113.058 |
| vhs-1 | 48.51 | 48.51 | 0.000 |
| hdd_vcm-1 | 15.59 | 15.68 | 0.000 |
| hdd_vcm-2 | 10.78 | 10.78 | 0.000 |
| hdd_vcm-3 | 30.42 | 30.51 | 0.630 |
| hdd_vcm-4 | 0.09 | 0.18 | 0.735 |
| DVD_TRAY_1 | 1.15 | 1.15 | 3.072 |
| DVD_TRAY_2 | 1.08 | 1.08 | 3.245 |

#### 0031-12-radiohead_1995-street_spirit_(fade_out)-[k].mid

- Semantic role: {"PERCUSSION": 70, "OTHER": 2609}
- GM family: {"GM percussion": 70, "Guitar": 2609}
- GM instrument (program tonalny / note GM percussion): {"38": 61, "26": 2609, "55": 4, "57": 4, "49": 1}
- Rejections: {"deviceBusy": 17459, "deviceNeededSoon": 5325, "incompatibleRole": 19510, "outOfRange": 4184, "cooldown": 0, "maxCopiesReached": 17474, "scoreTooLow": 5098, "fragmentTooShort": 873}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 27.81 | 27.81 | 0.000 |
| fdd-2 | 72.73 | 73.13 | 15.894 |
| fdd-3 | 56.58 | 74.97 | 19.380 |
| fdd-4 | 44.78 | 73.73 | 31.069 |
| DVD_STEPPER_1 | 7.52 | 65.16 | 81.896 |
| DVD_STEPPER_2 | 2.68 | 31.84 | 166.492 |
| DVD_STEPPER_3 | 3.57 | 21.92 | 190.450 |
| DVD_STEPPER_4 | 1.27 | 5.39 | 233.990 |
| vhs-1 | 70.95 | 70.95 | 0.000 |
| hdd_vcm-1 | 26.93 | 26.93 | 0.000 |
| hdd_vcm-2 | 10.48 | 10.48 | 0.000 |
| hdd_vcm-3 | 34.31 | 34.31 | 0.000 |
| hdd_vcm-4 | 1.24 | 3.75 | 0.000 |
| DVD_TRAY_1 | 0.33 | 0.33 | 0.058 |
| DVD_TRAY_2 | 0.27 | 0.27 | 0.204 |

#### 0032-01-radiohead_1997-airbag-[k].mid

- Semantic role: {"OTHER": 1939, "PERCUSSION": 6}
- GM family: {"Guitar": 1939, "GM percussion": 6}
- GM instrument (program tonalny / note GM percussion): {"30": 584, "27": 60, "26": 720, "29": 575, "49": 5, "57": 1}
- Rejections: {"deviceBusy": 36687, "deviceNeededSoon": 14384, "incompatibleRole": 21081, "outOfRange": 12363, "cooldown": 0, "maxCopiesReached": 11002, "scoreTooLow": 13343, "fragmentTooShort": 919}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 44.57 | 46.47 | 22.720 |
| fdd-2 | 43.62 | 43.62 | 24.496 |
| fdd-3 | 34.81 | 35.91 | 33.159 |
| fdd-4 | 34.97 | 34.97 | 30.414 |
| DVD_STEPPER_1 | 5.84 | 37.45 | 47.459 |
| DVD_STEPPER_2 | 4.47 | 36.60 | 55.469 |
| DVD_STEPPER_3 | 2.45 | 20.58 | 96.507 |
| DVD_STEPPER_4 | 3.22 | 12.00 | 121.875 |
| vhs-1 | 51.17 | 51.17 | 0.000 |
| hdd_vcm-1 | 29.26 | 29.26 | 0.105 |
| hdd_vcm-2 | 29.15 | 29.15 | 0.000 |
| hdd_vcm-3 | 24.67 | 24.67 | 0.000 |
| hdd_vcm-4 | 24.37 | 24.37 | 0.000 |
| DVD_TRAY_1 | 0.24 | 0.24 | 0.357 |
| DVD_TRAY_2 | 0.20 | 0.20 | 0.479 |

#### 0036-05-radiohead_1997-let_down-[k].mid

- Semantic role: {"GUITAR": 920, "PERCUSSION": 16}
- GM family: {"Guitar": 920, "GM percussion": 16}
- GM instrument (program tonalny / note GM percussion): {"27": 739, "25": 181, "57": 16}
- Rejections: {"deviceBusy": 141052, "deviceNeededSoon": 18953, "incompatibleRole": 2789, "outOfRange": 3980, "cooldown": 0, "maxCopiesReached": 4929, "scoreTooLow": 6063, "fragmentTooShort": 98}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 91.02 | 91.02 | 0.000 |
| fdd-2 | 88.37 | 91.89 | 2.164 |
| fdd-3 | 87.23 | 87.47 | 16.758 |
| fdd-4 | 80.60 | 80.96 | 33.396 |
| DVD_STEPPER_1 | 76.02 | 94.31 | 4.131 |
| DVD_STEPPER_2 | 70.41 | 89.61 | 17.553 |
| DVD_STEPPER_3 | 62.85 | 78.15 | 52.262 |
| DVD_STEPPER_4 | 65.31 | 73.31 | 64.795 |
| vhs-1 | 52.98 | 52.98 | 0.000 |
| hdd_vcm-1 | 23.39 | 23.39 | 0.000 |
| hdd_vcm-2 | 18.00 | 18.00 | 0.000 |
| hdd_vcm-3 | 21.68 | 21.68 | 0.000 |
| hdd_vcm-4 | 9.11 | 9.11 | 0.000 |
| DVD_TRAY_1 | 0.42 | 0.42 | 1.314 |
| DVD_TRAY_2 | 0.45 | 0.45 | 1.244 |

#### 0041-10-radiohead_1997-no_surprises-[k] (2).mid

- Semantic role: {"PERCUSSION": 41, "GUITAR": 791}
- GM family: {"GM percussion": 41, "Guitar": 791}
- GM instrument (program tonalny / note GM percussion): {"38": 13, "41": 7, "26": 305, "25": 486, "49": 21}
- Rejections: {"deviceBusy": 97407, "deviceNeededSoon": 18157, "incompatibleRole": 5051, "outOfRange": 3907, "cooldown": 2, "maxCopiesReached": 2320, "scoreTooLow": 2164, "fragmentTooShort": 150}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 74.39 | 75.45 | 16.974 |
| fdd-2 | 75.79 | 77.43 | 14.892 |
| fdd-3 | 75.37 | 76.94 | 12.770 |
| fdd-4 | 69.17 | 71.21 | 24.090 |
| DVD_STEPPER_1 | 64.40 | 84.40 | 3.563 |
| DVD_STEPPER_2 | 60.05 | 65.35 | 45.515 |
| DVD_STEPPER_3 | 58.89 | 61.54 | 54.039 |
| DVD_STEPPER_4 | 59.00 | 61.04 | 55.709 |
| vhs-1 | 62.60 | 62.60 | 0.000 |
| hdd_vcm-1 | 10.70 | 10.93 | 0.000 |
| hdd_vcm-2 | 11.17 | 11.45 | 0.000 |
| hdd_vcm-3 | 11.91 | 12.33 | 1.155 |
| hdd_vcm-4 | 0.79 | 0.79 | 2.100 |
| DVD_TRAY_1 | 1.04 | 1.04 | 2.129 |
| DVD_TRAY_2 | 0.95 | 0.95 | 2.342 |

#### 0054-02-radiohead_2001-pyramid_song.mid

- Semantic role: {"PAD_SYNTH": 75, "KEYS": 2, "PERCUSSION": 17}
- GM family: {"Ensemble": 69, "Strings": 6, "Piano": 2, "GM percussion": 17}
- GM instrument (program tonalny / note GM percussion): {"49": 86, "40": 6, "0": 2}
- Rejections: {"deviceBusy": 26667, "deviceNeededSoon": 2087, "incompatibleRole": 2476, "outOfRange": 9481, "cooldown": 0, "maxCopiesReached": 39, "scoreTooLow": 1746, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 89.68 | 89.68 | 0.000 |
| fdd-2 | 89.68 | 89.68 | 0.000 |
| fdd-3 | 89.68 | 89.76 | 0.000 |
| fdd-4 | 89.53 | 89.76 | 0.000 |
| DVD_STEPPER_1 | 81.96 | 60.03 | 0.000 |
| DVD_STEPPER_2 | 78.58 | 45.34 | 0.000 |
| DVD_STEPPER_3 | 34.33 | 34.60 | 7.331 |
| DVD_STEPPER_4 | 34.76 | 23.97 | 0.000 |
| vhs-1 | 56.78 | 56.78 | 0.000 |
| hdd_vcm-1 | 4.77 | 4.77 | 0.000 |
| hdd_vcm-2 | 6.64 | 6.64 | 0.000 |
| hdd_vcm-3 | 9.99 | 9.99 | 0.000 |
| hdd_vcm-4 | 0.45 | 0.45 | 0.000 |
| DVD_TRAY_1 | 0.49 | 0.49 | 1.244 |
| DVD_TRAY_2 | 0.44 | 0.44 | 1.359 |

#### 0063-01-radiohead_2003-2+2=5-[k].mid

- Semantic role: {"PERCUSSION": 133, "GUITAR": 1200}
- GM family: {"GM percussion": 133, "Guitar": 1200}
- GM instrument (program tonalny / note GM percussion): {"38": 3, "29": 813, "27": 199, "26": 188, "57": 130}
- Rejections: {"deviceBusy": 155893, "deviceNeededSoon": 32398, "incompatibleRole": 8896, "outOfRange": 3217, "cooldown": 0, "maxCopiesReached": 6229, "scoreTooLow": 4706, "fragmentTooShort": 247}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 65.11 | 65.24 | 24.995 |
| fdd-2 | 60.38 | 60.60 | 42.844 |
| fdd-3 | 66.42 | 66.75 | 22.789 |
| fdd-4 | 49.27 | 49.60 | 59.778 |
| DVD_STEPPER_1 | 44.57 | 82.90 | 3.774 |
| DVD_STEPPER_2 | 39.95 | 52.89 | 61.393 |
| DVD_STEPPER_3 | 37.80 | 45.42 | 73.533 |
| DVD_STEPPER_4 | 37.15 | 43.96 | 76.759 |
| vhs-1 | 62.68 | 62.68 | 0.000 |
| hdd_vcm-1 | 26.60 | 26.71 | 0.000 |
| hdd_vcm-2 | 25.31 | 25.37 | 0.000 |
| hdd_vcm-3 | 21.80 | 21.80 | 0.210 |
| hdd_vcm-4 | 13.77 | 13.77 | 0.315 |
| DVD_TRAY_1 | 3.86 | 3.86 | 7.263 |
| DVD_TRAY_2 | 3.86 | 3.86 | 7.263 |

#### 0071-09-radiohead_2003-there_there-[k] (2).mid

- Semantic role: {"OTHER": 1386, "PERCUSSION": 7}
- GM family: {"Guitar": 1386, "GM percussion": 7}
- GM instrument (program tonalny / note GM percussion): {"29": 1386, "49": 7}
- Rejections: {"deviceBusy": 74475, "deviceNeededSoon": 15716, "incompatibleRole": 9244, "outOfRange": 6582, "cooldown": 0, "maxCopiesReached": 5011, "scoreTooLow": 5377, "fragmentTooShort": 54}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 68.31 | 71.34 | 11.947 |
| fdd-2 | 67.45 | 69.39 | 13.164 |
| fdd-3 | 65.90 | 66.92 | 12.427 |
| fdd-4 | 66.21 | 66.92 | 15.286 |
| DVD_STEPPER_1 | 44.20 | 69.48 | 16.260 |
| DVD_STEPPER_2 | 39.15 | 49.53 | 79.214 |
| DVD_STEPPER_3 | 34.28 | 71.20 | 10.540 |
| DVD_STEPPER_4 | 33.63 | 43.65 | 99.277 |
| vhs-1 | 50.46 | 50.46 | 0.000 |
| hdd_vcm-1 | 43.96 | 43.96 | 0.000 |
| hdd_vcm-2 | 40.88 | 40.88 | 0.000 |
| hdd_vcm-3 | 42.61 | 42.61 | 0.000 |
| hdd_vcm-4 | 19.76 | 19.76 | 0.000 |
| DVD_TRAY_1 | 0.22 | 0.22 | 0.600 |
| DVD_TRAY_2 | 0.19 | 0.19 | 0.712 |

#### 0080-02-radiohead_2007-bodysnatchers-[k] (2).mid

- Semantic role: {"GUITAR": 2154, "PERCUSSION": 4}
- GM family: {"Guitar": 2154, "GM percussion": 4}
- GM instrument (program tonalny / note GM percussion): {"29": 1878, "26": 276, "49": 4}
- Rejections: {"deviceBusy": 120905, "deviceNeededSoon": 27624, "incompatibleRole": 4890, "outOfRange": 5674, "cooldown": 0, "maxCopiesReached": 5071, "scoreTooLow": 5621, "fragmentTooShort": 431}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 72.66 | 73.11 | 5.170 |
| fdd-2 | 72.99 | 73.05 | 8.105 |
| fdd-3 | 76.56 | 76.62 | 2.157 |
| fdd-4 | 73.13 | 73.26 | 4.457 |
| DVD_STEPPER_1 | 48.47 | 64.99 | 10.605 |
| DVD_STEPPER_2 | 42.45 | 65.76 | 9.645 |
| DVD_STEPPER_3 | 38.45 | 63.16 | 15.613 |
| DVD_STEPPER_4 | 37.17 | 51.31 | 42.713 |
| vhs-1 | 46.83 | 46.83 | 0.000 |
| hdd_vcm-1 | 27.21 | 27.21 | 0.000 |
| hdd_vcm-2 | 25.04 | 25.04 | 0.000 |
| hdd_vcm-3 | 20.48 | 20.48 | 0.000 |
| hdd_vcm-4 | 10.13 | 10.13 | 0.000 |
| DVD_TRAY_1 | 0.15 | 0.15 | 0.350 |
| DVD_TRAY_2 | 0.15 | 0.15 | 0.350 |

#### 0081-03-radiohead_2007-nude.mid

- Semantic role: {"PERCUSSION": 17, "GUITAR": 413}
- GM family: {"GM percussion": 17, "Guitar": 413}
- GM instrument (program tonalny / note GM percussion): {"45": 4, "43": 2, "25": 122, "26": 291, "49": 6, "57": 4, "59": 1}
- Rejections: {"deviceBusy": 38292, "deviceNeededSoon": 6427, "incompatibleRole": 3017, "outOfRange": 4421, "cooldown": 3, "maxCopiesReached": 3127, "scoreTooLow": 2339, "fragmentTooShort": 57}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 51.01 | 51.74 | 12.972 |
| fdd-2 | 46.69 | 47.71 | 14.890 |
| fdd-3 | 50.53 | 51.30 | 13.832 |
| fdd-4 | 42.14 | 43.59 | 22.428 |
| DVD_STEPPER_1 | 31.10 | 49.94 | 2.661 |
| DVD_STEPPER_2 | 29.86 | 49.25 | 4.964 |
| DVD_STEPPER_3 | 29.53 | 29.88 | 48.783 |
| DVD_STEPPER_4 | 29.20 | 28.61 | 50.651 |
| vhs-1 | 32.53 | 32.53 | 0.000 |
| hdd_vcm-1 | 11.79 | 11.93 | 0.000 |
| hdd_vcm-2 | 4.25 | 4.25 | 0.000 |
| hdd_vcm-3 | 20.12 | 20.21 | 0.420 |
| hdd_vcm-4 | 0.09 | 0.14 | 0.525 |
| DVD_TRAY_1 | 0.42 | 0.42 | 1.003 |
| DVD_TRAY_2 | 0.35 | 0.35 | 1.145 |

#### 0087-09-radiohead_2007-jigsaw_falling_into_place (2).mid

- Semantic role: {"OTHER": 1218, "PERCUSSION": 10}
- GM family: {"Guitar": 1218, "GM percussion": 10}
- GM instrument (program tonalny / note GM percussion): {"25": 1210, "28": 8, "49": 7, "55": 2, "57": 1}
- Rejections: {"deviceBusy": 164593, "deviceNeededSoon": 35739, "incompatibleRole": 7147, "outOfRange": 4912, "cooldown": 0, "maxCopiesReached": 4462, "scoreTooLow": 6329, "fragmentTooShort": 1}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 89.62 | 89.81 | 9.771 |
| fdd-2 | 85.80 | 86.45 | 17.301 |
| fdd-3 | 84.92 | 85.60 | 18.254 |
| fdd-4 | 85.64 | 86.01 | 18.458 |
| DVD_STEPPER_1 | 69.30 | 92.97 | 3.132 |
| DVD_STEPPER_2 | 65.02 | 91.35 | 7.948 |
| DVD_STEPPER_3 | 58.89 | 73.84 | 48.756 |
| DVD_STEPPER_4 | 60.86 | 66.27 | 65.277 |
| vhs-1 | 61.40 | 61.40 | 0.000 |
| hdd_vcm-1 | 29.50 | 29.50 | 0.000 |
| hdd_vcm-2 | 26.49 | 26.49 | 0.000 |
| hdd_vcm-3 | 29.55 | 29.55 | 0.000 |
| hdd_vcm-4 | 7.83 | 7.83 | 0.000 |
| DVD_TRAY_1 | 0.43 | 0.43 | 0.848 |
| DVD_TRAY_2 | 0.45 | 0.45 | 0.800 |

#### Mitski - Washing Machine Heart (cover) [MIDIfind.com].mid

- Semantic role: {"OTHER": 485}
- GM family: {"Guitar": 485}
- GM instrument (program tonalny / note GM percussion): {"25": 485}
- Rejections: {"deviceBusy": 3680, "deviceNeededSoon": 1818, "incompatibleRole": 5144, "outOfRange": 7250, "cooldown": 0, "maxCopiesReached": 465, "scoreTooLow": 1344, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 53.17 | 72.83 | 0.000 |
| fdd-2 | 50.04 | 69.75 | 8.930 |
| fdd-3 | 36.44 | 48.80 | 35.660 |
| fdd-4 | 29.76 | 37.96 | 45.015 |
| DVD_STEPPER_1 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_2 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_3 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_4 | 0.00 | 0.00 | 0.000 |
| vhs-1 | 57.05 | 57.05 | 0.000 |
| hdd_vcm-1 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-2 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-3 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-4 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_1 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_2 | 0.00 | 0.00 | 0.000 |

#### PSX_Bios_zb.mid

- Semantic role: {"OTHER": 5}
- GM family: {"Synth Lead": 4, "Synth Pad": 1}
- GM instrument (program tonalny / note GM percussion): {"81": 2, "87": 2, "88": 1}
- Rejections: {"deviceBusy": 172, "deviceNeededSoon": 18, "incompatibleRole": 655, "outOfRange": 144, "cooldown": 0, "maxCopiesReached": 173, "scoreTooLow": 40, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 31.88 | 31.88 | 0.000 |
| fdd-2 | 31.88 | 31.88 | 0.000 |
| fdd-3 | 4.74 | 4.74 | 0.000 |
| fdd-4 | 8.70 | 8.70 | 0.000 |
| DVD_STEPPER_1 | 0.00 | 40.58 | 0.000 |
| DVD_STEPPER_2 | 0.00 | 31.88 | 1.047 |
| DVD_STEPPER_3 | 0.00 | 0.00 | 4.884 |
| DVD_STEPPER_4 | 0.00 | 0.00 | 4.884 |
| vhs-1 | 54.85 | 54.85 | 0.000 |
| hdd_vcm-1 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-2 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-3 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-4 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_1 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_2 | 0.00 | 0.00 | 0.000 |

#### Pink - Try [MIDIfind.com].mid

- Semantic role: {"OTHER": 1514, "PERCUSSION": 22}
- GM family: {"Guitar": 1514, "GM percussion": 22}
- GM instrument (program tonalny / note GM percussion): {"30": 1514, "57": 11, "49": 11}
- Rejections: {"deviceBusy": 168647, "deviceNeededSoon": 15763, "incompatibleRole": 3916, "outOfRange": 5050, "cooldown": 0, "maxCopiesReached": 3474, "scoreTooLow": 3833, "fragmentTooShort": 4}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 94.27 | 94.47 | 5.454 |
| fdd-2 | 93.29 | 93.41 | 7.575 |
| fdd-3 | 93.28 | 93.62 | 7.032 |
| fdd-4 | 92.99 | 93.09 | 8.095 |
| DVD_STEPPER_1 | 81.12 | 91.52 | 1.091 |
| DVD_STEPPER_2 | 72.32 | 85.39 | 14.519 |
| DVD_STEPPER_3 | 63.27 | 80.14 | 25.103 |
| DVD_STEPPER_4 | 61.96 | 76.93 | 34.758 |
| vhs-1 | 53.75 | 53.75 | 0.000 |
| hdd_vcm-1 | 10.95 | 10.95 | 0.000 |
| hdd_vcm-2 | 9.49 | 9.49 | 0.000 |
| hdd_vcm-3 | 33.05 | 33.05 | 0.000 |
| hdd_vcm-4 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_1 | 0.90 | 0.90 | 0.000 |
| DVD_TRAY_2 | 0.90 | 0.90 | 0.000 |

#### Pink_Floyd_-_Time.mid

- Semantic role: {"PERCUSSION": 471, "KEYS": 1365}
- GM family: {"GM percussion": 471, "Piano": 1082, "Organ": 2, "Brass": 281}
- GM instrument (program tonalny / note GM percussion): {"48": 3, "47": 4, "36": 248, "38": 2, "40": 152, "43": 1, "45": 2, "50": 1, "2": 81, "17": 2, "61": 281, "0": 1001, "46": 58}
- Rejections: {"deviceBusy": 69174, "deviceNeededSoon": 19102, "incompatibleRole": 10716, "outOfRange": 7359, "cooldown": 61, "maxCopiesReached": 8155, "scoreTooLow": 7453, "fragmentTooShort": 401}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 30.77 | 39.83 | 7.987 |
| fdd-2 | 31.66 | 36.90 | 22.354 |
| fdd-3 | 29.76 | 33.74 | 30.326 |
| fdd-4 | 29.89 | 33.12 | 35.960 |
| DVD_STEPPER_1 | 13.97 | 30.00 | 54.659 |
| DVD_STEPPER_2 | 12.52 | 22.01 | 83.691 |
| DVD_STEPPER_3 | 12.10 | 17.74 | 99.014 |
| DVD_STEPPER_4 | 12.02 | 13.12 | 116.677 |
| vhs-1 | 42.21 | 42.21 | 0.000 |
| hdd_vcm-1 | 31.79 | 32.04 | 0.210 |
| hdd_vcm-2 | 20.23 | 21.87 | 0.000 |
| hdd_vcm-3 | 19.46 | 20.46 | 5.145 |
| hdd_vcm-4 | 3.38 | 11.95 | 11.359 |
| DVD_TRAY_1 | 2.06 | 2.06 | 10.310 |
| DVD_TRAY_2 | 2.06 | 2.06 | 10.316 |

#### Queen - Bohemian Rhapsody (2).mid

- Semantic role: {"PERCUSSION": 583, "OTHER": 965}
- GM family: {"GM percussion": 583, "Piano": 965}
- GM instrument (program tonalny / note GM percussion): {"35": 304, "45": 18, "43": 27, "40": 124, "41": 1, "49": 66, "0": 965, "46": 28, "57": 13, "55": 2}
- Rejections: {"deviceBusy": 97970, "deviceNeededSoon": 19439, "incompatibleRole": 21601, "outOfRange": 8232, "cooldown": 196, "maxCopiesReached": 4519, "scoreTooLow": 1509, "fragmentTooShort": 104}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 46.44 | 46.55 | 28.669 |
| fdd-2 | 46.34 | 46.43 | 30.252 |
| fdd-3 | 43.88 | 43.95 | 36.393 |
| fdd-4 | 44.46 | 44.49 | 37.396 |
| DVD_STEPPER_1 | 23.70 | 47.73 | 4.522 |
| DVD_STEPPER_2 | 20.95 | 30.44 | 59.786 |
| DVD_STEPPER_3 | 18.40 | 23.58 | 80.595 |
| DVD_STEPPER_4 | 19.07 | 19.55 | 94.241 |
| vhs-1 | 19.63 | 19.63 | 0.000 |
| hdd_vcm-1 | 12.80 | 16.38 | 0.210 |
| hdd_vcm-2 | 7.80 | 13.91 | 0.403 |
| hdd_vcm-3 | 14.01 | 15.27 | 2.807 |
| hdd_vcm-4 | 1.49 | 5.98 | 29.860 |
| DVD_TRAY_1 | 4.77 | 4.77 | 27.658 |
| DVD_TRAY_2 | 4.77 | 4.77 | 27.665 |

#### Radiohead — Sail to the Moon [MIDIfind.com] (1) (2).mid

- Semantic role: {"OTHER": 456, "KEYS": 125, "PERCUSSION": 8}
- GM family: {"Guitar": 456, "Piano": 125, "GM percussion": 8}
- GM instrument (program tonalny / note GM percussion): {"26": 456, "0": 125, "55": 6, "49": 2}
- Rejections: {"deviceBusy": 19903, "deviceNeededSoon": 1899, "incompatibleRole": 3536, "outOfRange": 10253, "cooldown": 2, "maxCopiesReached": 710, "scoreTooLow": 1393, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 86.99 | 95.64 | 0.465 |
| fdd-2 | 91.36 | 94.57 | 2.217 |
| fdd-3 | 83.31 | 92.32 | 5.938 |
| fdd-4 | 85.30 | 89.37 | 10.978 |
| DVD_STEPPER_1 | 34.58 | 18.30 | 0.000 |
| DVD_STEPPER_2 | 27.02 | 72.83 | 0.000 |
| DVD_STEPPER_3 | 24.79 | 34.31 | 103.127 |
| DVD_STEPPER_4 | 24.05 | 16.70 | 0.000 |
| vhs-1 | 15.64 | 15.64 | 0.000 |
| hdd_vcm-1 | 6.39 | 6.39 | 0.000 |
| hdd_vcm-2 | 2.17 | 2.17 | 0.000 |
| hdd_vcm-3 | 10.36 | 10.36 | 0.000 |
| hdd_vcm-4 | 0.08 | 0.08 | 0.000 |
| DVD_TRAY_1 | 0.27 | 0.27 | 0.342 |
| DVD_TRAY_2 | 0.27 | 0.27 | 0.342 |

#### Stay_Shakespears_Sister.mid

- Semantic role: {"PERCUSSION": 184, "OTHER": 449}
- GM family: {"GM percussion": 184, "Piano": 211, "Percussive": 38, "Guitar": 200}
- GM instrument (program tonalny / note GM percussion): {"36": 91, "40": 4, "48": 6, "2": 204, "113": 38, "29": 200, "4": 7, "57": 8, "49": 4, "46": 66, "55": 5}
- Rejections: {"deviceBusy": 18057, "deviceNeededSoon": 3078, "incompatibleRole": 11190, "outOfRange": 569, "cooldown": 14, "maxCopiesReached": 1063, "scoreTooLow": 2463, "fragmentTooShort": 1}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 48.26 | 51.91 | 1.263 |
| fdd-2 | 38.83 | 50.59 | 5.576 |
| fdd-3 | 44.08 | 48.81 | 3.015 |
| fdd-4 | 32.17 | 35.97 | 0.000 |
| DVD_STEPPER_1 | 15.88 | 31.01 | 0.313 |
| DVD_STEPPER_2 | 13.44 | 13.28 | 42.618 |
| DVD_STEPPER_3 | 12.71 | 12.84 | 42.925 |
| DVD_STEPPER_4 | 12.77 | 12.27 | 44.348 |
| vhs-1 | 57.26 | 57.26 | 0.000 |
| hdd_vcm-1 | 14.85 | 15.06 | 0.000 |
| hdd_vcm-2 | 12.97 | 14.45 | 0.945 |
| hdd_vcm-3 | 13.27 | 13.67 | 2.940 |
| hdd_vcm-4 | 6.64 | 8.95 | 4.830 |
| DVD_TRAY_1 | 4.28 | 4.28 | 13.729 |
| DVD_TRAY_2 | 4.18 | 4.18 | 13.974 |

#### range-test.mid

- Semantic role: {}
- GM family: {}
- GM instrument (program tonalny / note GM percussion): {}
- Rejections: {"deviceBusy": 0, "deviceNeededSoon": 0, "incompatibleRole": 584, "outOfRange": 0, "cooldown": 0, "maxCopiesReached": 0, "scoreTooLow": 0, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 0.00 | 0.00 | 0.000 |
| fdd-2 | 0.00 | 0.00 | 0.000 |
| fdd-3 | 0.00 | 0.00 | 0.000 |
| fdd-4 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_1 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_2 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_3 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_4 | 0.00 | 0.00 | 0.000 |
| vhs-1 | 100.00 | 100.00 | 0.000 |
| hdd_vcm-1 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-2 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-3 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-4 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_1 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_2 | 0.00 | 0.00 | 0.000 |

#### test.mid

- Semantic role: {"OTHER": 8}
- GM family: {"Unknown": 8}
- GM instrument (program tonalny / note GM percussion): {"None": 8}
- Rejections: {"deviceBusy": 234, "deviceNeededSoon": 12, "incompatibleRole": 245, "outOfRange": 0, "cooldown": 0, "maxCopiesReached": 0, "scoreTooLow": 324, "fragmentTooShort": 0}

| Urządzenie | BEFORE % | AFTER % | Niewykorzystany reinforceable s |
|---|---:|---:|---:|
| fdd-1 | 14.21 | 56.38 | 0.000 |
| fdd-2 | 56.86 | 56.86 | 0.000 |
| fdd-3 | 49.75 | 56.38 | 0.000 |
| fdd-4 | 49.75 | 56.38 | 0.000 |
| DVD_STEPPER_1 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_2 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_3 | 0.00 | 0.00 | 0.000 |
| DVD_STEPPER_4 | 0.00 | 0.00 | 0.000 |
| vhs-1 | 99.64 | 99.64 | 0.000 |
| hdd_vcm-1 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-2 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-3 | 0.00 | 0.00 | 0.000 |
| hdd_vcm-4 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_1 | 0.00 | 0.00 | 0.000 |
| DVD_TRAY_2 | 0.00 | 0.00 | 0.000 |

## Interpretacja odrzuceń i bezczynności

Rejections są liczbą **ocen candidate×target×interval**, a nie liczbą odrzuconych nut MIDI. To samo źródło może być oceniane wielokrotnie przy zmianach granic; nie należy dodawać ich do dropped PRIMARY. Kategorie wykluczają się na danej ocenie. Tray sampling jest raportowany pod scoreTooLow, mechaniczna zajętość pod cooldown.

idleButReinforceableSeconds to unia czasu, gdy urządzenie było PRIMARY-idle i istniał zgodny, score-qualified kandydat, przed ograniczeniem copy quota. unusedReinforceableSeconds to część tego czasu pozostawiona bez dodatkowego dźwięku. Jest to górna granica możliwości, nie sugestia maksymalizacji utilization. Dla HDD są to okna cykli mocnych akcentów; dla tray teoretycznie zgodne ruchy przed cooldown/sampling/quota, więc część możliwości jest celowo wyłączona.

Przyczyny dalszej ciszy: brak zgodnego kandydata, minScore, out of range, role mismatch, rezerwacja PRIMARY, limit jednej kopii, świadome pomijanie krótkich fragmentów, cooldown/sampling perkusji, wyłączony VHS. Nie sumujemy czasów różnych urządzeń jako długości utworu — są to device-seconds.

## Ocena muzyczna / kolejne kroki

Najbardziej korzystają DVD, potem FDD; HDD daje mniej, selektywnych mocnych akcentów. Tray zachowuje dotychczasową selekcję, bo już korzystał z wolnego czasu. VHS świadomie bez global kopii.

Największy wzrost dodatkowego czasu grania:
- 0031-12-radiohead_1995-street_spirit_(fade_out)-[k].mid: +406.167 device-seconds.
- 0071-09-radiohead_2003-there_there-[k] (2).mid: +283.257 device-seconds.
- 0032-01-radiohead_1997-airbag-[k].mid: +257.022 device-seconds.
- Pink_Floyd_-_Time.mid: +247.059 device-seconds.
- 0036-05-radiohead_1997-let_down-[k].mid: +190.859 device-seconds.

Najgęstsze miejsca: Queen / Stay osiągają maksymalnie 6 równoczesnych dodatkowych urządzeń, ale każde wzmacnia inne źródło; nigdy nie przekraczają jednej kopii tej samej nuty. Minimum 40 ms eliminuje krótkie fragmenty. Statystyki nie dowodzą subiektywnej jakości miksu — warto odsłuchać te fragmenty. W razie zbyt ciężkiego brzmienia można podnieść minScore/wyłączyć FDD lub HDD; nie zmieniamy PRIMARY allocatora.

Dalsze eksperymenty: octave reinforcement może pomóc dopiero po osobnym A/B i kalibracji zakresów. Harmonic reinforcement tworzyłby nową treść i wymagałby niezależnej oceny harmonii, więc jest najmniej uzasadnionym następnym krokiem. Timbre-aware routing ma sens po pomiarze rzeczywistych urządzeń. Żadnej z tych funkcji nie zaimplementowano.

## Testy i build

- 356 backend tests: OK, bez skipped. 16 testów nowego mechanizmu, także aktywacja przy wcześniej wyłączonym auto_arrange.
- 68 frontend tests: OK. Typecheck OK. Production build OK.
- npm run lint: Missing script: lint. Repo nadal nie ma skonfigurowanego lintera; git diff --check OK.
- scripts/benchmark.py i benchmark_dvd.py: cały zbiór unikalnych MIDI; exit 0. benchmark_dvd_reinforcement.py: 20 unique / 34 pliki, exit 0. Nowy benchmark_idle.py: wszystkie pełne PRIMARY A/B i cykle oraz limity kopii sprawdzone.
- Nie commitowano nowych zmian.
- Użytkownik jawnie zatwierdził samodzielne restarty. Aktywacja trybu przy auto_arrange=false dopięta i przetestowana. Standardowy scripts/dev.sh uruchomiony ponownie na 8000/5173. W przeglądarce potwierdzono zaznaczony Idle device reinforcement, parametry oraz zdarzenia reinforcement FDD/DVD/HDD/tray. Tryb działa w aplikacji.

## Zmienione pliki

| Plik | Uzasadnienie |
|---|---|
| `host/playback/reinforcement.py` | Jedno wejście passu, istniejący DVD sweep/zgodność wsteczna, scoring/compatibility/PRIMARY reservations/HDD/shared quotas/metrics. |
| `host/playback/allocator.py` | Wywołanie passu po immutable PRIMARY + articulation; metadata programów logicznych tracków. |
| `host/playback/orchestra.py` | Walidowana idleReinforcement konfiguracja, default OFF. |
| `host/playback/performance.py` | Metadata/trace dodatkowych eventów i raport globalny. |
| `host/playback/tray.py` | Adapter istniejącego GM busy/cooldown z shared quota/score/potential. |
| `host/playback/virtual.py` | Renderer gotowych hit/tone extras, config persisted, bez serial. |
| `host/playback/engine.py` | Config/import/export i osobne reinforcementNotes; źródła/trace w Arrangement. |
| `web/src/types.ts` | Typy config/trace/reinforcementNotes. |
| `web/src/components/VirtualOrchestra.tsx` | Global checkbox, klasy, copies/reservation/score, report extras wszystkich typów. |
| `web/src/components/ArrangementEditor.tsx` | PRIMARY/REINFORCEMENT inspector i wspólna lista additional notes w device/simulation. |
| `web/src/App.test.tsx` | UI toggle nie zmienia listy PRIMARY urządzeń. |
| `host/tests/test_idle_reinforcement.py` | A–M, invariants, family/range, short-window/lookahead, legacy, cooldown/sharedquota, exact source pitch, renderer/API. |
| `scripts/benchmark_idle.py` | Cały zbiór unique, twarde gates, typ/rola/GM/utilization/idle potential. |
| `benchmarks/idle-reinforcement.json` | Surowe wszystkie wyniki BEFORE/AFTER. |
| `benchmarks/idle-legacy-dvd-rerun.json` | Istniejący benchmark DVD po integracji. |
| `benchmarks/idle-auto-suite.txt` | Istniejący arranger benchmark log. |
| `benchmarks/idle-dvd-suite.json` | Istniejący historyczny DVD benchmark log. |
