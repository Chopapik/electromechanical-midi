# Lokalne ślady awarii

Logi są w katalogu projektu `.runtime/diagnostics/`, wykluczonym z Gita. Nie publikujemy ich automatycznie. Docker zapisuje je przez bind mount, więc przetrwają odtworzenie kontenera. Ustawienia → Diagnostyka awarii pokazują stan zapisu i link do ostatniego raportu, także po restarcie. Błąd zapisu jest widoczny również w stopce aplikacji.

## Gdzie szukać

- `backend/events.jsonl`: polecenia użytkownika, ich zakończenie, zmiany połączenia, stan odtwarzania co sekundę, sesje przeglądarki, wersja źródeł backendu (SHA-256), incydenty.
- `backend/incident-<id>.json`: błąd, traceback bez lokalnych zmiennych, kontekst i ostatnie 100 zdarzeń. Kontekst obejmuje m.in. utwór, preset, pozycję, epokę, wyjście, wyciszenia, parkowanie i metryki czasu.
- `gateway/`: osobny rejestr natywnej bramy BLE, z historią zapisów transportu przy błędzie. Nowa obsługa zaczyna działać dopiero po następnym uruchomieniu bramy. W ramach zmian offline nie restartowano usługi BLE.
- `active.json`: znacznik trwającej sesji. Jeśli pozostał po poprzednim uruchomieniu, powstaje `unclean_shutdown`. To dowód braku prawidłowego zakończenia, **nie dowód przyczyny awarii**. Znacznik pozostaje również po błędzie zapisu.

API: `GET /api/diagnostics` oraz `GET /api/diagnostics/incidents/<id>`; dostęp lokalny taki jak do aplikacji. Nie udostępniać portu aplikacji publicznie. Identyfikatory raportów nie pozwalają odczytywać dowolnych ścieżek.

## Jak analizować

1. Zachowaj raport z Ustawień lub skopiuj odpowiedni plik i dzienniki przed ich rotacją.
2. Sprawdź utwór, preset, pozycję i kod błędu. `recent` pokazuje poprzedzające zdarzenia.
3. W obrębie sesji porządkuj po `seq` i czasie `monotonic`; zapis incydentów ma priorytet, więc kolejność linii nie musi być kolejnością zdarzeń.
4. Backend i gateway mają osobne sesje. Porównuj czas UTC z uwzględnieniem różnic zegarów; nie traktuj tego jako precyzyjnego pomiaru opóźnienia między procesami.
5. `occurredAt` w błędzie przeglądarki oznacza czas jej zegara; raport mógł dotrzeć po odzyskaniu połączenia.

Błędy przeglądarki (`error`, `unhandledrejection`) trafiają do kolejki localStorage, do 20 raportów, i znikają po potwierdzonym zapisie przez backend. Brak potwierdzenia może powodować duplikaty przy ponowieniu. Czyszczenie pamięci przeglądarki lub niedostępne localStorage może utracić tę kolejkę.

## Ograniczenia i odporność

Zapis dyskowy wykonuje osobny wątek. Kolejka zwykłych zdarzeń ma limit 512, incydentów 32; przepełnienie zwiększa widoczne w Ustawieniach liczniki. Dziennik rotuje przy 2 MB, zachowuje 4 kopie; pojedynczy większy wpis może przekroczyć próg. Zachowujemy 50 ostatnich raportów, ich historię obcinamy do budżetu 256 kB. Aktualny raport może być większy, jeśli sam kontekst przekroczy budżet. Przy zamykaniu czekamy do 3 sekund na opróżnienie kolejek.

Incydenty zapisujemy atomowo z `fsync` pliku; zwykłe zdarzenia są buforowane przez system operacyjny. Nagłe odcięcie zasilania lub SIGKILL może utracić końcówkę. Następny start wykryje pozostawiony znacznik, ale nie odtworzy brakującego stosu ani przyczyny. Nie jest to pełny monitoring zawieszeń procesu lub systemu operacyjnego. Awaria przed inicjalizacją rejestratora wymaga również logów kontenera. Błędy dysku są sygnalizowane, a nie ukrywane jako udany zapis.

Nie zapisujemy środowiska, obrazów firmware, klucza OTA ani lokalnych zmiennych stosu. Znane nazwy pól sekretów oraz popularne formy haseł/tokenów są maskowane. To nie gwarantuje usunięcia każdej informacji w dowolnej treści wyjątku: przed udostępnieniem raportu przejrzyj go. Nazwa utworu i ścieżki w tracebacku mogą identyfikować lokalne pliki.

## Walidacja offline

Testy obejmują restart i odczyt raportu, rzeczywiste nagłe zakończenie procesu testowego przez `os._exit`, rotację, retencję, blokujący/błędny zapis, przepełnienie kolejki, maskowanie sekretów, potwierdzenie raportu dopiero po zapisie i odczyt przez API. Frontend sprawdza zachowanie kolejki po przeładowaniu i nieudanym wysłaniu. Nie uruchamiano instrumentów ani testów fizycznego BLE.

Weryfikacja wdrożenia 2026-10-29: 1021 testów backendu i 175 testów frontendu przeszło; TypeScript i build Vite poprawne (pozostaje ostrzeżenie o dużym pakiecie JS). Kontener `orchestra` przebudowany z `ORCHESTRA_OFFLINE=1`, zdrowy; API potwierdza aktywną diagnostykę bez błędu zapisu i bez utraconych zdarzeń. Sprawdzono w przeglądarce sekcję diagnostyki i wyciszenia wyłącznie w Ustawieniach. Bez testów fizycznego BLE; natywna brama nie była restartowana.
