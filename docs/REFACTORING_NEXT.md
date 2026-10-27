# Kolejna refaktoryzacja: aranżer, czytelność i serwis BLE

Status: **ZAKOŃCZONO — wszystkie etapy i bramki PASS**.
Zlecenie i wykonanie: 2026-10-27.
Data opracowania: 2026-10-27. Odbiorca: agent AI wykonujący kolejną rundę prac.
Punkt rozpoznania: `f394d33` (przed rozpoczęciem koniecznie sprawdź aktualny HEAD).

## 1. Cel i sposób użycia dokumentu

Celem jest obniżenie kosztu rozumienia i zmieniania aplikacji przy zachowaniu
obecnych wyników aranżacji, kontraktów API, zachowania odtwarzania i barier
bezpieczeństwa sprzętu. Nie jest to polecenie implementacji udzielone przez samo
utworzenie tego dokumentu. Rozpocznij wykonanie po zleceniu go przez użytkownika.
Zlecenie refaktoryzacji nie jest zgodą na flashowanie ani fizyczne testy.

Poprzednia runda została zakończona i jest opisana w
[REFACTORING_PLAN.md](REFACTORING_PLAN.md). Nie rozpoczynaj jej od nowa i nie
nadpisuj jej dziennika. Zachowaj istniejące granice Application, Player, Router,
Outputs, DeviceService, PlanningContext i frontendowych procesów komunikacji.
Ten plan dotyczy długu pozostałego wewnątrz tych granic.

Przed pracą przeczytaj bieżący `AGENTS.md`,
[ARCHITECTURE.md](ARCHITECTURE.md), [ARRANGEMENT.md](ARRANGEMENT.md) oraz sekcje
serwisu w [HARDWARE_TESTING.md](HARDWARE_TESTING.md). Kod i aktualna konfiguracja
rozstrzygają stan faktyczny; historyczne raporty nie stanowią aktualnego wyniku testów.
Nowe instrukcje użytkownika mają pierwszeństwo. Nie odtwarzaj starej konfiguracji
po to, by uzyskać zgodność z historycznym raportem.

## 2. Rozpoznany dług i docelowy rezultat

| Obszar | Obserwacja w momencie opracowania | Oczekiwany rezultat |
| --- | --- | --- |
| Alokacja | `host/playback/allocator.py` ma 826 linii, `hardware_arranger.py` 624. `allocate()` deleguje do aranżera sprzętowego, który importuje prywatne pomocniki alokatora. | Jednokierunkowe zależności i jawny wspólny kontrakt alokacji. |
| Presety | Presety pochodne wykorzystują bazowe presety, rekurencyjne wywołania i lokalne zmiany kopii konfiguracji. Znaczenie kolejności nie zawsze jest widoczne z jednego miejsca. | Czytelne rozstrzygnięcie strategii, plan etapów i udokumentowane wyjątki. |
| Dane planu | Istnieje PlanningContext, ale część danych nadal przechodzi przez słowniki i kompatybilnościowe sidecary. | Typy na istotnych granicach i jedna kontrolowana projekcja do istniejących raportów. |
| Czytelność | Gęste instrukcje, średniki, krótkie nazwy i długie wyrażenia w runtime oraz frontendzie. | Kod pokazujący kolejność, odpowiedzialność i warunki zakończenia bez rozszyfrowywania jednej linii. |
| Serwis | DeviceService łączy rezerwację operacji, połączenie, recovery, stan UI i scenariusze USB/BLE. | Jawne przejścia stanu, ograniczony zakres blokad i wspólny przebieg bezpiecznego serwisu. |
| Transport BLE | Połączenie, potwierdzenia wykonania, gateway i OTA mają różne role i cykle życia. | Wyraźna własność sesji i testy niepowodzeń na granicach, bez zmiany protokołu. |

Liczba linii jest wskazówką do przeglądu, nie celem refaktoryzacji. Nie dziel pliku
na arbitralne części tylko po to, żeby zmniejszyć jego rozmiar. Nie oceniaj
utrzymywalności samą liczbą klas, modułów lub testów.

## 3. Zakres i ograniczenia

### W zakresie

- Współdzielone typy i operacje alokatorów, sterowanie etapami i zależności presetów.
- Czytelność kodu objętego zmianami, ze szczególnym uwzględnieniem runtime i serwisu.
- Wewnętrzne kontrakty danych oraz adaptery zgodności tam, gdzie są potrzebne.
- Stan, wyłączność i cykl życia DeviceService oraz jego współpraca z transportem BLE.
- Testy zachowania, regresji, współbieżności i granic architektury.
- Aktualizacja dokumentacji faktycznie zmienionych odpowiedzialności.

### Poza zakresem

- Nowe algorytmy muzyczne, nowe presety i poprawianie brzmienia.
- Zmiana zakresów FDD/DVD, profili, gate, limitów ataków, mapowania urządzeń lub inventory.
- Zmiana timeoutów, okien ACK, retry, batchowania, lookahead i czasu wyłączenia zasilania.
- Migracja całej aplikacji na async, nowy framework, mikroserwisy, rozproszona kolejka.
- Przepisanie UI, zmiana wyglądu, globalne formatowanie repozytorium.
- Zmiana protokołu firmware, partycji, bootloadera i sposobu podpisywania OTA.
- Flashowanie, POWER ON, HOME, PLAY lub poruszanie napędami w ramach weryfikacji.

Odkryty błąd funkcjonalny opisz oddzielnie: reprodukcja, wpływ i proponowana poprawka.
Nie ukrywaj jej w refaktoryzacji ani nie zmieniaj baseline'u, żeby zamaskować różnicę.
Jeżeli błąd uniemożliwia bezpieczne zachowanie istniejącego kontraktu, zatrzymaj
zależny etap i przedstaw konkretny problem. Kontynuuj niezależne prace.

## 4. Niezmienniki obowiązujące we wszystkich etapach

### Aranżacja i wykonanie

1. To samo MIDI, konfiguracja i preferencje dają ten sam plan oraz uporządkowane
   komendy wykonawcze. Zachowaj kolejność rozstrzygania remisów i iteracji.
2. Zachowaj czasy, pitch, urządzenia, velocity, gate, powody DROP, skrócenia,
   opóźnienia, reinforcement, artykulację i relacje do nut źródłowych.
3. Zachowaj stabilne identyfikatory i powiązania extras podczas filtrowania,
   zastępowania i dopisywania. Publiczne `extra:N` pozostaje zgodne z API.
4. Nie używaj raportu diagnostycznego jako źródła sterowania wykonaniem.
5. MIDI → plan → compiler → ExecutionTimeline → Player → Router pozostaje jedyną
   ścieżką wykonania. VIRTUAL i REAL korzystają z tej samej osi czasu.
6. STRICT_TRACKS zachowuje osobną semantykę. Wyłączenie urządzenia nie renumeruje
   kolejnych urządzeń. Mute nie uruchamia ponownej alokacji.
7. Zachowaj źródłowy preset użytkownika oddzielnie od bazowej strategii alokacji.
8. Zachowaj pełną chronologię rezerwacji, limity mechaniczne, walidację po recovery,
   zachowanie ciągłych tonów oraz STOP na rzeczywistych przerwach.

### API i sesje

1. Zachowaj pola i znaczenie komend, odpowiedzi, requestId, stanów i błędów.
2. Audio ACK i heartbeat muszą obsługiwać wymagane ścieżki bez czekania w kolejce,
   która sama oczekuje na ich potwierdzenie.
3. Rozłączenie starej sesji nie może odebrać audio nowemu właścicielowi.
4. Zmiana wyjścia podczas planowania pozostaje dostępna zgodnie z obecnym kontraktem.
5. Nie traktuj zakolejkowania komendy, wysłania przez socket ani zakończenia zapisu
   BLE jako potwierdzenia wykonania przez kontroler.

### Serwis, BLE i ATX

1. DeviceService pozostaje wspólnym punktem wejścia dla utrzymania urządzenia.
2. Przy zagnieżdżeniu blokad obowiązuje kolejność `player.lock` → `service.lock`.
   Nie trzymaj `service.lock` podczas czekania na Playera, ACK, skan, build lub upload.
3. Muzyka i OTA mają wzajemnie wykluczające się użycie sesji BLE. Samo odłączenie
   linku od wyjścia nie może utracić odpowiedzialności za jego zamknięcie.
4. Upload wymaga wyłączności, potwierdzonego ALL STOP i skorelowanego POWER OFF,
   odczekania po GPIO19 LOW oraz właściwego przygotowania transportu.
5. USB zwalnia BLE, sprawdza port, buduje i ponownie sprawdza ten sam port przed
   uploadem. BLE zachowuje wyłączny link do transferu. Nie ujednolicaj tych różnic.
6. Brak komunikacji albo ACK przerywa upload. GPIO19 jest stanem logicznym,
   nie pomiarem napięcia. Nie zastępuj potwierdzenia arbitralnym sleep.
7. Nie ponawiaj automatycznie niepotwierdzonego transferu OTA. Recovery połączenia
   nie jest ponowieniem uploadu i nie może zacierać informacji o jego niepowodzeniu.
8. Recovery nie wykonuje POWER ON, HOME ani PLAY. Sukces flash i sukces recovery
   są odrębnymi informacjami.
9. Prywatny klucz pozostaje w wolumenie ustawień. Nie loguj, nie commituj i nie
   przesyłaj go przez BLE. Używaj fikcyjnego klucza w izolowanych testach.
10. Nie zmieniaj awaryjnej semantyki `power_off`: obecny kod ma odrębną obsługę
    niepowodzenia STOP. Nie przenoś tego wyjątku do bariery firmware; odtwórz go testem.
11. Bez osobnej zgody nie wywołuj uploadu. Po zgodzie używaj wyłącznie wspólnej
    procedury `.venv/bin/python scripts/safe_upload.py` lub jej wariantu
    `--transport ble`, zgodnie z AGENTS.md. Nigdy bezpośredniego `pio run -t upload`,
    `run_firmware` z portem ani surowego transportu OTA.
12. Pierwszy bootstrap bez obsługi POWER pozostaje poza tym planem: wymaga osobnej
    zgody, fizycznego odłączenia ATX i przeglądu domen zasilania ESP32/SR.

## 5. Etap 0 — aktualny punkt odniesienia i mapa zależności

**Cel:** mieć dowód zachowania sprzed zmian oraz odtwarzalne wejścia.

1. Odczytaj HEAD, `git status --short` i aktualne instrukcje. Nie usuwaj ani nie
   resetuj zmian użytkownika. Zapisz, na jakim stanie rzeczywiście pracujesz.
2. Przejrzyj miejsca użycia prywatnych symboli `allocator`, wywołania
   `allocate_hardware`, modyfikacje PerformancePlan oraz stan i blokady serwisu.
   Obejmij testy, CLI, benchmarki i narzędzia raportowania.
3. Utwórz mapę: moduł → odpowiedzialność → konsumenci → własność mutowalnych danych.
   Dla serwisu dodaj: pole → kto zapisuje → pod jaką blokadą → kto czyta.
4. Uruchom pełne testy hosta, frontend, build i kontrolę architektury. Odróżnij
   błąd środowiska od regresji. Stare liczby 917/168 lub 57 modułów nie są celem
   ani dowodem stanu aktualnego checkoutu.
5. Przed pierwszą zmianą produkcyjną zachowaj snapshot niezbędnego kodu,
   konfiguracji i narzędzi oraz aktualny baseline. Nie kopiuj środowisk, sekretów,
   wolumenów ani klucza OTA. Sam SHA nie odtwarza niecommitowanych zmian.
6. Zapisz manifest MIDI z SHA, katalog presetów, wersje narzędzi i izolowane
   preferencje. Capture i verify wykonaj na tym samym niezmienionym kodzie.
7. Użyj nowego artefaktu, np. `reports/refactoring-next-baseline-YYYY-MM-DD.jsonl.gz`.
   Nie nadpisuj baseline'u poprzedniej rundy: od tamtej pory zmienił się m.in.
   rejestr FDD. Nie kopiuj istniejącego pliku pod nową nazwą jako nowego pomiaru.
8. Utwórz także baseline pełnego dostępnego korpusu. Obecne narzędzie korpusowe
   obejmuje `universal`, `fdd_expressive`, `adaptive_legato`; nie jest dowodem dla
   wszystkich presetów. Mały baseline musi obejmować cały bieżący katalog.
9. Brak wejściowego MIDI lub snapshotu zgłoś jako brak pokrycia. Nie podmieniaj
   wejść po cichu. Znane błędy parsera zapisz osobno, wraz z tym, co porównujesz.

**Brama:** baseline przechodzi verify bez zmian; wejścia i snapshot można odtworzyć;
wyniki początkowe i zakres niepokryty są zapisane. W przeciwnym razie nie zaczynaj
przenoszenia algorytmów.

## 6. Etap 1 — wspólny kontrakt alokacji i usunięcie zależności zwrotnej

**Pliki wejściowe:** `host/playback/allocator.py`, `hardware_arranger.py`,
`performance.py`, `device_models.py`, konsumenci ustaleni w etapie 0.

1. Zinwentaryzuj `_Slot`, `_Candidate`, `_source_notes`, `_dropped`, `_place`,
   `_clip`, `_adaptive_cap`, `_duplicate_kpis`, `_partition_effects`, `_priority`.
   Sprawdź zależności każdego z nich; nie przenoś automatycznie całej listy.
2. Wydziel spójne wspólne modele, przygotowanie wejścia i operacje planu do
   neutralnego modułu lub niewielkiej grupy modułów w `playback`. Robocze nazwy:
   `allocation_models.py`, `allocation_input.py`, `allocation_operations.py`.
   Wybierz ostateczny podział na podstawie rzeczywistych zależności.
3. Wspólny moduł nie importuje ani `allocator`, ani `hardware_arranger`, runtime,
   transportów i kontrolerów HTTP. Typy nie mogą zależeć od implementacji podglądu.
4. Wydziel publiczne nazwy tylko dla rzeczywiście współdzielonych operacji.
   Nie rozwiązuj problemu samym usunięciem podkreślników z nazw w starym module.
5. Zachowaj istniejące funkcje wejścia `allocate`, `allocate_hardware` i
   `manual_pins`, o ile audyt wykazał ich użycie. Adapter zgodności ma być cienki,
   opisany i nie może przechowywać drugiej implementacji.
6. Przenieś kod bez zmian matematyki, sortowania, kolejności mutacji i precyzji.
   Osobno dokonuj poprawy nazw lub formatowania, żeby diff był weryfikowalny.
7. Dopisz kontrolę zakazującą ponownego importowania prywatnych pomocników
   `allocator` przez aranżer sprzętowy i zależności zwrotnej neutralnych modułów.

**Docelowy kierunek:** `allocator` → `hardware_arranger` → wspólne moduły;
`allocator` może też korzystać ze wspólnych modułów. Brak importu zwrotnego.

**Testy:** allocator, hardware, hardware_profiles, auto_arranger, arrangement,
STRICT_TRACKS, efekty niepitched i continuity; pełny mały baseline, a przed
zamknięciem etapu pełny korpus i kontrola architektury.

**Brama:** brak zależności zwrotnej; wszystkie istniejące ścieżki wejścia działają;
projekcja wykonania identyczna, a nowe granice mają automatyczną ochronę.

## 7. Etap 2 — jawne strategie presetów i kolejność etapów

**Pliki wejściowe:** `host/runtime/planning_pipeline.py`,
`host/playback/hardware_arranger.py`, `fdd_pairs.py`, `fdd_expression.py`,
`fdd_legato.py`, `adaptive_legato.py`, `fdd_adaptive.py`, `universal_recovery.py`.

1. Rozpisz tabelę dla każdego presetu: strategia bazowa, logiczne głosy/pary,
   transformacje, recovery, ograniczenia, walidacja i końcowy preset raportowany.
2. Wykorzystaj istniejący `ArrangementStrategy`. Nie twórz drugiego niezależnego
   katalogu presetów ani drugiego pipeline'u konkurującego z obecnym.
3. Oddziel rozstrzygnięcie strategii od wykonania. Zastąp niejawne zależności
   parametrami lub niewielkim typowanym opisem, bez rozbudowanego systemu pluginów.
4. Zrekonstruuj dokładną semantykę rekurencyjnych wywołań `allocate_hardware`.
   Usuń rekurencję tylko tam, gdzie można zapisać identyczną sekwencję etapów.
   Nie spłaszczaj różnych presetów do wspólnej ścieżki kosztem wyjątków muzycznych.
5. Zachowaj sekwencję: alokacja → ekspresja → ograniczenia FDD → warunkowy recovery
   z ponowną walidacją → końcowa artykulacja. Odtwórz również etapy wewnętrzne.
6. Rozróżnij flagi mające różne znaczenie. Przykład do audytu: `logical_fdd`
   przyjmujący wartości logiczne i liczbowe. Nowy typ musi zachować rozróżnienie
   faktycznych trybów; nie utożsamiaj `True` i liczby głosów bez analizy użyć.
7. Zdefiniuj dla etapu: wejście, mutowane pola, wyjście, niezmienniki i moment
   walidacji. Nie kopiuj całego planu w każdym etapie bez uzasadnienia.
8. Nie podmieniaj czasowo konfiguracji użytkownika. Kopia strategii jest oddzielna
   od wybranego presetu, a publiczne raportowanie zachowuje jego tożsamość.

**Testy:** wszystkie presety z katalogu, FDD pairs/unison4/expressive/legato/
adaptive, recovery, DVD register/sustain, wyłączeni partnerzy, piny ręczne,
STRICT_TRACKS, granice czasowe i brak wolnego miejsca na wzmocnienie.
Testuj wynik i kolejność istotnych efektów, nie tylko listę nazw wywołanych funkcji.

**Brama:** tabela presetów zgadza się z implementacją; żadna zmiana decyzji,
extras ani komend; pełny baseline i korpus zgodne.

## 8. Etap 3 — dane planowania i czytelność

1. Przeglądaj kolejno kod zmieniony w etapach 1–2, następnie
   `planning_pipeline.py`, `application.py`, `outputs.py`, `device_service.py`.
   Frontend obejmuj tylko tam, gdzie gęsty kod utrudnia zrozumienie przepływu.
2. Rozbij wielokrotne instrukcje na osobne linie; nazwij warunki i wartości
   pośrednie. Nadaj zmiennym nazwy opisujące rolę, jednostkę i własność.
3. Rozdziel formatowanie od przenoszenia odpowiedzialności. Nie formatuj całego
   repozytorium ani nie wprowadzaj dużego zestawu nowych narzędzi w tym etapie.
4. Na granicach współdzielonych danych rozważ dataclass, Enum, TypedDict lub
   Protocol. Dobieraj typ do roli: TypedDict opisuje kształt, ale nie waliduje
   danych w runtime. Nie zastępuje istniejących walidatorów JSON/WS.
5. Pierwszeństwo mają dane przechodzące przez kilka modułów: strategia alokacji,
   kandydat i slot, powiązania artykulacji, wynik operacji serwisowej.
6. Zachowaj `PlanningContext` jako źródło wewnętrznych danych wykonania.
   Kompatybilnościowe słowniki raportu powstają na granicy. Nie utrzymuj dwóch
   niezależnie edytowalnych reprezentacji tego samego stanu.
7. Przed zmianą typu sprawdź serializację, equality, kolejność, mutowalność,
   domyślne wartości i zachowanie braku pola. Zachowaj publiczny JSON.
8. Komentarze mają objaśniać powód nietypowej decyzji: kolejność blokad, remisy,
   precyzję float, ownership lub wyjątek presetu. Nie opisuj oczywistej składni.
9. Nie usuwaj obsługi błędów jako „szumu”. Dla szerokiego `except` ustal, czy
   chroni recovery, sprzątanie lub barierę bezpieczeństwa, zanim go zawęzisz.

**Brama:** zmiany czytelności nie zmieniają semantyki; typy nie tworzą zależności
zwrotnych; aktualne testy i baseline dla dotkniętej ścieżki są zgodne. Zmiana
wspólnych modeli planu wymaga także pełnego korpusu.

## 9. Etap 4 — jawny stan i cykl życia DeviceService

**Pliki wejściowe:** `host/runtime/device_service.py`, `outputs.py`, `player.py`,
`application.py`, testy ownership, ATX, safe upload i firmware flow.

1. Przed zmianą rozpisz tabelę przejść dla connect, zwykłego serwisu, firmware USB,
   firmware BLE, recovery i shutdown. Uwzględnij `busy`, `connecting`, `operation`,
   `_generation`, `_connect_done`, `_closed`, `firmware_state` i stan linku.
2. Oddziel wewnętrzny stan operacji od publicznej projekcji UI. Nie zastępuj
   niezależnych osi flash/recovery jedną flagą success/error.
3. Zdefiniuj legalne przejścia, właściciela każdego przejścia i zachowanie przy
   spóźnionym wyniku. Nowa generacja unieważnia wcześniejszą próbę recovery.
4. Skup rezerwację i zwalnianie operacji w jednym mechanizmie. Obejmij błędy przed
   budową, podczas budowy, po odłączeniu linku i podczas sprzątania.
5. Oddziel zarządzanie stanem/zdarzeniami od pracy na urządzeniu. DeviceService
   nadal koordynuje całość. Nie twórz nowej klasy dla każdej metody.
6. Wstrzyknij tylko zależności potrzebne do deterministycznych testów: fabrykę
   połączenia, build/upload, oczekiwanie lub zegar tam, gdzie test tego wymaga.
   Produkcyjne wartości domyślne i terminy pozostają niezmienione.
7. Zdefiniuj ownership linku przy connect, attach, detach i OTA. Każda ścieżka
   kończy się jednoznacznym przekazaniem albo zamknięciem; nie zamykaj linku
   przejętego przez nowszą operację.
8. Callbacki i emitowanie zdarzeń nie mogą niejawnie powodować reentrancy pod
   blokadą. Odtwórz i przetestuj ich położenie względem sekcji krytycznych.
9. Zachowaj numerację i kolejność firmware events, requestId i limity historii.
   Po zmianie struktury klas przenieś mocki testowe na właściwą granicę.
10. Nie „naprawiaj” shutdown dodaniem blokującego join bez testu, że wątek nie
    oczekuje na zasób trzymany przez zamykający go kod.

**Brama:** tabela stanów odpowiada kodowi; cleanup działa po każdym błędzie;
spóźnione connect/recovery nie przyłączają starego linku; testy nie używają sprzętu.

## 10. Etap 5 — wspólny przebieg USB/BLE z zachowaniem różnic transportów

**Pliki wejściowe:** DeviceService, `host/ble_link.py`, `ble_gateway.py`,
`ble_ota.py`, `firmware.py`, `firmware_ota.py`, `scripts/safe_upload.py`.

1. Wyodrębnij wspólną orkiestrację: rezerwacja → STOP → POWER OFF → odczekanie →
   przygotowanie transportu → build → upload → zamknięcie/przekazanie → recovery.
   Sprawdź dokładne obecne miejsca kontroli capability i klucza; nie przesuwaj
   ich arbitralnie, jeśli zmienia to skutki uboczne lub raportowanie błędu.
2. USB i BLE mogą mieć małe adaptery przygotowania i transferu. Adapter nie
   omija DeviceService i nie może sam uznawać braku ACK za bezpieczne OFF.
3. Budowanie obrazu i transport nie decydują o właścicielu Playera ani o POWER.
   Zwracają wynik lub błąd do koordynatora. Postęp jest raportowany przez callback.
4. Nie przenoś prywatnego klucza do obiektu statusu, zdarzeń ani transportowego
   DTO. Zachowaj lokalne podpisywanie i publiczną weryfikację firmware.
5. Zapisz granice odpowiedzialności: DeviceService — bariera i wyłączność;
   BleOrchestraLink — operacje linku; BleBytes/GatewayBytes — transport;
   gateway — przekazanie i potwierdzenia; BLE OTA — transfer protokołu.
6. Zachowaj przygotowanie konfiguracji przed startem zegara muzyki, ograniczony
   zbiór komend konfiguracji i potwierdzenia wykonania. Refaktoryzacja serwisu nie
   może przywrócić overrunów usuniętych w późniejszych poprawkach BLE.
7. Nie przebudowuj pakietowania muzyki ani protokołu ACK w tej rundzie. Jeżeli
   jest konieczne do zamierzonego podziału, zmniejsz zakres podziału.
8. Porównaj ślady operacji dla sukcesu i błędów przed/po refaktoryzacji. Sprawdzaj
   zarówno wymagane czynności, jak i brak niedozwolonych efektów ubocznych.

**Brama:** jedna wspólna bariera bezpieczeństwa; testy obu transportów przechodzą;
niepotwierdzony transfer nie jest ponawiany; nie zmieniono firmware/protokołu.

## 11. Macierz obowiązkowych scenariuszy serwisowych

Wykorzystaj istniejące testy i dodawaj brakujące scenariusze. Test ma obserwować
wynik, ślad komend i ownership; nie utrwalać wyłącznie prywatnego układu klas.

| Scenariusz | Co trzeba wykazać offline |
| --- | --- |
| Brak STOP ACK | Build i transfer nie ruszają; operacja kończy się błędem. |
| Brak lub błędne POWER OFF ACK | Nie ma build/upload; stan zasilania nie udaje potwierdzonego OFF. |
| Brak capability OTA lub klucza | Brak transferu i automatycznego generowania nowego klucza BLE. |
| USB brak/wiele portów, zmiana portu po build | Brak uploadu na niewłaściwy port. |
| Błąd build | Brak transferu, zwolnienie rezerwacji, właściwe recovery. |
| BLE utracone w trakcie OTA | Brak fałszywego success i automatycznej retransmisji. |
| Flash udany, recovery nieudane | Zachowany sukces flash i osobny błąd/retry połączenia. |
| Connect równolegle z serwisem | Brak podwójnego właściciela i zakleszczenia blokad. |
| Stare recovery po nowszej operacji | Nie dołącza starego linku ani nie nadpisuje nowego statusu. |
| Shutdown podczas recovery | Próba nie ożywia zamkniętej usługi, zasoby są sprzątnięte. |
| PLAY/lab/zmiana wyjścia podczas OTA | Brak muzycznych zapisów do sesji OTA i przejęcia linku. |
| STOP czekający na audio ACK | ACK dociera bez zakleszczenia przez blokadę lub kolejkę. |
| Awaryjne POWER OFF po błędzie STOP | Dotychczasowy osobny kontrakt OFF pozostaje zachowany. |
| Każdy koniec ścieżki serwisowej | Brak automatycznych POWER ON, HOME i PLAY. |
| Stara sesja Web Audio | Nie usuwa nowego właściciela po zakończeniu swojej dzierżawy. |

Wyścigi odtwarzaj przez Event/barierę/fikcyjny transport i ograniczony timeout
testu. Nie opieraj poprawności na przypadkowych sleep ani rzeczywistym skanowaniu
BLE. Testy jednostkowe mają podstawione build/upload, porty, klucze i połączenia.
Testy poleceń firmware oparte na źródłach nie dowodzą działania fizycznego sprzętu.

## 12. Polecenia i zasady walidacji

Wszystkie poniższe polecenia wykonuj z katalogu repozytorium, chyba że wskazano
inaczej. Przed pierwszym użyciem przeczytaj aktualne skrypty i ich `--help`.
Nazwy artefaktów z `YYYY-MM-DD` zastąp datą bieżącej rundy i zapisz w dzienniku.
Nie uruchamiaj capture po zmianach jako zamiennika punktu odniesienia.

```sh
.venv/bin/python -m unittest discover -s host/tests -q
.venv/bin/python scripts/check_architecture.py
.venv/bin/python scripts/generate_preset_catalog.py --check
npm --prefix web test
npm --prefix web run build
```

Mały baseline przed zmianami, następnie verify po kolejnych etapach:

```sh
.venv/bin/python scripts/refactoring_baseline.py --capture reports/refactoring-next-baseline-YYYY-MM-DD.jsonl.gz
.venv/bin/python scripts/refactoring_baseline.py --verify reports/refactoring-next-baseline-YYYY-MM-DD.jsonl.gz
```

Capture korpusu wykonaj przed zmianami lub z zachowanego snapshotu. Podany katalog
`midi` jest lokalnym minimum; dodatkowe dostępne katalogi dodaj przez kolejne
`--midi-dir`, zapisując ich manifest. Nie zakładaj istnienia `~/Music/MIDI`.

```sh
.venv/bin/python scripts/refactoring_corpus.py --capture reports/refactoring-next-corpus-YYYY-MM-DD.json --midi-dir midi --workers 3
.venv/bin/python scripts/refactoring_corpus.py --verify reports/refactoring-next-corpus-YYYY-MM-DD.json --workers 3
```

Zestaw serwisowy do szybkiej weryfikacji po małej zmianie (nie zastępuje pełnego):

```sh
PYTHONPATH=host:host/tests .venv/bin/python -m unittest test_device_ownership test_atx_power test_safe_upload test_firmware_flow test_ble_ota_service test_firmware_ota test_ble_ota test_ble_ota_gateway test_ble_ota_firmware test_ble_link test_ble_gateway test_ble_gateway_receipts test_ble_execution_ack test_application_scenarios test_output_during_planning -q
```

Przy rozbieżności baseline'u:

1. Zidentyfikuj MIDI, preset i pierwszą różnicę; dla korpusu użyj `--dump-case`
   z `--report` i `--dump-output` po sprawdzeniu bieżącej składni narzędzia.
2. Porównaj snapshot i bieżący kod na dokładnie tych samych danych i ustawieniach.
3. Odróżnij projekcję wykonania od czasów pomiaru/diagnostyki. Nie zaokrąglaj
   floatów, nie sortuj ponownie komend i nie pomijaj pól, żeby uzyskać PASS.
4. Napraw regresję albo wydziel jawnie zmianę zachowania poza ten etap.
5. Sprawdź, czy wspólna zmiana serializatora/verifiera nie ukryła różnic.
   Nie aktualizuj naraz implementacji i oczekiwań bez niezależnego porównania.

Wydajność: zachowaj pomiary czasu i pamięci na tych samych reprezentatywnych MIDI.
Porównuj powtarzane przebiegi w podobnych warunkach, a nie pojedynczy pomiar.
Powtarzalne pogorszenie wyjaśnij i usuń przed zamknięciem etapu; nie obiecuj
przyspieszenia na podstawie samego podziału modułów. Nie zmieniaj algorytmu w celu
optymalizacji w ramach tej rundy.

## 13. Wdrożenie po etapach implementacyjnych

Po zmianach aplikacji, backendu, konfiguracji lub dołączonego firmware obowiązuje
AGENTS.md:

```sh
docker compose up -d --build orchestra
docker compose ps orchestra
docker compose port orchestra 8000
```

Następnie sprawdź healthcheck, `/api/state` i stronę główną na rzeczywiście
zmapowanym porcie. Zweryfikuj zawartość zmienionych plików w działającym kontenerze
(np. przez porównanie SHA-256 z checkoutem), a po zmianie frontendu także bundle
wskazany przez serwowany HTML. Sam status „healthy” nie dowodzi nowej wersji.
Nie loguj sekretów ani pełnych środowisk kontenera.

Sprawdzenie wdrożenia jest pasywne: nie uruchamia utworu, lab, HOME, POWER ON ani
uploadu. Nie zmieniaj ustawień REAL/VIRTUAL użytkownika tylko dla testu. Nie kasuj
wolumenów, zwłaszcza wolumenu z preferencjami i prywatnym kluczem OTA.
Niedostępnego Dockera lub nieudanego healthchecku nie opisuj jako udanego wdrożenia.
Prace wyłącznie dokumentacyjne nie wymagają przebudowy.

## 14. Etap 6 — zamknięcie i przekazanie

1. Uruchom pełny zestaw hosta, frontend, build, generator, kontrolę architektury,
   mały baseline wszystkich presetów i korpus. Nie powtarzaj kosztownych testów
   bez powodu, jeżeli po ich przejściu nie zmienił się kod wpływający na wynik.
2. Uzupełnij guard architektury o nowe granice, uwzględniając importy względne
   i wewnątrz funkcji. Sprawdź pokrycie nowych modułów. Istniejący guard nie jest
   pełnym analizatorem typów, cykli i współbieżności — nie przedstawiaj go jako takiego.
3. Przejrzyj pozostałe adaptery zgodności. Usuń je tylko po audycie konsumentów;
   pozostawione opisz wraz z przyczyną i warunkiem przyszłego usunięcia.
4. Zaktualizuj ARCHITECTURE i ARRANGEMENT zgodnie z rzeczywistą implementacją.
   Nie kopiuj całej dokumentacji algorytmów do tego planu.
5. Wykonaj wdrożenie i weryfikację z rozdziału 13.
6. Zapisz wynik, dowody, odstępstwa, niepokryte obszary i pozostały dług.
   Wyraźnie oznacz testy offline/VIRTUAL oraz brak testów fizycznych.

### Kryteria ukończenia całej rundy

- Alokatory nie korzystają ze wzajemnych prywatnych implementacji.
- Wspólne modele i operacje mają neutralną, jednokierunkową zależność.
- Strategia i kolejność etapów są jawne dla każdego presetu.
- Wyniki wykonania i publiczne kontrakty pozostały zgodne z aktualnym baseline'em.
- DeviceService ma udokumentowaną własność stanu, legalne przejścia i cleanup.
- Testy obejmują błędy uploadu, wyłączność BLE i deterministyczne wyścigi.
- Nie wprowadzono drugiego źródła stanu ani nowej ścieżki omijającej bariery.
- Zmiany czytelności pomagają prześledzić przepływ, zamiast jedynie mnożyć pliki.
- Działający kontener zawiera nowy kod i jest healthy.
- Dziennik zawiera faktyczne wyniki, bez przypisywania offline dowodów sprzętowych.

## 15. Organizacja pracy, zatrzymanie i wznowienie przez agenta

Pracuj w kolejności etapów 0–6, małymi zmianami. Czytelność poprawiaj również
lokalnie podczas etapów, lecz nie mieszaj formatowania całego pliku z trudną
zmianą algorytmiczną. Nie dodawaj zależności lub ogólnych frameworków „na przyszłość”.

Przed każdym etapem zapisz krótki zamiar i bramkę. Po etapie zapisz wyniki.
Przy wznowieniu przeczytaj dziennik, sprawdź aktualny diff i zacznij od pierwszego
nieukończonego etapu. Nie uznawaj samego checkboxa za dowód wykonania.

Nie resetuj cudzych zmian. Cofanie własnego etapu ma być ograniczone do jego
zmian, bez destrukcyjnego resetu checkoutu. Nie wycofuj nowych funkcjonalnych
poprawek użytkownika tylko dlatego, że zmieniły historyczny baseline.

Commity, jeśli są wykonywane, powinny odpowiadać spójnym krokom i przestrzegać
AGENTS.md: opisowy temat, krótki opis co/po co, dotknięte zachowanie, walidacja
oraz ograniczenia offline/VIRTUAL. Nie używaj samego „cleanup” jako opisu.

Ten dokument nie nakazuje delegowania. Jeżeli użytkownik osobno zleci pracę
wielu agentów, rozdziel odpowiedzialność za pliki i nie prowadź jednoczesnych
edycji alokatora, modeli planu lub DeviceService bez jednego właściciela integracji.

Zatrzymaj zależny etap, gdy brakuje odtwarzalnego baseline'u, pojawia się różnica
wykonania bez wyjaśnienia, wymagana byłaby zmiana protokołu/sprzętu lub nie można
zachować bariery uploadu. Zapisz konkretną przeszkodę i wymagane rozstrzygnięcie.
Nie obchodź ograniczeń. Rutynowe decyzje o nazwach i podziale modułów podejmuj
samodzielnie w ramach zleconego zakresu.

## 16. Dziennik wykonania

Dziennik bieżącej realizacji. Wyniki historyczne poprzedniej rundy nie zastępują walidacji poniżej.

| Etap | Status | Wyniki / raport / commit |
| --- | --- | --- |
| 0. Punkt odniesienia i mapa zależności | GOTOWE | 994 host / 170 frontend; 117 capture+verify; 168 źródeł w korpusie |
| 1. Wspólny kontrakt alokacji | GOTOWE | 145 testów; guard; baseline117; korpus lokalny264 i końcowy501 PASS |
| 2. Strategie i etapy presetów | GOTOWE | 120 testów; baseline117 i korpus501 PASS; brak rekurencji |
| 3. Dane i czytelność | GOTOWE | AST i kontrakty zgodne; baseline117 / korpus501 PASS |
| 4. Stan i cykl życia serwisu | GOTOWE | 9 testów lifecycle, testy ownership/POWER/recovery PASS |
| 5. Orkiestracja USB/BLE | GOTOWE | 11 zamrożonych śladów zgodnych; pełne testy BLE/OTA PASS |
| 6. Walidacja, wdrożenie, dokumentacja | GOTOWE | 1008 host, 170 frontend, build/generator, guard62, corpus501, deploy PASS |

Szablon wpisu po etapie:

```text
Data i etap:
HEAD wejściowy / stan lokalnych zmian:
Zakres i zmienione odpowiedzialności:
Zachowane kontrakty i niezmienniki:
Polecenia walidacji i faktyczne wyniki:
Baseline / manifest / raport / snapshot:
Wynik wdrożenia i dowód wersji:
Odstępstwa, błędy zastane i pozostały dług:
Ograniczenia: offline / VIRTUAL / brak prób fizycznych:
Commit, jeżeli wykonany:
Następny krok i jego bramka:
```

### Rozpoczęcie — 2026-10-27

HEAD wejściowy: `f394d33`. Zmiany wejściowe: plan i odnośnik w indeksie docs.
[Mapa odpowiedzialności i presetów](research/refactoring-next-audit.md). Snapshot
271 plików: `/tmp/orchestra-refactoring-next-f394d33`; etap 1 zachowany osobno
w `/tmp/orchestra-refactoring-next-stage1` do niezależnej weryfikacji korpusu.

Backend przed zmianami: **994 PASS** (33,564 s), frontend **170 PASS**, build,
generator i guard **57 PASS**. Testowe porty localhost wymagały wyjścia poza
sandbox; pierwszego PermissionError nie traktujemy jako błędu aplikacji.
Nowy mały baseline `reports/refactoring-next-baseline-2026-10-27.jsonl.gz`: 117
przypadków capture+verify PASS, także po etapie 1. Nie zmieniano verifiera.
Pełny korpus jest przechwytywany z niezmiennego snapshotu, także z lokalnej
biblioteki Music/MIDI; niezależne snapshoty etapów zachowują możliwość zbadania
pierwszej regresji. Etapy pozostają otwarte do zakończenia pełnej weryfikacji.

Etap 1: neutralne modele, source preparation i event operations. Stare nazwy
prywatne pozostają aliasami zgodności dla testów/CLI; refinements nie używają
alokatora jako biblioteki. 145 testów PASS; rozszerzony guard 13 testów PASS.
Kontener po rebuildzie healthy, API HTTP 200, wdrożony SHA256 allocation_operations
zgodny z checkoutem. Bez flashowania i prób fizycznych.

### Etapy 2–5 — implementacja i bramki lokalne

- `ArrangementStrategy` przeniesiony do neutralnego `arrangement_strategy`;
  `HardwareAllocationStrategy` rozstrzyga bazowy preset i refinement przed
  alokacją. Pojedynczy backbone zastąpił rekurencję, jawny `FddGrouping` zachowuje
  różnicę True → 4 i 2 → pary. ID pochodzą z istniejącego katalogu, generator PASS.
- 120 testów presetów/Legato/recovery PASS; 117/117 baseline po etapie 2 i po
  końcowych zmianach czytelności PASS. Próbny cykl importów strategy→Legato został
  wykryty przed wdrożeniem i usunięty: opis strategii zależy wyłącznie od danych
  presetów i konfiguracji. Nowy guard zapobiega jego przywróceniu.
- Czytelność: rozwinięto instrukcje i bloki w jednej linii w Application,
  Real/VirtualOutput, pipeline i hardware_arranger. Samo rozwinięcie sprawdzono
  jako identyczny AST, bez atrybutów pozycji. Pipeline ma czytelniejsze nazwy
  zmiennych. SourceNote opisuje istniejący mapping, bez nowej serializacji.
- Serwis: typ operacji, ticket generacji, typ statusu, zakres rezerwacji/cleanup
  i FirmwareSession odpowiedzialna za zamknięcie linku OTA. Bariera STOP/OFF
  pozostaje wspólna; build/transfer USB/BLE mają jeden przebieg i zachowane
  odmienne przygotowanie transportu. Protokołu transportów/firmware nie zmieniono.
- 11 śladów sukcesu i awarii USB/BLE ze snapshotu `f394d33` porównano dokładnie
  z nowym kodem: te same efekty, komendy, zdarzenia i kolejność. Zapis wejściowy
  jest w `host/tests/fixtures/service-lifecycle-2026-10-27.json`; test nie
  regeneruje go z bieżącej implementacji.
- Jawne poprawki cyklu życia: callback pierwszego statusu nie pozostawia busy;
  shutdown podczas POWER/STOP ACK nie instaluje spóźnionego linku; zamknięta
  usługa odmawia nowej operacji. Trzy nowe testy uruchomione na snapshotcie
  wejściowym odtworzyły cztery niepowodzenia (dwa momenty ACK). Bieżący kod
  przechodzi te regresje oraz test starego recovery i wyłączności OTA.
- Pełny host na tej bramce: **1006 PASS**, frontend **170 PASS**, TypeScript/Vite build PASS,
  guard **62 moduły PASS**. Zmiany helpera testowego po tym przebiegu sprawdzono
  ponownymi dziewięcioma testami lifecycle PASS. Brak prób fizycznych.
- Pomiar 3 wycinków 48 s, po rozgrzaniu po 5 powtórzeń i oddzielny tracemalloc:
  `reports/refactoring-next-performance-2026-10-27.json`. Stosunek median czasu
  nowy/stary: 0,838 / 0,910 / 0,962; szczyt śledzonych alokacji w każdym ~1,000.
  Równolegle trwały zadania korpusu, więc nie traktujemy tego jako dowodu
  przyspieszenia ani SLA. Brak zaobserwowanej regresji na tych trzech wejściach.
- Kolejny rebuild orchestra PASS: healthy, `/api/state` HTTP 200, frontend
  serwuje bundle `index-CZz3cXKD.js`; SHA trzech zmienionych modułów zgodne.
- Trwałe archiwum wejściowego kodu/konfiguracji/narzędzi i niezmienionych źródeł
  firmware: `reports/refactoring-next-source-2026-10-27.tar.gz`, z manifestem SHA.
  Pozwala odtworzyć snapshot po usunięciu /tmp. Nie zawiera środowisk ani kluczy.

Pełne bramki korpusowe pozostają otwarte. Prace nad stanem serwisu i czytelnością
kontynuowano podczas niezależnego przeliczania danych ze snapshotu; nie ogłaszamy
ukończenia etapów wyłącznie na podstawie małego baseline'u. Zachowany snapshot
etapu 1 umożliwia niezależną diagnozę przed zmianą strategii. Końcowy wpis ma
podać rzeczywiste pokrycie całego korpusu i ograniczenia parsera.

Końcowy pełny host po uzupełnieniu scenariuszy: **1008 PASS** (54,657 s).
Frontend ponownie **170 PASS**, build PASS. Przeniesione 13 modeli/pomocników
porównano dodatkowo przez AST ze snapshotem wejściowym, normalizując wyłącznie
zmienione nazwy i adnotacje typów: zgodne. Cały AST Application i Outputs jest
identyczny ze snapshotem. Pełne korpusowe porównania nadal są w toku.

### Zakończony capture pełnego korpusu

`reports/refactoring-next-full-corpus-2026-10-27.json`: **168 unikalnych SHA**,
**167 czytelnych MIDI × 3 presety = 501 pełnych planów**, zero błędów planowania.
Jeden zastany błąd parsera dotyczy `touhou4.mid` (`list index out of range`).
Nie poprawiano parsera w tej rundzie; verify ma sprawdzić także zgodność tego błędu.
88 plików z lokalnego capture stanowi dokładnie zgodny podzbiór tego raportu:
porównano wszystkie digests i błędy, wyłączając wyłącznie czas pomiaru.
Końcowe verify 168 źródeł rozpoczęto po atomowym zapisaniu pełnego raportu.

### Zakończenie — 2026-10-27

Wszystkie etapy **GOTOWE**. Końcowy korpus: **168/168 źródeł zgodnych**, czyli
**501/501 pełnych planów** dla universal / fdd_expressive / adaptive_legato oraz
**1 niezmieniony błąd parsera** (`touhou4.mid`). Wszystkie 13 presetów mają osobną
bramkę **117/117 PASS**, obejmującą także warianty routingu i wyłączone urządzenia.
Nie zmieniano verifierów ani tolerancji porównań.

Końcowa walidacja: **1008 testów hosta PASS**, **170 testów frontendu PASS**,
TypeScript/Vite build i generator presetów PASS, guard **62 moduły PASS**.
Ostatni rebuild orchestra PASS: healthy, API HTTP 200, frontend i 16 hashy
plików produkcyjnych/testowych zgodne z checkoutem. Nie wykonano commitów.

[Zbiorczy raport](../reports/refactoring-next-verification-2026-10-27.json)
zawiera pokrycie, wersje narzędzi, hashe i ograniczenia.
[Raport czasu/pamięci](../reports/refactoring-next-performance-2026-10-27.json)
nie wykazuje regresji na trzech badanych wejściach; pomiary przy obciążeniu
korpusem nie uzasadniają obietnicy przyspieszenia.
[Archiwum wejściowego kodu](../reports/refactoring-next-source-2026-10-27.tar.gz)
zawiera 286 plików, każdy zweryfikowany względem manifestu SHA. MIDI pozostają
pod oryginalnymi ścieżkami zapisanymi w manifestach; brakujące wejście ma być
zgłaszane, nie zastępowane.

Odstępstwo organizacyjne: kosztowne korpusowe bramki etapów 1–3 domknięto wspólnie
na końcowej wersji, z dodatkową niezależną kontrolą 264 planów snapshotu etapu 1.
Zmiany miały wcześniej oddzielne testy i porównania 117 przypadków; snapshoty
zachowano do diagnozy ewentualnej różnicy. Zgodność 88 wejść lokalnych z pełnym
niezmiennym capture potwierdzono osobno. Nie ograniczono końcowego pokrycia.

Pozostały dług: aliasy prywatnych nazw allocator dla starszych konsumentów,
jawny istniejący wyjątek universal_recovery→compiler do fingerprintu oraz
złożoność samych heurystyk muzycznych i protokołu BLE. Ta runda upraszcza ich
granice i własność stanu; nie zmienia algorytmów, parametrów ani protokołu.
Błąd parsera pozostaje osobnym zadaniem.

Zakres dowodów: **offline/fikcyjne transporty i VIRTUAL**. Nie uruchamiano
fizycznych instrumentów, nie flashowano ESP32 i nie mierzono szyn ATX ani akustyki.
Kolejny agent powinien rozpocząć od nowych potrzeb i aktualnego stanu repozytorium,
bez ponawiania ukończonych etapów tego planu.

### Przygotowanie commita — 2026-10-28

Na zlecenie użytkownika zmiany utrwalono razem w Git. Kontrola staged diff
wskazała zbędne puste linie na końcu trzech nowych modułów allocation; usunięto je
przy potwierdzonej identyczności AST. Odświeżono hashe w raporcie i wdrożenie.
Wyniki walidacji zachowania powyżej pozostają aktualne. Commit opisuje zakres,
wyniki offline/VIRTUAL i brak prób fizycznych; identyfikator jest w historii Git.
