# Połączenia i zasilanie

Docelowy układ: ESP32-WROOM-32 (płytka 38-pin CP2102), **6 × SN74HC595N**,
**8 × moduł DRV8833**, **8 FDD**, **6** dwufazowych bipolarnych stepperów DVD, 4 cewki HDD VCM oraz
2 pasywne PC Speakery sterowane przez osobne S8050.
Firmware przygotowuje **8 FDD i 6 DVD**; host ma katalog 20 pozycji, z których aktywne pozostają **4 FDD, 4 DVD, 4 HDD i 2 speakery**.
Dotychczasowe testy logiki dotyczą istniejących kanałów, nie fizycznej kwalifikacji
całego docelowego zestawu 20 urządzeń. FDD5–8 i DVD5–6 są planowane do przyszłych
testów, bez potwierdzonego podłączenia/kwalifikacji; startują wyłączone.
SR6 i pozostałe niezmierzone wyjścia również wymagają pomiaru.
Nowe okablowanie powstaje od zera: DVD/HDD zmieniają Q względem starszej mapy.
**Nie uruchamiaj tego firmware z poprzednim okablowaniem DVD/HDD.**
Kompatybilne STATUS nie identyfikuje rewizji połączeń; sprawdzenie mapy jest ręczne.
Numery GPIO nie są numerami pozycji na złączu płytki ESP32.
Numery pinów 74HC595 poniżej dotyczą DIP-16; oznaczenia DRV8833 dotyczą
funkcji na module, a nie numerów nóżek układu scalonego.

Źródła mapowania: [rdzeń firmware](../firmware/controller/include/orchestra_core.h),
[adapter ESP32](../firmware/controller/src/esp32/main.cpp),
[inventory](../config/devices.json). Parametry i kwalifikacja:
[urządzenia](HARDWARE_DEVICES.md); kolejność uruchamiania:
[testy](HARDWARE_TESTING.md). Dokument opisuje połączenia logiczne całego układu;
nieznane wartości elementów i zgodność poziomów trzeba potwierdzić przed
zasileniem odpowiedniej części. Nie ma zatwierdzonej listy konkretnych modeli modułów.

## Zasilanie

| Obwód | Napięcie / miejsce podania | Status |
| --- | --- | --- |
| ESP32 | USB płytki developerskiej | Nie łącz dodatniej szyny zasilania ESP32 z dodatnią szyną ATX |
| 6 × SN74HC595N i pull-upy logiczne | 3,3 V z ATX, wspólna masa z ESP32 USB | Osobna szyna logiki; nie łącz jej z pinem 3V3/5V/VIN zasilanej USB płytki ESP32 |
| FDD | Osobne 5 V do złącza zasilania napędu | Bieżące założenie układu; sprawdź model i orientację wtyku |
| DVD stepper | Proponowane 3,3 V **na VM DRV8833 #1–6** | Robocze napięcie zasilania silników, wymaga pomiaru temperatury i prądu; brak potwierdzonego limitu ciągłej pracy |
| HDD VCM | Osobne VM DRV8833 #7–8, do ustalenia | Brak zweryfikowanego napięcia/prądu dla kompletu cewek; zapis testu 5 V i ~23,3 Ω znajduje się w [badaniach](research/hardware-measurements.md#hdd-vcm) |
| PC Speaker / FX | Osobna szyna V_SPK, do ustalenia | Nieznany prąd obciążenia i rezystory bazowe S8050; nie zasilać głośnika z GPIO |

W teście samej logiki zasil ESP32 przez USB, a rejestry ze sprawdzonej szyny
3,3 V ATX. Połącz masy zasilaczy, ESP32, rejestrów, napędów i sterowników. Wspólna masa
nie oznacza połączenia dodatnich szyn, również dwóch niezależnych źródeł nominalnie 3,3 V. Prąd silników
prowadź osobnymi przewodami do zasilaczy; nie przez regulator 3,3 V ESP32 ani
cienkie mostki masy logiki. Sprawdź przerwy w szynach płytek stykowych.

Dodaj odsprzęganie zasilania przy układach: 100 nF przy każdym 74HC595 oraz
kondensatory VM zgodne z dokumentacją konkretnego modułu DRV8833 i długością
przewodów. To zalecenia projektowe producentów, nie wynik pomiaru tej instalacji.
Zasilacze, przekroje, zabezpieczenia i nastawy ograniczenia prądu wymagają doboru
po identyfikacji obciążeń. Samo 3,3 V nie dowodzi bezpiecznego prądu DVD.

## Sterowanie ATX przez PS_ON#

Ustalone połączenie, osobny S8050 względem dwóch tranzystorów speakerów:

```text
GPIO19 ── 2,2 kΩ ── baza S8050
                     │
                  47–100 kΩ
                     │
wspólne GND ────── emiter
ATX PS_ON# (zielony) ─ kolektor
```

GPIO19 HIGH włącza tranzystor i zwiera aktywne LOW PS_ON# do GND: **ATX ON**.
GPIO19 LOW: **ATX OFF** jako żądanie logiczne. Rezystor baza–emiter utrzymuje
tranzystor wyłączony podczas resetu/wysokiej impedancji GPIO. Zweryfikuj rzeczywisty
pinout posiadanego S8050; samo oznaczenie nie ustala kolejności nóżek obudowy.
**Nie podłączamy PWR_OK, ADC ani dodatkowego wejścia pomiarowego. GPIO27 pozostaje LED.**

ESP32 pozostaje zasilany z USB, gdy główna szyna 3,3 V ATX zasilająca 74HC595
jest wyłączona. Wyjścia ESP32 DATA/CLOCK/LATCH oraz /OE oraz pull-upy mogą wtedy
pracować względem niezasilonych rejestrów: istnieje ryzyko zasilania wstecznego
przez wejścia, nieustalonego /OE i utraty zawartości rejestrów. Nie łącz dodatnich
szyn USB/ESP32 z ATX. Sam POWER OFF, rezystor /OE ani wysłanie ramki STOP
**nie rozwiązują izolacji domen zasilania**. Dobór separacji/buforów i kontrola
kolejności zasilania wymagają osobnej weryfikacji elektrycznej, przed użyciem obciążeń.

Firmware startuje z GPIO19 LOW i nie zapisuje ON. Przy POWER ON zatrzymuje
instrumenty, ustawia HIGH, czeka robocze 100 ms i ponownie wysyła ramkę STOP.
To opóźnienie programowe, nie potwierdzenie prawidłowego narastania szyn ani
rozwiązanie powyższego problemu. Przy POWER OFF najpierw zatrzymuje wszystkie
instrumenty, potem ustawia LOW; FDD tracą potwierdzenie HOME. Potwierdzenie
komendy ani odczekanie czasu nie oznacza pomiaru zaniku napięcia.

## GPIO ESP32

| GPIO | Połączenie |
| ---: | --- |
| 23 | SER pin 14 pierwszego 74HC595: DATA |
| 18 | SRCLK pin 11 wszystkich 74HC595: CLOCK |
| 22 | RCLK pin 12 wszystkich 74HC595: LATCH |
| 21 | /OE pin 13 wszystkich 74HC595; zewnętrzny pull-up 10 kΩ do 3,3 V |
| 34 | FDD1 TRACK0, pin 26 złącza sygnałowego |
| 35 | FDD2 TRACK0, pin 26 |
| 36 | FDD3 TRACK0, pin 26 |
| 39 | FDD4 TRACK0, pin 26 |
| 32 | FDD5 TRACK0, pin 26; nowy kanał |
| 33 | FDD6 TRACK0, pin 26; nowy kanał |
| 16 | FDD7 TRACK0, pin 26; nowy kanał |
| 17 | FDD8 TRACK0, pin 26; nowy kanał |
| 25 | R_B1 → baza S8050 Q1 → sterownik głównego PC Speakera |
| 26 | R_B2 → baza S8050 Q2 → sterownik PC Speaker FX |
| 19 | 2,2 kΩ → baza osobnego S8050 ATX; kolektor do PS_ON#, emiter do GND |
| 27 | Opcjonalna dioda testowa: 330 Ω → anoda LED, katoda → GND |
| 1 / 3 | UART0 / USB-Serial, pozostawione do programowania i diagnostyki |

TRACK0 jest aktywne LOW. **Każde z ośmiu wejść ma zewnętrzny pull-up do 3,3 V**;
firmware ustawia wszystkie jako INPUT, bez INPUT_PULLUP. Rezystancję każdego
pull-upu dobierz do wyjścia konkretnego napędu i przewodów. GPIO34/35/36/39 są
wyłącznie wejściowe. GPIO32/33/16/17 mogą pracować jako wejścia i nie kolidują
z używanymi SPI, USB-UART, speakerami ani LED GPIO27 w tym firmware.
[Karta ESP32-WROOM-32](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf)
potwierdza te GPIO; zweryfikuj jednak oznaczenie modułu, wyprowadzenia i schemat
**konkretnej płytki 38-pin CP2102**. GPIO16/17 mają alternatywną funkcję UART2;
nie podłączaj tam drugiego UART. Nie przenoś tej mapy na wariant z innymi
wewnętrznymi przydziałami/PSRAM bez weryfikacji. Sam CP2102 nie identyfikuje modułu.
Sprawdź, czy FDD nie podciąga tego sygnału do 5 V; w razie potrzeby zastosuj
konwersję poziomu. Nie podawaj 5 V na wejścia ESP32. Nie zakładaj zgodności
wejść STEP/DIR każdego FDD z logiką 3,3 V; gdy model jej nie gwarantuje,
potrzebny jest odpowiedni nieodwracający bufor poziomów.
Opcjonalny pull-down 10 kΩ GPIO27 zapewnia LOW także przed startem firmware.
GPIO27 (LED) i Q27 (DRV3 BIN2) to różne połączenia.

## Łańcuch 74HC595

Dla **każdego z sześciu** rejestrów: pin 16 → 3,3 V, pin 8 → GND,
pin 10 /SRCLR → 3,3 V. Nie pozostawiaj /SRCLR ani /OE w stanie pływającym.
Łącz pin 9 QH′ układu #1 z pinem 14 SER układu #2, następnie #2→#3→#4→#5→**#6**. SR6 jest ostatni, najdalej od ESP32.
QH′ jest wyjściem szeregowym; nie zastępuje wyjścia QH.
CLOCK, LATCH i /OE są wspólne. Układ #1 jest najbliżej ESP32.

| Rejestr | Globalne wyjścia | QA / QB / QC / QD / QE / QF / QG / QH — piny DIP-16 |
| --- | --- | --- |
| #1 | Q0–Q7 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #2 | Q8–Q15 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #3 | Q16–Q23 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #4 | Q24–Q31 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #5 | Q32–Q39 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #6 | Q40–Q47 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |

SPI przesuwa bajt **SR6 jako pierwszy, SR1 jako ostatni**, MSB first, 1 MHz.
Ramka ma 6 bajtów / 48 bitów, co najmniej 48 µs plus narzut i zbocze LATCH.
Boot utrzymuje /OE HIGH, ładuje STEP wszystkich ośmiu FDD HIGH, pozostałe
wyjścia LOW, potem włącza /OE. Stan w kolejności SR1→SR6:
**`55 55 00 00 00 00`**; kolejność bajtów SPI: `00 00 00 00 55 55`.
Boot nie wykonuje HOME ani ruchu. /OE HIGH oznacza wyjścia high-Z, nie odcięcie
mocy mostków. Przy flashowaniu i testach logiki odłącz zasilanie urządzeń
wykonawczych oraz ich sygnały; nie polegaj wyłącznie na programie.

**Zgłoszona awaria montażowa:** brak połączenia pinu 8 GND każdego rejestru
powodował nieprawidłowe napięcia i niestabilną logikę. Po poprawieniu GND na
pinie 15 pięciu starych rejestrów zmierzono LOW ≈0 V / HIGH ≈3,41 V.
To obserwacja użytkownika dla tych pięciu pinów, nie certyfikacja wszystkich
Q ani nowego SR6. Sprawdź osobno pin 8 i napięcie zasilania każdego układu.

## Wszystkie wyjścia Q0–Q47

**Wszystkie 48 Q jest przypisane; nie ma wolnych wyjść ani linii usypiania.**
SR1–2 obsługują FDD, SR3–5 DVD, SR6 HDD. Dla DVD wejścia są kolejno
AIN1, AIN2, BIN1, BIN2. Każdy HDD zajmuje jeden mostek H.

| Q | Połączenie | Q | Połączenie |
| ---: | --- | ---: | --- |
| 0 | FDD1 STEP | 1 | FDD1 DIR |
| 2 | FDD2 STEP | 3 | FDD2 DIR |
| 4 | FDD3 STEP | 5 | FDD3 DIR |
| 6 | FDD4 STEP | 7 | FDD4 DIR |
| 8 | FDD5 STEP | 9 | FDD5 DIR |
| 10 | FDD6 STEP | 11 | FDD6 DIR |
| 12 | FDD7 STEP | 13 | FDD7 DIR |
| 14 | FDD8 STEP | 15 | FDD8 DIR |
| 16 | DRV1 AIN1 | 17 | DRV1 AIN2 |
| 18 | DRV1 BIN1 | 19 | DRV1 BIN2 |
| 20 | DRV2 AIN1 | 21 | DRV2 AIN2 |
| 22 | DRV2 BIN1 | 23 | DRV2 BIN2 |
| 24 | DRV3 AIN1 | 25 | DRV3 AIN2 |
| 26 | DRV3 BIN1 | 27 | DRV3 BIN2 |
| 28 | DRV4 AIN1 | 29 | DRV4 AIN2 |
| 30 | DRV4 BIN1 | 31 | DRV4 BIN2 |
| 32 | DRV5 AIN1 | 33 | DRV5 AIN2 |
| 34 | DRV5 BIN1 | 35 | DRV5 BIN2 |
| 36 | DRV6 AIN1 | 37 | DRV6 AIN2 |
| 38 | DRV6 BIN1 | 39 | DRV6 BIN2 |
| 40 | DRV7 AIN1 | 41 | DRV7 AIN2 |
| 42 | DRV7 BIN1 | 43 | DRV7 BIN2 |
| 44 | DRV8 AIN1 | 45 | DRV8 AIN2 |
| 46 | DRV8 BIN1 | 47 | DRV8 BIN2 |

## FDD

Dla każdej stacji połącz STEP z pinem 20 i DIR z pinem 18 złącza 34-pin.
TRACK0 pin 26 prowadź do odpowiedniego GPIO według tabeli wyżej.
Połącz masy sygnałowe i zasilania; standardowe nieparzyste piny złącza są masą,
ale identyfikację pinu 1 i pinout konkretnego napędu sprawdź przed połączeniem.
Wybór napędu /DS utrzymuj aktywny LOW na właściwym wejściu (często pin 12,
zależnie od zworek i kabla). /DS nie jest sterowane przez żadne Q z tej mapy.
Kabel z przeplotem zmienia wybór napędu; użyj znanego, bezpośredniego mapowania.
Zasilanie 5 V podaj na złącze zasilania FDD zgodnie z oznaczeniami napędu;
nie ustalaj polaryzacji małego wtyku wyłącznie po kolorze przewodów.
HOME będzie wiarygodne dopiero po sprawdzeniu aktywności TRACK0.

## DVD i HDD przez DRV8833

| Moduł | AOUT1 / AOUT2 | BOUT1 / BOUT2 |
| --- | --- | --- |
| DRV1 | DVD1 cewka A | DVD1 cewka B |
| DRV2 | DVD2 cewka A | DVD2 cewka B |
| DRV3 | DVD3 cewka A | DVD3 cewka B |
| DRV4 | DVD4 cewka A | DVD4 cewka B |
| DRV5 | DVD5 cewka A | DVD5 cewka B |
| DRV6 | DVD6 cewka A | DVD6 cewka B |
| DRV7 | HDD1 VCM | HDD2 VCM |
| DRV8 | HDD3 VCM | HDD4 VCM |

Znajdź pary przewodów cewek DVD omomierzem przy odłączonym zasilaniu.
Jedna cewka zajmuje cały mostek; nie łącz wyjść mostków ze sobą ani z masą.
VM i GND każdego modułu podłącz do właściwego obwodu zasilania.
Sterowanie używa wyłącznie AIN1/AIN2/BIN1/BIN2; nie ma dodatkowej linii
usypiania/wybudzania z rejestrów ani ESP32. Q40–Q47 obsługują cztery HDD przez DRV7–8.
O gotowości modułu do pracy decyduje jego faktyczny schemat; żaden pin
niepodłączony na module nie jest traktowany jako zabezpieczenie odcinające moc.
AISEN/BISEN muszą być połączone według schematu konkretnego modułu
(z masą lub przez właściwe rezystory pomiaru prądu); nie zakładaj obecności
ograniczania prądu tylko dlatego, że użyto DRV8833. Firmware nie mierzy tych prądów,
nie odczytuje nFAULT i nie ma czujników temperatury. Wszystkie osiem modułów
ma przydział; ich fizyczna gotowość wymaga osobnych kontroli.

## Dwa PC Speakery

Potwierdzona przez użytkownika topologia funkcjonalna jest identyczna dla obu
kanałów: osobny S8050 i osobny rezystor bazy. Przyjęte połączenie low-side:

```text
GPIO25 ── R_B1 ── B Q1 S8050        GPIO26 ── R_B2 ── B Q2 S8050
                  E ── GND                           E ── GND
                  C ── Speaker−                      C ── Speaker FX−
V_SPK ──────────────── Speaker+      V_SPK ──────────────── Speaker FX+
```

**R_B1, R_B2 i V_SPK są nieustalone**. Głośniki według użytkownika są
prawdopodobnie 8 Ω; producent, moc i faktyczna impedancja nie są potwierdzone.
Nie zakładaj kolejności B/C/E z nazwy S8050: sprawdź konkretnego producenta,
obudowę i element. Rezystor jest między GPIO a bazą, głośnik w obwodzie
kolektora, emiter na wspólnej masie. Przed zasileniem dobierz rezystor,
prąd obciążenia oraz ochronę tranzystora przed przepięciami obciążenia
indukcyjnego. Te dane nie wynikają z kodu. Nie kopiuj napięcia z dawnych
połączeń silnika VHS. Nie podłączaj głośnika 8 Ω bezpośrednio do GPIO.
GPIO25 i GPIO26 są już przypisane; kolejnych GPIO nie trzeba szukać.

## Dokumentacja elementów

- [TI SN74HC595 — pinout DIP-16, kaskada i /OE](https://www.ti.com/lit/ds/symlink/sn74hc595.pdf)
- [TI DRV8833 — mostki, VM i xISEN](https://www.ti.com/lit/ds/symlink/drv8833.pdf)
- [Espressif ESP32-WROOM-32 — GPIO i zasilanie](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf)

Karta układu scalonego nie zastępuje schematu gotowego modułu ani identyfikacji
silnika, tranzystora i głośnika. Brakujące dane nie blokują odtworzenia logiki
mapowania, ale uniemożliwiają uznanie całego układu mocy za zweryfikowany.
