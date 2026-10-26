# Plan etapowej refaktoryzacji aplikacji

Data audytu: 2026-10-26. Punkt odniesienia: `a221286` na `main`.
Status: **plan przygotowany; żaden etap implementacji nie został wykonany**.

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
| 0. Baseline | DO ZROBIENIA | — |
| 1. Import MIDI | DO ZROBIENIA | — |
| 2. Kontrakty i presety | DO ZROBIENIA | — |
| 3. Scenariusze aplikacyjne | DO ZROBIENIA | — |
| 4. Stan i preferencje | DO ZROBIENIA | — |
| 5. Dane planowania | DO ZROBIENIA | — |
| 6. Pipeline aranżera | DO ZROBIENIA | — |
| 7. Frontend runtime | DO ZROBIENIA | — |
| 8. Domknięcie | DO ZROBIENIA | — |

Po każdym etapie dopisz krótki wpis:

- Data, SHA wejściowe i numer etapu.
- Zmienione odpowiedzialności i publiczne kontrakty.
- Polecenia testów, wyniki i lokalizacja raportu porównania.
- Wynik wdrożenia lub uzasadnienie, dlaczego nie było potrzebne.
- Odstępstwa, znane problemy, zakres niezbadany na fizycznym sprzęcie.
- Commit, jeśli był zlecony; następny etap i warunki jego rozpoczęcia.

Pierwszym przyszłym zadaniem implementacyjnym jest **wyłącznie etap 0**.
