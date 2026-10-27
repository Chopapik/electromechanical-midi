# Audyt wejściowy kolejnej refaktoryzacji — 2026-10-27

HEAD: `f394d33`. Zmiany wejściowe dotyczą wyłącznie `docs/README.md` i nowego
`docs/REFACTORING_NEXT.md`. Kod produkcyjny i konfiguracja są zgodne z HEAD.
Snapshot kodu/konfiguracji/narzędzi: `/tmp/orchestra-refactoring-next-f394d33`
(271 plików, jawny manifest `snapshot.json`; bez środowisk i sekretów).
Jest to lokalny artefakt roboczy, który może zniknąć po sprzątaniu /tmp.

## Zależności i własność danych przed zmianami

| Moduł | Odpowiedzialność | Konsumenci | Własność mutacji |
| --- | --- | --- | --- |
| allocator | Wejście alokacji, modele slot/kandydat, przygotowanie nut, ścieżka bez fizycznych profili | runtime pipeline, CLI/benchmarki, hardware_arranger, fdd_pairs, testy | Lokalne sloty i lista zdarzeń; nowy PerformancePlan |
| hardware_arranger | Fizyczne profile i rezerwacje, wybór urządzeń, walidacja, presety pochodne | allocator, fdd_pairs i inne refinements przez fold/validation | Lokalne stany urządzeń, events i raport planu |
| fdd_pairs | Revoicing i wzmocnienia par/grup | hardware_arranger | Mutuje przyjęty plan po zamknięciu bazowej alokacji |
| planning_pipeline | Wybór strategii i końcowe etapy | runtime.arranger | Jeden plan; polityka użytkownika oddzielna od kopii alokacyjnej |
| planning_context | Lanes, grupy, join, stabilne powiązania extras | compiler i refinements | Wewnętrzny kontekst jednego planu; extra:N jako projekcja |
| DeviceService | Rezerwacja, connect, utrzymanie, firmware, recovery i status UI | Application, serwer/CLI przez Application | service.lock i player.lock zgodnie z tabelą poniżej |
| RealOutput | Link, konfiguracja, logiczny POWER, aktywność i niepewność | Player/Router, DeviceService | Operacje wyjścia, a nie bezpośrednie zapisy z serwisu |
| BleOrchestraLink | Protokół komend i delegowanie do transportu | RealOutput, serwis | Własny byte transport |
| BleBytes / GatewayBytes | Wątek BLE / socket lokalnej bramy, ACK i transfer OTA | BleOrchestraLink | Własna sesja transportowa; muzyka i OTA rozłączne |

Zależność zwrotna: allocator → hardware_arranger → prywatne symbole allocator.
Dodatkowo fdd_pairs importuje _clip z allocator. Testy importują _priority i
_source_notes; zachowanie zgodności tych nazw wymaga jawnych aliasów lub migracji.
ManualPin jest używany przez testy i publiczne wejście manual_pins.

## Stan serwisu przed zmianami

| Stan | Zapis | Synchronizacja / czytelnicy |
| --- | --- | --- |
| busy, operation | run rezerwuje i zwalnia | service.lock; Application.require_available i status |
| connecting, _connect_done | connect rozpoczyna/kończy | service.lock; run i status |
| _generation | run dla firmware | service.lock; connect i recovery odrzucają starsze próby |
| _closed | shutdown | Event; connect, recovery i run cleanup |
| firmware_state | _state, odczyt w connect/recovery/run | _state pod service.lock, część odczytów bez blokady; publiczna kopia w status |
| events, sequence | _event | service.lock; emit po zwolnieniu blokady |
| error, power_error | connect, run, _power | Mieszane; status pod service.lock |
| real.link | attach/detach przez RealOutput | player.lock przy instalacji i przygotowaniu, ownership OTA lokalnie w run |
| player.owner | select_owner i finally run | player.lock; brak automatycznego PLAY po serwisie |
| porty i firmware_reason | refresh | service.lock po zakończeniu skanu |

Zagnieżdżenie blokad: player → service. Connect nie czeka na player/ACK pod
service.lock. Podczas transferu OTA RealOutput nie ma linku; run zachowuje lokalny
uchwyt i odpowiada za zamknięcie. Awaryjne power_off dopuszcza próbę OFF po
niepotwierdzonym STOP; upload odmawia takiego przejścia.

## Strategia bazowa przed zmianami

| Preset użytkownika | Bazowa alokacja fizyczna | Transformacja | Recovery runtime |
| --- | --- | --- | --- |
| balanced | balanced | standardowa walidacja i sustain | nie |
| fdd_quality | fdd_quality | standardowa walidacja i sustain | nie |
| dvd_lead_low_fdd | dvd_lead_low_fdd | standardowa walidacja i sustain | nie |
| fdd_quality_adaptive | fdd_quality, dvdContinuousSustain=false | adapt_quality_plan | nie |
| instrument_roles | instrument_roles | role instrumentów | nie |
| instrument_roles_unison | instrument_roles | fdd_pairs unison | nie |
| instrument_roles_duet | instrument_roles | fdd_pairs duet | nie |
| instrument_roles_unison4 | universal, reprezentant grupy 4 FDD | fdd_pairs quad | tak |
| fdd_expressive | universal, reprezentant pary; fixed gate 0, unison false | fdd_pairs expressive | tak |
| fdd_expressive_solo | jak expressive | expressive, potem bez akcentów | tak |
| fdd_legato | jak expressive | expressive, bez akcentów, phrase legato | tak |
| adaptive_legato | jak expressive | expressive, bez akcentów, adaptive legato | tak |
| universal | universal | standardowa walidacja i sustain | tak |

STRICT_TRACKS korzysta z osobnego alokatora; bazowa strategia runtime nadal jest
rozstrzygana przed wyborem routingu, a końcowe etapy pozostają wspólne.

## Walidacja początkowa

Wyniki i kolejne bramki są dopisywane w dzienniku `../REFACTORING_NEXT.md`.
Pełne testy backendu wymagają dostępu do lokalnych portów dla fikcyjnej bramy.
Pierwsze uruchomienie w sandboxie wykazało PermissionError wiązania localhost;
nie jest to wynik testu fizycznego BLE ani regresja aplikacji.

## Wynik rundy

Wszystkie etapy zakończono. Mapa powyżej zachowuje stan wejściowy; bieżące
odpowiedzialności i legalne przejścia są w ARCHITECTURE, a strategie i mutacje
etapów w ARRANGEMENT. Zbiorcze wyniki: 1008 host, 170 frontend, 117 przypadków
wszystkich presetów, 501 pełnych planów trzech presetów i jeden zgodny zastany
błąd parsera. Raport: `reports/refactoring-next-verification-2026-10-27.json`.
Dowody są offline/VIRTUAL; nie przeprowadzano testów fizycznych ani uploadu.
