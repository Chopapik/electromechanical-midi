# Hardware-first: profile i wykonanie

## Aktualna ścieżka

`MidiSource → runtime.arranger → allocator.allocate → hardware_arranger →
PerformancePlan → runtime.compiler → ExecutionTimeline → Player → Router`.
REAL i VIRTUAL korzystają z tej samej fizycznej alokacji i harmonogramu;
połączenie BLE nie zmienia dostępnej polifonii w planie. Brak połączenia blokuje
REAL Play, a nie import MIDI. Dawny renderer PCM i wybór real/hybrid per-device
nie są ścieżką obecnej aplikacji.

[README](../README.md) zawiera skład, presety i uruchamianie;
[ESP32](esp32-orchestra.md) jest źródłem opisu połączeń, zasilania i komend.
Historyczne szczegóły migracji zachowuje
[raport wdrożenia](hardware-first-implementation-report.md).

## Źródła danych i inventory

- `config/devices.json`: stabilne ID, kolejność/lane, enabled, typ, profil muzyczny,
  transpozycja, preferencje i polityka. Lista obejmuje cztery FDD, cztery DVD,
  dwa PC Speakery, cztery HDD oraz dwie wyłączone tacki.
- `config/hardware-profiles/theoretical.json`: priory i przykłady referencyjne.
- `config/hardware-profiles/instances.json`: kalibracje oraz konfiguracja instancji.
- `firmware/controller/include/hardware_profiles_generated.h`: generowane domyślne
  parametry wykonawcze ESP32, nie oddzielny ręcznie edytowany profil.

`runtime.registry.PlanningProfiles.present()` korzysta z zadeklarowanego
`enabled` w registry. STATUS nie wykrywa fizycznie podłączonego silnika.
`DeviceRegistry.profile()` scala profil teorii i dane instancji. Zachowane API
planowania obsługuje też jawne hardware overrides; aktualny UI nie jest edytorem
inventory/kalibracji. Mute z UI jest bramką Routera, nie zmianą profilu lub pojemności.
Nie zmieniaj kolejności urządzeń w sposób przenumerowujący fizyczne lanes.

Sprawdzenie nagłówka bez modyfikacji:

```sh
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Regeneracja po zamierzonej zmianie profili: to samo polecenie bez `--check`.
Po zmianie kodu/config przebuduj obraz; aktualizacja firmware na kontrolerze
wymaga osobnego jawnego uploadu USB. Sama dokumentacja nie zmienia profili.

## Dowody i niepewność

Każda ilość może zawierać `value`, `unit`, `source`, `evidenceType`, `confidence`
i `uncertainty`. FACT oznacza fakt o wskazanym źródle lub kodzie, DERIVED wynik
obliczeń, HYPOTHESIS założenie, MEASURED pomiar określonej instancji/warunków.
FACT z katalogu Minebea nie identyfikuje silnika z odzyskanego DVD. Wartość
zapisana jako MEASURED nadal wymaga przeczytania źródła i warunków pomiaru.
Confidence: HIGH/MEDIUM/LOW/UNKNOWN; null nie oznacza bezpiecznego braku limitu.
Nie kopiujemy indywidualnej kalibracji DVD1 do pozostałych silników.

Nieznane prąd, temperatura, wychylenie i energia uderzeń pozostają UNKNOWN.
Autoryzacja w modelu oznacza wykonalność według dostępnych danych, a nie
potwierdzenie bezpieczeństwa termicznego. Tabelę napięć i obserwacji utrzymujemy
w jednym miejscu: [zasilanie](esp32-orchestra.md#power-supplies-and-evidence).

## Modele urządzeń

### FDD

Wszystkie cztery współdzielą konfigurację: 72 kroki od TRACK0, 5 ms dla kierunku,
2439 µs minimalnego odstępu STEP, impuls LOW 30 µs. TRACK0 jest fizycznym
punktem odniesienia; `awaySteps` i projekcja hosta nie są pomiarem położenia.
HOME ma timeout 2 s. Brak HOME blokuje REAL Play FDD; połączenie nie uruchamia
homingu automatycznie. Spóźnione impulsy nie są nadrabiane w skompresowanej serii.

Przed lokalnym eksperymentem oktawy zakres muzyczny instancji wynosił 200–410 Hz;
410 Hz ma historyczne dane odsłuchu jednego napędu, nie indywidualne potwierdzenie
czterech urządzeń. Lokalna niezacomitowana próba używa transpose -12, preferencji
100–205 Hz i okna profilu 100–410 Hz. To ustawienie odsłuchowe, nie nowy pomiar
minimalnej częstotliwości mechanicznej; nie wchodzi do tego commita.

Częstotliwość tonu/STEP i częstość nowych nut są różnymi parametrami.
Wspólny [pass ataków](fdd-attack-rate.md) dopuszcza domyślnie jeden NOTE_ON na
120 ms na stację; upraszcza szybkie ozdobniki i ponownie ocenia chronologię.
Koszt kroków/zawróceń w presetach jest estymacją, nie sensorem zużycia.

### DVD SLED

Cztery instancje działają jako `continuousRotation=true`, travel 0. Nie ma
wtedy automatycznego odbijania na końcu drogi. Dodatni travel nadal wybiera
ruch ograniczony, a -1 oznacza nieznaną drogę i odrzuca PLAY. Historyczne 140
kroków i sweep DVD1 pozostają metadanymi; nie są egzekwowane w trybie ciągłym.
Wyniki sweepu dotyczą kroków/s i warunków z ratio=1, a nie wszystkich napędów.

`stepRate = acousticHz / pitchRatio`. DVD1–3 mają hipotezę ratio 0.5 (LOW), DVD4
1.0. [Obserwacje tunera i przeliczenie](dvd-pitch-calibration.md) nie zastępują
pomiaru widma każdego silnika. Hostowy sufit muzyczny 600 Hz składa wyższe tony
o oktawy, również w DVD Lead i dla manualnych pins. Nie jest granicą termiczną.
Firmware ma dodatkowo minimalny okres 100 µs i istniejącą rampę 5000 kroków/s².
Model ocenia czas zmiany `abs(target-current)/acceleration`, a w trybie
ograniczonej drogi także hamowanie `v²/(2a)` i rezerwę drogi.

`Sled::play()` zmienia cel bez STOP; DVD sustain wydłuża wyłącznie gate'y,
sprawdzając pełną chronologię z rezerwacjami. STOP natychmiast wyłącza mostek,
nie wykonuje rampy hamowania. Licznik względny pozycji to telemetria, nie czujnik.
Ciągły obrót nie oznacza dopuszczenia nieograniczonej pracy termicznej.

### Historyczny sweep DVD1

Wcześniejszy test DVD1 obejmował 50–500 Hz co 10 Hz, przy pitchRatio=1,
rampie i automatycznym zawracaniu z limitem 140 kroków. Zapisane pasma bez
wykluczonych rezonansów: **50–120, 180–190, 270–300, 340–470 kroków/s**.
W dawnej konfiguracji ograniczonej drogi whitelist odrzucała pozostałe
częstotliwości; envelope wynosił 50–470 kroków/s. Są to obserwacje DVD1
w tamtych warunkach, nie kalibracja czterech silników ani obecnego ciągłego
obrotu. Metadane sweepu pozostają w `instances.json`; obecny nagłówek ma
zerowe liczby aktywnych allowed bands dla ciągłego obrotu.

### HDD percussion i tonal

Obecny wykonawca to perkusja: Park 40 ms, Settle 40 ms, Strike 4 ms, potem coast.
Gotowość, nominalny odstęp i okno burst pochodzą z profilu. Teoria oraz historyczny
Uno 2 ms nie mogą zastąpić wartości ESP32. Nieznane budżety prądu, temperatury
i uderzeń nie stają się bezpiecznymi limitami przez poprawne planowanie.

Profile/research HDD tonal istnieją, ale fizyczny wykonawca tonalny nie jest
włączony. Brakuje zweryfikowanego centrowania, pomiaru wychylenia i sterowania
prądem; `HDD_TONAL_EXECUTOR_UNAVAILABLE` nie jest zastępowane przypadkowym HIT.

### PC Speaker, FX i tray

Typ VHS i komendy VHS/VHS2 pozostają ze względu na kompatybilność. Aktualne
urządzenia to dwa PC Speakery przez S8050 na GPIO25/26, z niezależnymi timerami
wysokości. Gain VIRTUAL i wspólny kształt/pulse duty mają osobne ustawienia;
[pełny opis](pc-speaker-fx.md). Nie ma pomiaru odpowiedzi akustycznej ani prądu.
Tray ma komendy firmware, ale brak zatwierdzonego profilu obu pozycji registry
wyklucza je z bieżącego planowania i Laboratory.

## Ocena kandydatów i diagnostyka

Oceny TIMING, QUALITY i PHYSICAL_LOAD są niezależne: PASS/DEGRADED/UNKNOWN/BLOCKED.
`authorized`, `readyAt`, przyspieszenie, zawracanie, krótki gate i zakres decydują
o dopuszczeniu i koszcie. Krótka wykonalna nuta może być DEGRADED zamiast DROP.
Polityka muzyczna i priorytet lead/bass wybierają dopuszczalnego kandydata;
wynik jest deterministyczny. Sustain nie może przywrócić skradzionego gate'u,
zająć obcej rezerwacji ani pominąć mechanicznej gotowości. UNISON i reinforcement
rezerwują pełne przedziały; walidowane są także przyszłe nuty.

`PerformanceEvent.hardware` pokazuje wybór i kandydatów; `plan.hardware` i raport
zawierają mapowanie oraz estymowane stany. Liczniki candidate requested/dropped
nie są liczbą odrzuconych źródłowych nut: jedna nuta może próbować wielu urządzeń.
Właściwe source drops są w `report.totals`, z osobnym opisem efektów nietonalnych
i redukcji ataków FDD. Ruch, zawrócenia i obciążenie to **PLANNED**, nie pomiar.

`GET /api/plan`, `GET /api/timeline`, `GET /api/state` i `/api/monitor/raw` służą
do diagnostyki. PerformancePlan jest w `/settings` → Aranżacja.
Sprzęt zgłasza capabilities (`hardware_profiles`, `dvd_continuous`, `speaker_fx`,
`speaker_waves`, `stop_ack`); host wymaga odpowiednich funkcji, konfiguruje profile
po STOP i nie flashuje automatycznie. Weryfikację fizyczną zaczynaj od połączeń,
STOP/watchdoga i skończonych testów [Laboratory](instrument-lab.md), z pomiarami
prądu, temperatury i odpowiedzi akustycznej.
