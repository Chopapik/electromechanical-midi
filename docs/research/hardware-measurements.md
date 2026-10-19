# Obserwacje, pomiary i hipotezy sprzętowe

Rejestr dowodów, oddzielony od [bieżących parametrów](../HARDWARE_DEVICES.md)
i [połączeń](../HARDWARE_WIRING.md). Nie wykonywano nowych pomiarów podczas
porządkowania dokumentacji. „Nieznane” oznacza brak danych, nie potwierdzenie
bezpieczeństwa. Przy kolejnych testach zapisuj instancję, model, napięcie,
prąd, czas, temperaturę, metodę, orientację, firmware i konfigurację.

## FDD

Zachowany test **jednej fizycznej stacji**, w normalnej/docelowej orientacji,
z różnymi pozycjami głowicy. Po próbie powrót do TRACK0; delta kroków wykrywała
utratę pozycji. Dokładne pozycje i kolejność stress-testu nie zostały zapisane.
Źródło pierwotnego zapisu: [archiwum](../archive/hardware-and-history.md#fizyczna-kalibracja-fdd).

| Częstotliwość | Poprawne próby | Co można wnioskować |
| --- | --- | --- |
| 410 Hz | 38/40 (95%) | Roboczy górny punkt; 2 próby nie przeszły, nie pełna bezbłędność |
| 411–423 Hz | Brak liczbowego wyniku | Opisana strefa graniczna/niestabilna |
| 424 Hz | 0/40 | Brak poprawnych prób w tym teście |
| 425 Hz | 0/40 | Brak poprawnych prób w tym teście |
| 5 Hz | 5/5 bez utraty kroków | Mechaniczne minimum ≤5 Hz w tych warunkach, nie dolna granica muzyczna |

`stableHz=[130,410]` FDD1 zachowuje dolne 130 Hz jako metadane, **nie zmierzony
próg minimum**. Nie przenosi to wyniku 410 Hz na każdą z czterech stacji.
100 Hz i −12 są eksperymentem odsłuchowym:
[zapis eksperymentu](fdd-octave-experiment.md). Dawne 200–410 Hz w archiwum
opisuje wcześniejszą politykę, nie bieżący efektywny zakres.

## DVD

| Dowód | Wynik | Ograniczenie |
| --- | --- | --- |
| Obserwacja użytkownika przy VM 5 V | Nadmierne nagrzewanie silników DVD | Bez zapisanej temperatury, prądu i czasu; nie wyznacza liczbowego limitu |
| Proponowane VM 3,3 V | Robocza propozycja zasilania **silników przez DRV8833** | Brak kwalifikacji termicznej/prądowej, także dla sustainu |
| Sweep DVD1 50–500 Hz co 10 Hz, pitchRatio=1 | Pasma 50–120, 180–190, 270–300, 340–470 kroków/s | Jeden silnik, poprzedni tryb z limitem drogi 140 kroków i automatycznym nawrotem; nie aktualna whitelist ciągłego obrotu |
| Tuner gitarowy, 2026-10-11 | Komenda 200 Hz odczyt ~100 Hz; 500 Hz odczyt ~250 Hz | Możliwa detekcja oktawy/harmonicznej, brak pomiaru widmowego i indywidualnej kwalifikacji DVD1–3 |

Ostatnia obserwacja uzasadnia **hipotezę** `pitchRatio=0,5`, LOW confidence,
zapisaną pierwotnie dla DVD1–3. DVD4 miał wtedy 1,0. `steps/s=acousticHz/pitchRatio`:
żądane 200 Hz przy ratio 0,5 oznacza 400 kroków/s, 500 Hz oznacza 1000 kroków/s.
Nie jest to pomiar momentu, temperatury ani bezpieczeństwa tych częstotliwości.
Źródło metadanych sweepu i tunera: [instances.json](../../config/hardware-profiles/instances.json).
Ciągły tryb korzysta z innej interpretacji profilu niż ten sweep; oryginalne dane
pozostają zachowane, ale nie aktywują historycznych pasm ani 140 kroków.

Aktualizacja **2026-10-19** — użytkownik zgłosił identyczny typ silnika DVD3
i DVD4, lecz przy zadanych 440 Hz stroik wskazywał odpowiednio około 440 i 220 Hz.
Kod wysyłał tę samą wartość PLAY, ale profile wymuszały odpowiednio 880 i 440 kroków/s.
Symulacja produkcyjnego C++ potwierdziła tę różnicę; nie jest to pomiar fizycznych
impulsów ani dźwięku. Dla DVD4 dodano indywidualną korekcję `pitchRatio=0,5`
(HYPOTHESIS/LOW), aby żądane 440 Hz oznaczało 880 kroków/s jak dla DVD3.
Oczekiwany wynik akustyczny wymaga ponownego odsłuchu/stroika; nie wykonano nowej
próby fizycznej, analizy widma ani pomiarów prądu/temperatury. DVD1 jest innym
silnikiem i użytkownik zgłosił nieprawidłowe brzmienie; jego stare ratio pozostaje
niepotwierdzone. Korekcja DVD4 nie obejmuje DVD5–6: zachowano jawne ratio 1,0
i stan wyłączenia. Host wysyła PROFILE podczas konfiguracji, więc zastosowanie
korekcji DVD4 przez aplikację nie wymaga flashowania ESP32.

Najdłuższy ciągły odcinek DVD w software benchmarku Universal pełnej biblioteki:
**366,997 s (Ful Stop)**. W pierwszym korpusie 31 MIDI: **136,195 s (Fake Plastic Trees)**.
Źródło i definicja: [Universal](universal-arrangement.md).
To długości komend na jednej lane, **nie fizyczne próby ciągłego grzania**.

## HDD VCM

[Historyczny szkic HDD HIT](../../firmware/hdd_hit/hdd_hit.ino) zapisuje zasilanie
5 V i rezystancję cewki około 23,3 Ω. Nie ma identyfikacji i kompletnych pomiarów
prądu/temperatury dla wszystkich czterech obecnych VCM. Nie należy przenosić tego
napięcia na cały zestaw jako zweryfikowanej specyfikacji.
Czas fizycznego cyklu i zakres modelu opisują [urządzenia](../HARDWARE_DEVICES.md#hdd-vcm).
Referencyjne modele rezonansów w [badaniu teoretycznym](orkiestra-model-teoretyczny.md)
nie są widmem zmierzonym na odzyskanych dyskach.

## Speakery

Wcześniejszy opis zakładał dwa S8050 NPN; użytkownik skorygował oznaczenie
na **S8550 PNP** i zgłosił montaż: emiter do ATX 3,3 V, baza przez 330 Ω do
GPIO25/26 i 10 kΩ do emitera, kolektor przez 56 Ω (moc rezystora do potwierdzenia) do plusa głośnika,
minus do wspólnego GND. To deklaracja połączeń, bez potwierdzenia pomiarami.
Głośniki prawdopodobnie 8 Ω; impedancja/moc i pinout elementów niepotwierdzone.
Pierwszy montaż zawierał omyłkowo 47 kΩ zamiast planowanych 47 Ω; użytkownik
zastąpił go 56 Ω i wskazał to jako przyczynę ciszy. Nie wykonano pomiarów prądu
ani temperatury tego wariantu. Aktualny [schemat](../HARDWARE_WIRING.md#dwa-pc-speakery) opisuje PNP;
firmware ustawia HIGH dla wyłączenia i odwraca PWM obu kanałów.
Nie zarejestrowano prądu tranzystorów, temperatur ani kształtu sygnału na głośniku.
Aktualne sterowanie obejmuje tylko sprzętowy prostokąt z regulacją wypełnienia.

## Laboratory

Zapis próby kontrolera ESP32 z **2026-10-08**, przez ówczesny runtime BLE:
DVD1 392 Hz / 3 s, automatyczny i wcześniejszy STOP, odmowa 220 Hz,
pojedynczy HDD1 HIT, zamknięcie sesji podczas pracy i ponowne wejście bez autoplay.
Kontroler potwierdził uruchomienie i tokenowy ALL STOP. Stan końcowy przez WS
pojawił się po około 3,25 s od kliknięcia testu 3 s (z transportem i publikacją UI).
Nie flashowano firmware. To test komend/statusu kontrolera, nie pomiar akustyczny,
prądowy lub termiczny. Odmowa 220 Hz dotyczyła dawnych pasm DVD1,
nie obecnego trybu ciągłego. Obecna procedura: [testy](../HARDWARE_TESTING.md#laboratory).
