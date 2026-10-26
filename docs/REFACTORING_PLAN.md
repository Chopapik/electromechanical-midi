# Plan etapowej refaktoryzacji aplikacji

Data audytu: 2026-10-26. Punkt odniesienia: `a221286` na `main`.
Status: **zakończony — etapy 0–8 zweryfikowane 2026-10-26**.

Dokument jest instrukcją dla przyszłego agenta AI. Przed wykonaniem sprawdź
aktualny kod, historię i `AGENTS.md`: ścieżki oraz obserwacje mogą się zdezaktualizować.
Nie traktuj samego istnienia tego pliku jako polecenia rozpoczęcia implementacji.

## 1. Cel i granice

Poprawić podział odpowiedzialności, jawność kontraktów i możliwość ponownego
wykorzystania modułów. Zachować obecne brzmienie i zachowanie aplikacji.
Refaktoryzacja nie służy dostrajaniu algorytmów muzycznych.

Zachowujemy główny podział:

```text
MIDI → analiza/aranżacja → PerformancePlan → compiler → ExecutionTimeline
                                                      ↓
                                                    Player
                                                      ↓
                                                    Router
                                                 REAL / VIRTUAL
```

Docelowe odpowiedzialności:

| Moduł/obszar | Odpowiedzialność |
| --- | --- |
| Kontrolery HTTP/WebSocket | Walidacja komunikatów, uprawnienia transportowe, odpowiedzi i mapowanie błędów |
| Warstwa aplikacyjna | Scenariusze użytkownika, kolejność operacji, własność sesji, koordynacja usług |
| Biblioteka MIDI | Rozwiązywanie nazw, walidacja importu, zapis i metadane plików |
| Registry i profile | Katalog urządzeń i zwalidowane możliwości; zapis preferencji przez osobny magazyn |
| Aranżer | Deterministyczne decyzje muzyczne, artykulacja, rezerwacje i walidacja mechaniczna |
| Compiler | Konwersja planu na wspólny harmonogram tone/hit/stop |
| Player | Zegar, epoka, odtwarzanie, anulowanie i właściciel wykonania |
| Router | Wybór wyjścia i filtrowanie; STOP przechodzi również dla wyciszonych urządzeń |
| Wyjścia/transporty | Przekład poleceń, gotowość, potwierdzenia i stan konkretnego wyjścia |
| DeviceService | Koordynacja serwisu, zasilania, bezpiecznego uploadu i odzyskania BLE |
| Frontend | Prezentacja, działania użytkownika, klient komunikacji i lokalny silnik audio |
| Firmware | Wykonanie poleceń i lokalne zabezpieczenia urządzeń |

Nie dodawaj automatycznie baz danych, mikroserwisów, kontenera DI, magistrali
zdarzeń ani generycznych `BaseService`/`BaseRepository`. Proste funkcje, klasy
oraz małe kontrakty wystarczą. Nazwy proponowane niżej są orientacyjne.

## 2. Zasady wykonania dla agenta

1. **W jednym podejściu wykonaj tylko jeden etap z sekcji 5.** Domyślne polecenie
   „kontynuuj plan” oznacza pierwszy niedokończony etap. Po jego walidacji
   zatrzymaj się i przedstaw wynik. Kolejne etapy wymagają kolejnego polecenia,
   chyba że użytkownik wyraźnie zlecił określony szerszy zakres.
2. Etap 0 jest osobnym zadaniem. Nie łącz tworzenia punktu odniesienia ze zmianą
   kodu produkcyjnego. W większym etapie migruj po jednym scenariuszu/etapie
   pipeline'u i sprawdzaj go przed następnym.
3. Przeczytaj aktualne `AGENTS.md`, `git status`, różnice lokalne i ten dokument.
   Zachowaj niezacommitowane zmiany użytkownika. Nie resetuj repozytorium.
4. Przed edycją wskaż zakres bieżącego etapu i jego bramkę akceptacji.
   Nie wykonuj przy okazji formatowania całego repo ani poprawiania muzyki.
5. Jeżeli znajdziesz błąd wpływający na zachowanie, odróżnij jego naprawę od
   refaktoryzacji. Odtwórz go, opisz oczekiwaną różnicę i nie regeneruj wzorców
   tylko po to, żeby testy zaczęły przechodzić. Etap 1 obejmuje wskazany defekt
   nieużywanej metody importu; pozostałe zmiany funkcjonalne wymagają osobnego zakresu.
6. Po zmianach aplikacji wykonaj wymagane przez `AGENTS.md` przebudowanie
   `orchestra`, sprawdź zdrowie i faktycznie serwowaną wersję. Sama zmiana tego
   dokumentu nie wymaga przebudowy. Nie uruchamiaj odtwarzania REAL.
7. Commituj tylko na polecenie użytkownika lub w ramach wyraźnie udzielonego
   upoważnienia. Jeśli commit jest zlecony, preferuj jeden etap na commit;
   podaj co/po co zmieniono, wyniki testów i ograniczenia. Bez push bez zlecenia.
8. Uzupełnij dziennik w tym pliku: stan etapu, zmiany, testy, dowody zgodności,
   odstępstwa i następny krok. Po błędzie pozostaw etap otwarty.

## 3. Niezmienne wymagania

- Nie zmieniaj presetów, ich domyślnego wyboru, transpozycji, bramek, progów,
  limitów częstotliwości, gęstości HDD, alokacji ani zasad reinforcement.
- Zachowaj identyfikatory i adresację urządzeń, aktywność HDD3–4, tryb
  STRICT_TRACKS oraz istniejące wyjątki zgodności protokołu.
- REAL i VIRTUAL korzystają z tego samego ExecutionTimeline. Zachowaj
  intencjonalne różnice transportowe, np. lookahead audio przeglądarki.
- Zachowaj semantykę STOP, mute, seek, disconnect, epok i braku samoczynnego
  wznowienia. Zachowaj auto-homing i potwierdzenia przed ruchem.
- Zachowaj wyłączność operacji serwisowych, kontroli sesji audio/laboratorium,
  sprawdzanie Origin oraz potwierdzenie użytkownika przed POWER ON.
- Nie zmieniaj procedury bezpiecznego uploadu. Nie flashuj, nie włączaj ATX
  i nie wykonuj ruchu sprzętu w ramach weryfikacji refaktoryzacji.
- Nie zmieniaj firmware, map GPIO ani timingu STEP. Obecny podział core /
  protocol / adapter ESP32 pozostaje podstawą; jego przebudowa nie jest częścią planu.
- Zachowaj publiczne komunikaty, statusy, requestId, kody HTTP, nazwy presetów,
  zapisane preferencje i ich format, chyba że etap jawnie przewiduje zgodną migrację.
- Nie uznawaj testów offline/VIRTUAL za ocenę brzmienia REAL lub temperatury.

## 4. Obserwacje audytu do ponownego potwierdzenia

- `host/web/server.py` implementuje upload, mimo że `host/web/library.py`
  zawiera `save_upload()`. Nieużywana metoda odwołuje się do niezdefiniowanych
  `MAX_UPLOAD_BYTES`, `mido`, `io`; odtworzono `NameError`. Endpoint ją omija.
- Kontroler WebSocket bezpośrednio zarządza właścicielem audio i stanem runtime.
- `DeviceService._power()` bezpośrednio zmienia pola RealOutput oraz stan linku.
- `DeviceRegistry` łączy katalog/profilowanie z zapisem preferencji speakerów.
- Katalog presetów jest powielony w Pythonie, TypeScript i opcjach Settings.
- `useRuntime()` łączy transport, ACK, upload, zdarzenia firmware i audio.
- Etapy aranżera zmieniają wspólny plan; część informacji wykonawczych znajduje
  się w słowniku raportowym `plan.hardware`. Legato zależy od `fddExpressive.groups`.
- Sidecary reinforcement są adresowane indeksem `extra:N`; zmiana listy wymaga
  ręcznej synchronizacji indeksów. Compiler rozpoznaje Legato przez klucz raportu.
- `VirtualDeviceInstance` jest także modelem dla planowania, mimo nazwy i miejsca
  w module `playback/virtual.py`. Przed przeniesieniem sprawdź wszystkie ścieżki
  CLI, historyczne narzędzia i testy; nie uznawaj ich za martwe bez dowodu.

## 5. Kolejność etapów

### Etap 0 — Zapis punktu odniesienia

**Zakres:** inwentaryzacja i testy charakteryzujące; bez zmian produkcyjnych.

1. Zapisz SHA, stan drzewa, konfigurację i wersje narzędzi. Stan lokalny jest
   źródłem prawdy; nie porównuj bezrefleksyjnie z dawnym commitem.
2. Uruchom istniejące testy backendu, frontendu i build. Historyczny wynik
   to 836 testów hosta i 129 frontendu; nie jest to wymaganie liczby testów.
3. Zapisz listę komend HTTP/WS, odpowiedzi, kodów błędów oraz właścicieli
   mutowalnego stanu. Opisz kolejność istniejących blokad i oczekiwań na ACK.
4. Przygotuj mały, stały zestaw MIDI: syntetyczne przypadki + Bodysnatchers,
   Somebody That I Used to Know, No Surprises, utwór z długim tłem i gęstą
   perkusją. Identyfikuj pliki SHA-256, a nie samą nazwą. Brak pliku zgłoś;
   nie zastępuj go milcząco inną wersją. Nie dodawaj do Git całej lokalnej muzyki.
5. Dla wszystkich wspieranych presetów w tym zestawie zapisz wyniki planowania:
   zachowane/odrzucone source ID i powody, device ID, on/off, Hz, artykulację,
   reinforcement i skompilowaną kolejkę. Dodaj STRICT_TRACKS i urządzenia wyłączone.
6. Oddziel dane wykonawcze od diagnostyki i czasu obliczeń. Nie ukrywaj różnic
   float szeroką tolerancją. Dla czystych przenosin kodu oczekuj identycznych
   wartości i kolejności; istniejące tolerancje kompilatora pozostają niezmienione.

**Bramka:** powtarzalny baseline, opis znanych błędów i zestaw porównań możliwy
 do uruchomienia bez sprzętu. Zatrzymaj się po przedstawieniu baseline'u.

### Etap 1 — Jedna implementacja importu MIDI

**Zakres:** `host/web/library.py`, endpoint uploadu, testy biblioteki/API.

1. Przenieś do jednej operacji biblioteki walidację zawartości, wybór nazwy
   i zapis. Kontroler zachowuje ograniczone czytanie uploadu i odpowiedź HTTP.
2. Zachowaj zachowanie aktualnego endpointu: limit 5 MB, rozszerzenia,
   walidację przez MidiSource, odpowiedzi i obecne nazewnictwo przy kolizji.
   Nie przyjmuj odmiennej konwencji z nieużywanej `save_upload()` jako wzorca.
3. Usuń duplikat lub uczyń go delegującym adapterem, jeśli ma realnych odbiorców.
4. Biblioteka zgłasza błędy niezależne od FastAPI; kontroler mapuje je na HTTP.
   Nie twórz osobnego repozytorium wyłącznie dla jednego zapisu pliku.

**Testy:** poprawny import, uszkodzone/puste MIDI, limit rozmiaru, rozszerzenie,
kolizja nazwy, ścieżki wychodzące poza katalog, błąd zapisu i sprzątanie pliku
roboczego. Zachowanie działającego endpointu musi pozostać zgodne.

**Bramka:** pojedynczy używany importer, brak niezdefiniowanych nazw, brak
zależności biblioteki od HTTP; testy API i biblioteki przechodzą.

### Etap 2 — Katalog presetów i kontrakty komend

**Zakres:** walidacja API, deklaracje typów klienta, katalog presetów.

1. Ustal jedno źródło danych o presetach: identyfikator, etykieta, opis.
   Z niego korzysta walidacja backendu i UI; wybierz prosty mechanizm udostępnienia
   lub generowania, zgodny z obecną aplikacją. Bez nowego systemu pluginów.
2. Zdefiniuj wiadomości jako konkretne warianty komend z wymaganymi polami,
   zamiast dowolnego `action: string` + słownika. Zachowaj format na przewodzie.
3. Waliduj odbierane dane na granicy. Same typy TypeScript nie walidują JSON.
   Odróżnij komendy, ACK, snapshoty, błędy, audio i zdarzenia firmware.
4. Zdefiniuj wspólne kody błędów tam, gdzie już istnieją. Zachowaj surowy szczegół
   diagnostyczny i aktualną prezentację; nie przebudowuj wszystkich komunikatów naraz.

**Testy:** kompletność katalogu względem backendu/UI, nieznany preset/komenda,
brak pola, błędny typ, requestId, stare poprawne komunikaty i bezpieczna obsługa
niepoprawnej wiadomości. Testy `App`, ładowania MIDI i laboratoryjnych błędów.

**Bramka:** dodanie presetu nie wymaga niezależnej edycji kilku list;
komendy mają sprawdzany kontrakt. Harmonogramy pozostają identyczne z etapem 0.

### Etap 3 — Scenariusze aplikacyjne poza kontrolerem

**Zakres:** `host/web/server.py`, `host/runtime/application.py` i ewentualny mały
moduł scenariuszy. Nie przenoś całego dużego `if` do kolejnej klasy bez poprawy granic.

1. Migruj kolejno: play/pause/stop/seek, wybór wyjścia/mute, laboratorium,
   na końcu delegowanie do serwisu. Każda operacja ma jawnego właściciela/sesję.
2. Kontroler zachowuje HTTP/WS, Origin, serializację i wysłanie odpowiedzi.
   Reguły własności wykonania oraz kolejność operacji należą do warstwy aplikacyjnej.
3. Utrzymaj wyjątki współbieżności: zmiana wyjścia podczas planowania nie może
   czekać za całym obliczeniem. ACK audio i heartbeat nie mogą utknąć za STOP,
   który właśnie na ACK czeka. Nie serializuj wszystkiego jedną nową blokadą.
4. Testuj scenariusze również bez FastAPI i WebSocket, na atrapach wyjść.

**Testy:** `test_runtime`, `test_output_during_planning`, `test_auto_homing`,
`test_laboratory`, `test_atx_power`, `test_firmware_flow`; sesja innej przeglądarki,
disconnect, zajęty serwis, brak ACK i zmiana wyjścia w trakcie planowania.

**Bramka:** kontroler nie zmienia bezpośrednio stanu playera/wyjść; scenariusze
są używalne z innego interfejsu, a zasady wyłączności i STOP są zachowane.

### Etap 4 — Własność stanu urządzeń i zapis preferencji

**Zakres:** `DeviceService`, `RealOutput`, adapter linku i `DeviceRegistry`.

1. Zdefiniuj operacje właściciela stanu, np. obsługę potwierdzonego POWER OFF,
   utraty połączenia i unieważnienia konfiguracji. Przenieś do nich bezpośrednie
   zapisy pól wykonywane obecnie przez inne moduły.
2. Zachowaj rozróżnienie stanu logicznego od pomiaru napięcia i od UNKNOWN.
   Nie zmieniaj warunków uznania STOP/OFF za potwierdzone.
3. Wydziel mały magazyn preferencji speakerów z registry: wczytanie i atomowy
   zapis, z zachowaniem ścieżki środowiskowej, wartości i formatu JSON.
   Registry nadal odpowiada za walidację katalogu i parametrów.
4. Sprawdź kolejność blokad i obiegi błędów; nie przenoś oczekiwania na transport
   do nowego miejsca objętego blokadą bez testu współbieżności.

**Testy:** `test_atx_power`, `test_safe_upload`, `test_firmware_flow`,
`test_speaker_volume`, `test_runtime`; zapis zakończony błędem, brak BLE,
niepotwierdzony OFF, błąd uploadu i brak automatycznego POWER ON po recovery.

**Bramka:** każdy stan ma jednego właściciela, zewnętrzne moduły używają jego
operacji. Brak regresji plików preferencji i procedur serwisowych.

### Etap 5 — Jawne dane planowania i artykulacji

**Zakres:** modele planu/kontekstu oraz używający ich kod; bez zmiany kolejności algorytmów.

1. Wprowadź mały typowany kontekst dla grup FDD, efektywnych polityk i możliwości
   urządzeń. Przenieś zależność Legato od `hardware.fddExpressive.groups` do niego.
2. Rozdziel kontekst wykonawczy od raportowania. Zachowaj istniejący kształt
   raportów przez projekcję/adapter dla UI, benchmarków i istniejących odbiorców.
3. Nadaj extras stabilną tożsamość lub zwiąż artykulację bezpośrednio ze zdarzeniem.
   Migrację `extra:N` wykonuj przez adapter, bez zmiany kolejności poleceń ani
   semantyki source ID. Nie dodawaj losowych UUID do deterministycznego planowania.
4. Przekaż kompilatorowi jawne dane o łączeniu tonów; klucz diagnostyczny
   `fddLegato` nie powinien decydować o STOP. Zachowaj dokładnie obecne reguły
   stykających się tonów oraz tolerancję 1 ns i prawdziwe przerwy.
5. Nie wymuszaj niemutowalności całego planu. Określ, kto może zmieniać które dane.

**Testy:** indeksowanie i filtrowanie extras, brak sidecara, stabilne ID,
kompilacja STOP przy stykających się i rozdzielonych nutach, deterministyczność,
wszystkie istniejące testy Legato/Adaptive/Expressive i porównania etapu 0.

**Bramka:** usunięcie informacji wyłącznie diagnostycznej nie zmienia wykonania.
Pełne polecenia i decyzje muzyczne pozostają zgodne z baseline'em.

### Etap 6 — Czytelny pipeline aranżera

**Zależność:** etap 5 musi być zakończony.

1. Spisz faktyczną kolejność etapów każdego presetu, także wewnątrz
   `hardware_arranger.py`. Zachowaj ponowne walidacje wykonywane po recovery.
2. Wydziel nazwane etapy z określonym wejściem, wynikiem i dozwolonym zakresem
   zmian. Orkiestrator wybiera ich kolejność; nie zawiera szczegółów artykulacji.
3. Oddziel wybrany preset od współdzielonej strategii alokacji. Usuń konieczność
   chwilowego ustawiania `arrangementPreset='fdd_expressive'` dla innych presetów.
4. Migruj po jednej rodzinie presetów: bazowe/Universal, grupowe FDD,
   Expressive, następnie Legato i Adaptive. Po każdej wykonaj porównanie.
5. Jeżeli model `VirtualDeviceInstance` jest wspólnym modelem domenowym,
   przenieś go do neutralnego modułu z przejściowym importem zgodności.
   Nie usuwaj starszych CLI/eksperymentów bez sprawdzenia ich użycia.

**Testy:** mały baseline wszystkich presetów po każdej migracji; po zakończeniu
pełny korpus MIDI przed/po dla zmienionych ścieżek. Uruchom również testy starszych
alokatorów, STRICT_TRACKS, profili i firmware/protokołu dostępne offline.

**Bramka:** bez różnic muzycznych i wykonawczych; jawne zależności etapów;
nowa artykulacja nie wymaga dopisywania wyjątków w kilku niezależnych miejscach.

### Etap 7 — Podział runtime frontendu

**Zakres:** `web/src/runtime.ts` oraz jego odbiorcy i testy.

1. Wydziel klienta komunikacji: połączenie, ponawianie, requestId, ACK, timeouty
   i anulowanie oczekujących żądań. Użyj kontraktów z etapu 2.
2. Wydziel proces upload → planowanie i obsługę zdarzeń firmware. Hook React
   składa te elementy i dostarcza stan widokom.
3. Zachowaj pojedynczą instancję silnika audio, heartbeat, epoki, właściciela
   sesji i ACK anulowania. Odtwarzanie nie może powielać się po remoncie komponentu.
4. Usuń rozjazd między dwiema metodami wysyłania komend tylko przez jawną obsługę
   różnych potrzeb ACK. Nie każda wiadomość wymaga oczekiwania na odpowiedź.
5. Zachowaj układ i styl interfejsu. Wydzielaj komponenty, gdy mają własne
   zachowanie lub są używane wielokrotnie, a nie według liczby linii JSX.

**Testy:** cały frontend; szczególnie ładowanie MIDI, laboratory, ATX, firmware,
reconnect, timeout/ACK, odmontowanie, zmiana sesji, anulowanie audio i VirtualOutput.
Build TypeScript musi przejść. Smoke test interfejsu wyłącznie bez uruchamiania REAL.

**Bramka:** hook nie implementuje transportu i uploadu w jednym bloku;
interfejs i zachowanie audio pozostają zgodne.

### Etap 8 — Domknięcie i ochrona granic

1. Usuń przejściowe adaptery dopiero po migracji wszystkich odbiorców. Sprawdź
   importy, CLI, testy i dokumentację. Zachowaj badania i benchmarki historyczne.
2. Uaktualnij istniejące `docs/ARCHITECTURE.md`, `docs/ARRANGEMENT.md` i indeks,
   bez tworzenia równoległych opisów tej samej architektury.
3. Dodaj lekką kontrolę niezdefiniowanych nazw i rzeczywiście istotnych granic
   importów. Dobierz narzędzie do repo; nie uruchamiaj masowej zmiany formatowania.
4. Wykonaj pełne testy i końcowe porównanie korpusu z baseline'em, a po zmianach
   aplikacji wymagany rebuild/deploy. Raportuj znane błędy parsera osobno.

**Bramka:** brak nieuzasadnionych różnic w zachowaniu, dokumentacja zgodna z kodem,
jasna lista pozostawionego długu i dowody weryfikacji. Zakończ plan.

## 6. Wykonywanie testów i porównań

Z katalogu głównego repozytorium:

```sh
.venv/bin/python -m unittest discover -s host/tests -q
npm --prefix web test
npm --prefix web run build
```

Dla pojedynczego modułu testów (przykład):

```sh
PYTHONPATH=host:host/tests .venv/bin/python -m unittest test_runtime -q
```

Po zmianach aplikacji, zgodnie z aktualnym `AGENTS.md`:

```sh
docker compose up -d --build orchestra
docker compose ps
```

Sprawdź healthcheck oraz `/api/state` i serwowany frontend na porcie wynikającym
z Compose/`APP_PORT` (domyślnie 5173). Nie uznawaj samego udanego builda za wdrożenie.
Nie wysyłaj POWER ON ani poleceń ruchu. Używaj atrap w testach integracyjnych.

Istniejące `scripts/benchmark_universal.py` i
`scripts/benchmark_adaptive_legato.py` można wykorzystać jako narzędzia.
**Porównanie dwóch presetów nie zastępuje porównania tego samego presetu
przed i po refaktoryzacji.** Zachowaj oddzielne raporty baseline/kandydat,
identyczny manifest SHA, konfigurację i preferencje. Nie nadpisuj raportów
historycznych. Nie uruchamiaj obu wersji na sprzęcie.

Porównuj kompletne zdarzenia/polecenia, nie tylko liczbę nut, STOP lub hash pliku.
Przy hashach zachowaj możliwość wypisania pierwszej różniącej się komendy.
Wyłącz z porównania tylko jawnie wskazane pola diagnostyczne, czas pomiaru
oraz ścieżki lokalne; nie wyłączaj wysokości, czasów, artykulacji ani urządzeń.

Brak lokalnych plików, kompilatora C++, Dockera lub zależności zgłoś jako
ograniczenie walidacji. Nie oznaczaj niewykonanego sprawdzenia jako zaliczonego.
Nie ponawiaj pełnej biblioteki po każdej kosmetycznej zmianie; używaj wskazanych
bramek i poszerzaj testy przy nowych ryzykach.

## 7. Dziennik wykonania — uzupełnia agent

| Etap | Stan | Commit / dowód walidacji |
| --- | --- | --- |
| 0. Baseline | GOTOWE | 117/117 capture + verify; reports/refactoring-baseline-2026-10-26.jsonl.gz |
| 1. Import MIDI | GOTOWE | 59 testów biblioteki/API/runtime PASS; rebuild orchestra PASS |
| 2. Kontrakty i presety | GOTOWE | 106 backend, 154 frontend, build, generator i baseline13 PASS |
| 3. Scenariusze aplikacyjne | GOTOWE | 114 backend, 7 scenariuszy bez FastAPI, baseline13, deploy PASS |
| 4. Stan i preferencje | GOTOWE | 163 testy, baseline13 i rebuild PASS |
| 5. Dane planowania | GOTOWE | 903 host, 117/117 baseline, rebuild PASS |
| 6. Pipeline aranżera | GOTOWE | 138 testów, 117/117 baseline, 489/489 pełnych planów, rebuild PASS |
| 7. Frontend runtime | GOTOWE | 168 frontend, TypeScript/build, rebuild PASS |
| 8. Domknięcie | GOTOWE | 917 host, 168 frontend, guard57, generator/build/deploy; 489/489 planów i 1 niezmieniony błąd parsera |

Po każdym etapie dopisz krótki wpis:

- Data, SHA wejściowe i numer etapu.
- Zmienione odpowiedzialności i publiczne kontrakty.
- Polecenia testów, wyniki i lokalizacja raportu porównania.
- Wynik wdrożenia lub uzasadnienie, dlaczego nie było potrzebne.
- Odstępstwa, znane problemy, zakres niezbadany na fizycznym sprzęcie.
- Commit, jeśli był zlecony; następny etap i warunki jego rozpoczęcia.

Przy kontynuacji sprawdź dziennik poniżej i wybierz pierwszy nieukończony etap.
Nie zaczynaj ponownie etapu 0, jeśli jego artefakty i wyniki już istnieją.


### Wykonanie — 2026-10-26, start

Użytkownik wyraźnie zlecił cały plan w jednym zadaniu, etapami z testami;
pozwolił na kilku agentów. Etapy są wykonywane kolejno po ich bramkach,
bez oczekiwania na osobne polecenie po każdym z nich. Nie zlecono commitów.

Punkt wejściowy Git: `ea0b26c5ddad30a9dc5042dbd4e34daf6abdc0f8`.
Przed zamrożeniem baseline'u domknięto osobno zleconą poprawkę stałych par
Adaptive Legato. Jej różnica względem starej wersji jest jawna i opisana w
`reports/adaptive-legato-pairs.json`; główne nuty i harmonogramy innych urządzeń
zachowano. Refaktoryzacja ma zachować już poprawiony stan, nie przywracać
wcześniejsze niepełne wzmocnienia par.

Środowisko początkowe: Python 3.14.8, Node v24.10.0, npm 11.6.0.
Weryfikacja poprawki: pełny host 840 PASS, następnie końcowe 16 testów Adaptive
PASS; frontend 129 PASS, build PASS. Kontener przebudowany, healthy;
serwowany bundle `/assets/index-7fLkdD2C.js` zawiera opis stałych par.
Bez uploadu firmware, POWER ON ani prób fizycznych.


### Etap 0 — zakończony

`reports/refactoring-baseline-2026-10-26.jsonl.gz`: 117 przypadków, 64 519
zdarzeń głównych i 85 684 komendy. Capture i niezależny verify: 117/117 PASS.
Manifest zawiera SHA oryginalnych MIDI i jawnych 48-sekundowych wycinków:
Bodysnatchers, Somebody That I Used to Know, No Surprises, The National Anthem,
Counting Stars; do tego dwie syntetyczne próbki, wszystkie 13 presetów i
warianty STRICT_TRACKS/wyłączonych partnerów. Brak pomiarów akustycznych.
Preferencje speakerów są izolowane, a konfiguracja zapisana w artefakcie.
SHA-256 artefaktu: `7140fcdfcd094c5ec3a571797e6c62227199655aa664e147d254b89953826948`.
Audyt API, właścicieli stanu i blokad: `docs/research/refactoring-baseline.md`.
Narzędzie `scripts/refactoring_baseline.py` ma 4 testy; verify wskazuje pierwszą
różnicę i porównuje float dokładnie. Metadane Git nie blokują refaktoryzacji.

### Etap 1 — zakończony

Jeden importer `MidiLibrary.save_upload`, błędy domenowe niezależne od FastAPI,
mapowanie HTTP/WS w kontrolerze. Zachowano limit 5 MB, MidiSource, odpowiedzi,
konwencję nazw stem-N.mid i sprzątanie plików roboczych. 59 testów biblioteki,
API, runtime i przełączania wyjścia podczas planowania PASS. Rebuild orchestra PASS.

Jawna naprawa poza czystą zmianą struktury: odtworzono upload do wiszącego
symlinku, który zapisywał poza biblioteką. Nowy zapis wyłączny `xb` traktuje
symlink i równoległy zapis jako zajętą nazwę; regresja jest pokryta testem.
Nie zmieniono planowania MIDI, protokołu ESP32 ani zasilania.


### Etap 2 — zakończony

Kanoniczny katalog `host/arrangement_presets.py` i generowany plik TypeScript
z `scripts/generate_preset_catalog.py --check`. Kolejność ID bazowego kontraktu
pozostała identyczna; kolejność UI jest jawnie określona osobno.
`host/web/contracts.py` i `web/src/contracts.ts` definiują oraz sprawdzają
wiadomości. Format poprawnych komend/odpowiedzi zachowany, błędny JSON lub
niewłaściwy kształt danych daje kontrolowany błąd bez utraty sesji. ACK audio,
sync i wyjątek output podczas planowania pozostają poza zwykłą kolejką.

Wyniki: 100 istniejących fokusowych testów backendu i 6 nowych PASS;
154 testy frontendu PASS, TypeScript/Vite build PASS, generator --check PASS;
13/13 baseline fixture-phrases/AUTO PASS. Rebuild po etapie 2 PASS.
Testy nie wykonują operacji na fizycznym sprzęcie.


### Etap 3 — zakończony

`Application` ma jawne metody scenariuszy odtwarzania, laboratorium, serwisu,
audio, heartbeatów i cyklu życia. Kontroler mapuje komunikaty i Origin;
nie zmienia już ownera ani stanu playera/wyjść bezpośrednio. Wyjątek output
podczas planowania oraz natychmiastowa ścieżka audio_ack/sync są zachowane.
Disconnect nadal wykonuje STOP przed upływem dzierżawy audio.

114 fokusowych testów backendu PASS, w tym 7 nowych scenariuszy bez FastAPI/WS,
testy zmiany wyjścia podczas planowania oraz ACK/sync podczas STOP. Mały baseline
wszystkich 13 presetów AUTO PASS. Rebuild orchestra po etapie 3 PASS.
Kolejny etap ogranicza bezpośrednie zmiany stanu wewnątrz usług aplikacyjnych.


### Etap 4 — zakończony

RealOutput udostępnia power/detach/home_all i unieważnianie konfiguracji;
adapter linku unieważnia logiczny stan POWER i odniesienie FDD. DeviceService
nie zapisuje już bezpośrednio tych pól. `SpeakerSettingsStore` przejął wczytanie
i atomowy zapis preferencji, z zachowaniem środowiska, ścieżki i formatu JSON.

163 testy serwisu/POWER/safe upload/firmware/preferencji/runtime/homingu/lab/BLE
PASS; baseline 13 presetów AUTO PASS; rebuild orchestra PASS.

Dwie jawne korekty współbieżności, pokryte testami: connect nie trzyma już
service.lock podczas oczekiwania na player.lock lub ACK; kolejność zagnieżdżeń
jest player→service. Stara sesja przeglądarki po swojej dzierżawie nie czyści
właściciela audio, jeśli w tym czasie przejęła go nowa sesja.
Nie osłabiono potwierdzeń STOP/POWER ani procedury uploadu; brak testów fizycznych.


### Etap 5 — zakończony

`PlanningContext` przechowuje grupy FDD, możliwości wykonawcze i flagę łączenia
tonów. Kompilator nie rozpoznaje Legato po kluczu raportowym. Dodatkowe nuty
mają stabilne wewnętrzne powiązania z artykulacją, także dla identycznych
wartości zdarzeń i filtrowania/replacementów. Kompatybilna projekcja `extra:N`
i publiczna serializacja pozostają bez zmian. Legacy producers są adaptowane
na granicy alokacji; dalsze transformacje używają helperów powiązań.

161 testów fokusowych PASS, pełny backend 903 PASS; niezależny pełny verify
117/117 PASS. Rebuild aplikacji po etapie 5 PASS. Zmiany bez pomiarów fizycznych.

### Etap 6 — zakończony

`runtime.arranger` jest publicznym wejściem do nazwanych kroków w
`runtime.planning_pipeline`. `ArrangementStrategy` jawnie oddziela wybrany
preset od współdzielonej alokacji; tworzy osobną konfigurację zamiast chwilowo
zmieniać wejściowy wybór. Kolejność etapów i ponowne walidacje po recovery
pozostają takie same. Wspólny model urządzeń/profili jest w
`playback.device_models`, ze zgodnymi importami starego `playback.virtual`.

138 testów pipeline/modelu/preview/recovery/FDD/runtime PASS; 117/117 przypadków
baseline identycznych, w tym wszystkie 13 presetów i warianty STRICT/disabled.
Trzy testowe patchpointy przeniesiono z dawnego modułu arrangera do właściciela
alokacji w pipeline, bez zmiany ich asercji. Rebuild po etapie 6 PASS.
Pełny korpus: 483 ścieżki / 164 SHA-unikalne MIDI; końcowy verify potwierdził
489/489 planów w Universal/Expressive/Adaptive oraz jeden niezmieniony błąd
parsera. Snapshot pełnego korpusu zamrożono po etapach 1–4, przed zmianami
planowania z etapów 5–6; wcześniejszy mały baseline obejmuje wszystkie etapy.


### Etap 7 — zakończony

`RuntimeClient` odpowiada za WS, reconnect, heartbeat, pending requests, ACK,
timeouty i disposal; `MidiImportProcess` za STOP→import→plan oraz sprzątanie;
`FirmwareEvents` za historię serwisu. `useRuntime` składa je z jednym silnikiem
audio i stanem widoków. Stare callbacki zamkniętego socketa są ignorowane.

168 testów frontendu PASS, TypeScript/Vite build PASS, rebuild orchestra PASS.
Nowe testy obejmują StrictMode, brak powielonych heartbeatów, timeout 120 s,
requestId, disposal, upload po odmontowaniu, stary socket/właściciel i historię.
Jawna naprawa reconnect: `VirtualOutput.resetSession()` kasuje stare epoki i
próbkę synchronizacji po hello, zachowując odblokowany kontekst audio. Dzięki
regresji epoch20→nowy backend0/1 przeglądarka nie milknie po restarcie backendu.
Pakiety z poprzedniej epoki w tej samej sesji nadal są odrzucane.


### Etap 8 — zakończony, 2026-10-26

Końcowy raport: [refactoring-verification-2026-10-26.json](../reports/refactoring-verification-2026-10-26.json).
Pełny backend: 917 testów PASS (w tym dostępne testy offline C++/protokołu i
adaptera). Frontend: 168 testów PASS, TypeScript/Vite build PASS. Guard AST/
symtable obejmuje 57 modułów; generator katalogu presetów `--check` PASS.
Sprawdzono lokalne odnośniki zmienionej dokumentacji i `git diff --check`.

Mały baseline: 117/117 dokładnie zgodnych przypadków we wszystkich 13 presetach,
z wariantami AUTO/STRICT_TRACKS i wyłączonymi partnerami. Pełny korpus: 483
ścieżki, 164 unikalne SHA; 163 poprawne MIDI × 3 strategie = 489/489 identycznych
planów i kolejek. Porównanie obejmuje pełne czasy, wysokości, urządzenia,
sidecary, extras i uporządkowane komendy, bez zaokrąglania float. `touhou4.mid`
ma ten sam błąd parsera `list index out of range` przed i po zmianach; nie
zaliczono go do 489 udanych planowań. Referencja:
[pełny korpus](../reports/refactoring-corpus-before-2026-10-26.json).

Aktualne odpowiedzialności i granice opisuje [ARCHITECTURE.md](ARCHITECTURE.md),
a kolejność przekształceń muzycznych [ARRANGEMENT.md](ARRANGEMENT.md).
Po ostatnich zmianach aplikacji przebudowano i uruchomiono `orchestra`; healthy,
`/api/state` 200. Serwowany `/assets/index-B2hB1m-r.js` jest bajtowo identyczny
z lokalnym buildem (SHA-256 w raporcie). Smoke test `/settings` pokazał poprawny
stan i katalog urządzeń bez uruchamiania REAL. Dalsze zmiany dotyczyły raportu
i dokumentacji, więc nie wymagały kolejnej przebudowy aplikacji.

Pozostawiony dług jest jawny: diagnostyczny import `compile_plan` przez
`universal_recovery`, stare eksporty modelu z `playback.virtual` oraz projekcja
`extra:N` dla zgodności odbiorców. Guard nie zastępuje pełnej analizy typów,
przepływu ani współbieżności. Zamrożone źródła korpusu są w lokalnym `/tmp`;
raport zapisuje ich manifest SHA, ale ich przetrwanie wymaga osobnej kopii.
Pozostało ostrzeżenie deprecacyjne Starlette/httpx.

Plan zakończony. Brak zmian firmware lub konfiguracji, uploadu ESP32, POWER ON,
ruchu urządzeń i odsłuchów fizycznych. Wyniki nie potwierdzają brzmienia ani
bezpieczeństwa termicznego. Zmiany pozostawiono niezacommitowane; bez push.


### Podział na commity — na późniejsze polecenie użytkownika

Po zakończeniu weryfikacji użytkownik zlecił zapis wszystkich zmian. Podzielono
je na osiem logicznych commitów; wcześniejsze stwierdzenie o braku commitów
opisuje stan w chwili zamknięcia etapu 8. Zapis historii nie zmienił plików
aplikacji ani konfiguracji, więc nie wymagał kolejnego rebuilda kontenera.

| Commit | Zakres | Sprawdzenie wyodrębnionej wersji |
| --- | --- | --- |
| `febdfe9` | Stałe pary Adaptive Legato | 33 testy PASS |
| `2a42a24` | Jeden importer MIDI i zapis plików | 59 testów PASS |
| `c753d46` | Katalog presetów i kontrakty | 65 backend + 25 frontend, build PASS |
| `ce5a20f` | Scenariusze i własność stanu runtime | 138 testów PASS |
| `e031887` | Narzędzia i zamrożone baseline’y | 4 testy narzędzia PASS |
| `297f690` | Kontekst i etapy planowania | 906 testów hosta PASS |
| `03d2dc5` | Podział runtime frontendu | 168 testów, build PASS |
| Końcowy commit tego dokumentu | Kontrola architektury, dokumentacja i raport | 917 testów hosta, guard, generator, odnośniki PASS |

Wersje etapów sprawdzono w osobnym katalogu z tymi samymi lokalnymi MIDI;
nie przełączano działającej aplikacji na pośrednie rewizje. Opisy commitów
zawierają cel, zakres, wyniki oraz ograniczenie do testów offline/VIRTUAL.
Bez push, uploadu ESP32, POWER ON i prób fizycznych.
