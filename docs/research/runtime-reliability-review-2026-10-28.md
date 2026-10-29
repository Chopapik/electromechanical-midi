# Przegląd responsywności i cyklu wykonania — 28.10.2026

Zakres: analiza kodu i testy offline. Bez połączenia z fizycznym BLE, uruchamiania
instrumentów, sterowania ATX i flashowania. Prace wykonano na `main`.

## Najważniejsze ustalenia i poprawki

| Problem | Skutek | Poprawka |
| --- | --- | --- |
| `Application.set_preset` wykonywało aranżację pod `Player.lock` | Snapshot, tick odtwarzacza i STOP czekały na CPU; interfejs nie dostawał aktualnego stanu | Prywatna kopia konfiguracji, obliczenia poza blokadą, krótka publikacja gotowego wyniku; jawne etapy planowania |
| Globalna kolejka komend obejmowała STOP | STOP mógł czekać za przygotowaniem MIDI; wcześniejsze Play mogło wykonać się później | STOP omija kolejkę operacji, unieważnia oczekujące komendy oraz zastosowanie trwającego planu |
| `useRuntime.send` nie oczekiwało skorelowanego ACK dla zwykłych operacji | Brak natychmiastowego spinnera, wielokrotne kliknięcia przed odpowiedzią | Lokalne stany oczekiwania, ACK/error, ograniczenie powtarzanych operacji; etapy widoczne we wspólnej stopce |
| `Player.snapshot` budowało listy czasów wszystkich komend w każdej próbce | Koszt liniowy względem długości utworu pod blokadą odtwarzacza, około 20 razy/s | Indeksy czasów budowane przy ładowaniu; wyszukiwanie binarne w gotowych listach |
| Wysyłanie stanu do przeglądarek było sekwencyjne i bez limitu oczekiwania | Jeden wolny klient mógł opóźnić pozostałych, w tym komunikaty audio | Równoległe wysyłanie do klientów, ograniczony czas oczekiwania i zamykanie przeciążonego połączenia |
| Komendy tworzyły nieograniczoną liczbę oczekujących zadań | Nadmiar żądań mógł zalegać i wykonywać się po zamknięciu sesji | Limit zadań, zachowany dostęp do STOP/zmiany wyjścia, kontrola sesji przed wykonaniem zakolejkowanego polecenia |
| Tłumaczenie błędów urządzeń było dostępne wyłącznie w Laboratory | Na ekranie orkiestry użytkownik widział surowy błąd lub nie rozumiał przyczyny | Wspólne objaśnienia TRACK0 i wariantów overrun; szczegóły techniczne pozostają dostępne |
| Homing przechowywał pierwotną listę wszystkich urządzeń aż do końca | Timeout nie odróżniał stacji gotowych od nadal niepotwierdzonych | Lista aktualizowana po kompletnych odpowiedziach STATUS; nazwy niepotwierdzonych stacji w timeout i stanie |
| Kolejne Play/STOP usuwały bieżący komunikat błędu | Trudno odtworzyć, przy jakim utworze i pozycji wystąpiło przerwanie | `lastFailure`: kod, surowy komunikat, pozycja, epoka, wyjście, plik, preset, dane homingu i czasów; dostępne w stanie/API i stopce |
| Wyciszanie wymagało klikania każdego urządzenia | Uciążliwa obsługa zespołów | Jedno żądanie `mute_group`, walidacja całej grupy, zamknięcie wszystkich bramek przed STOP poszczególnych kanałów |

Grupy UI, wyłącznie w Settings obok indywidualnych wyciszeń: wszystkie FDD, FDD 1–4, FDD 5–8, DVD, HDD, speakery. To grupy
fizycznych wykonawców; nie są automatycznym rozpoznaniem partii melodii/basu.
Włączenie grupy otwiera bramki dla kolejnych zdarzeń, bez ponownego odgrywania
zaległych nut. Zmiana mute nie przelicza aranżacji.

## Co oznacza BLE overrun i przypadek Bad Apple

Istniejąca [diagnoza z 26.10](ble-overrun-diagnosis.md) dokumentuje przerwę
około 251 ms wewnątrz potwierdzanego zapisu GATT, przy pustej kolejce i samym
PING. Historyczna obserwacja Bad Apple dotyczyła także błędu z zerową kolejką.
To dowód dotyczący tamtej wersji i sesji, nie nowy pomiar obecnego wykonania.

Aktualny transport obsługuje potwierdzenie wykonania pakietu przez firmware.
Nadal ma ograniczony wiek komendy i czas ACK. Przekroczenie kończy sesję,
żeby nie odtwarzać zaległych nut. Następne Play może zadziałać po odbudowie
połączenia i potwierdzeniu STOP; nie dowodzi to usunięcia źródła problemu.

Nie zwiększano limitu 250 ms ani nie wyłączano mechanizmów zatrzymania.
Nie ma podstaw, by po samym przeglądzie software stwierdzić, że obecne przerwania
radia zostały usunięte. Diagnostyka bramki nadal rozróżnia kolejkę, worker,
pętlę BLE, zapis i oczekiwanie ACK. `lastFailure` pomaga powiązać problem z utworem.

## Pozostające ograniczenia architektoniczne

- REAL wysyła polecenia do wykonania na bieżąco. Brak bufora muzycznego ze
  zsynchronizowanymi terminami wykonania w ESP32 oznacza zależność od jitteru
  hosta, stosu BLE i radia. Taki bufor wymaga osobnego projektu zegarów,
  epok, STOP i watchdoga oraz walidacji urządzeń.
- Planowanie działa w wątku Pythona. Zwolnienie `Player.lock` przywraca dostęp
  do stanu, ale nie daje izolacji CPU jak osobny proces. STOP odrzuca wynik;
  nie zabija trwających obliczeń. Stan jasno mówi o anulowaniu zastosowania planu.
- Konfiguracja sprzętu i bariery potwierdzeń nadal wymagają krótkiej wyłączności
  wykonania. Lokalny spinner sygnalizuje oczekiwanie już przed odpowiedzią serwera.
- Stan ostatniego błędu jest pamięciowy: restart serwera go usuwa. Ślady bramki
  mają oddzielny cykl życia i nie są automatycznie dołączane do rekordu UI.
- Etapy przygotowania nie są procentowym postępem algorytmu; nie podajemy
  fikcyjnej wartości procentowej ani czasu zakończenia.
- Duży pakiet frontendu (w tym VexFlow) nadal powoduje ostrzeżenie bundlera.
  Podział pakietu może poprawić pierwsze ładowanie, ale nie rozwiązuje latencji BLE.

## Weryfikacja

Dodano regresje obejmujące responsywny snapshot/STOP w trakcie planowania,
odrzucenie spóźnionego planu i zakolejkowanego Play, zachowanie starego planu
po błędzie, zamknięcie bramek całej grupy mimo błędu STOP, trwały kontekst błędu,
wyświetlanie oczekiwania przed ACK i błędy homingu poza Laboratory.
Testy transportu używają atrap BLE i symulowanego parsera firmware C++.
Weryfikacja backendu: **1014 testów PASS**, w tym testy symulowanego BLE/TCP
wymagające lokalnego nasłuchu poza sandboxem. Frontend: **173 testy PASS**,
także po końcowej korekcie umiejscowienia wyciszeń. Build TypeScript/Vite PASS.
Kontener przebudowano i potwierdzono stan healthy, `ORCHESTRA_OFFLINE=1`,
brak połączenia ESP32 oraz nowe pola API i nowy zasób JavaScript.

Aktualizacja 29.10.2026: grupowe wyciszenia pozostają wyłącznie w ustawieniach,
zgodnie z doprecyzowaniem użytkownika. Główny ekran pokazuje stan instrumentów.

Uruchomienie lokalnej aplikacji do weryfikacji: `ORCHESTRA_OFFLINE=1 docker compose up -d --build orchestra`.
To ustawienie dotyczy utworzonego kontenera; ponowne uruchomienie Compose bez
tej zmiennej korzysta z domyślnej polityki konfiguracji środowiska.
