# Połączenia i zasilanie

Aktualny układ: ESP32-WROOM-32, 5 × 74HC595, 6 × moduł DRV8833,
4 FDD, 4 dwufazowe bipolarne steppery DVD, 4 cewki HDD VCM oraz
2 pasywne PC Speakery sterowane przez osobne S8050.
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
| ESP32 | USB płytki developerskiej | Sposób zasilania logiki; sprawdź schemat konkretnej płytki przed równoczesnym podaniem zewnętrznego zasilania |
| 5 × 74HC595 i pull-upy logiczne | 3,3 V, wspólna masa ESP32 | Przyjęta logika układu; nie szyna zasilania silników |
| FDD | Osobne 5 V do złącza zasilania napędu | Bieżące założenie układu; sprawdź model i orientację wtyku |
| DVD stepper | Proponowane 3,3 V **na VM DRV8833 #1–4** | Robocze napięcie zasilania silników, wymaga pomiaru temperatury i prądu; brak potwierdzonego limitu ciągłej pracy |
| HDD VCM | Osobne VM DRV8833 #5–6, do ustalenia | Brak zweryfikowanego napięcia/prądu dla kompletu cewek; zapis testu 5 V i ~23,3 Ω znajduje się w [badaniach](research/hardware-measurements.md#hdd-vcm) |
| PC Speaker / FX | Osobna szyna V_SPK, do ustalenia | Nieznany prąd obciążenia i rezystory bazowe S8050; nie zasilać głośnika z GPIO |

Połącz masy zasilaczy, ESP32, rejestrów, napędów i sterowników. Wspólna masa
nie oznacza połączenia dodatnich szyn o różnych napięciach. Prąd silników
prowadź osobnymi przewodami do zasilaczy; nie przez regulator 3,3 V ESP32 ani
cienkie mostki masy logiki. Sprawdź przerwy w szynach płytek stykowych.

Dodaj odsprzęganie zasilania przy układach: 100 nF przy każdym 74HC595 oraz
kondensatory VM zgodne z dokumentacją konkretnego modułu DRV8833 i długością
przewodów. To zalecenia projektowe producentów, nie wynik pomiaru tej instalacji.
Zasilacze, przekroje, zabezpieczenia i nastawy ograniczenia prądu wymagają doboru
po identyfikacji obciążeń. Samo 3,3 V nie dowodzi bezpiecznego prądu DVD.

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
| 25 | R_B1 → baza S8050 Q1 → sterownik głównego PC Speakera |
| 26 | R_B2 → baza S8050 Q2 → sterownik PC Speaker FX |
| 27 | Opcjonalna dioda testowa: 330 Ω → anoda LED, katoda → GND |
| 1 / 3 | UART0 / USB-Serial, pozostawione do programowania i diagnostyki |

TRACK0 jest aktywne LOW. GPIO 34/35/36/39 są wejściowe i wymagają zewnętrznych
pull-upów do 3,3 V. Wartość dobierz do wyjścia konkretnego napędu i przewodów.
Sprawdź, czy FDD nie podciąga tego sygnału do 5 V; w razie potrzeby zastosuj
konwersję poziomu. Nie podawaj 5 V na wejścia ESP32. Nie zakładaj zgodności
wejść STEP/DIR każdego FDD z logiką 3,3 V; gdy model jej nie gwarantuje,
potrzebny jest odpowiedni nieodwracający bufor poziomów.
Opcjonalny pull-down 10 kΩ GPIO27 zapewnia LOW także przed startem firmware.
GPIO27 i wyjście rejestrów Q27 to różne połączenia.

## Łańcuch 74HC595

Dla każdego z pięciu rejestrów: pin 16 → 3,3 V, pin 8 → GND,
pin 10 /SRCLR → 3,3 V. Nie pozostawiaj /SRCLR ani /OE w stanie pływającym.
Łącz pin 9 QH′ układu #1 z pinem 14 SER układu #2, następnie #2→#3→#4→#5.
QH′ jest wyjściem szeregowym; nie zastępuje wyjścia QH.
CLOCK, LATCH i /OE są wspólne. Układ #1 jest najbliżej ESP32.

| Rejestr | Globalne wyjścia | QA / QB / QC / QD / QE / QF / QG / QH — piny DIP-16 |
| --- | --- | --- |
| #1 | Q0–Q7 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #2 | Q8–Q15 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #3 | Q16–Q23 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #4 | Q24–Q31 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |
| #5 | Q32–Q39 | 15 / 1 / 2 / 3 / 4 / 5 / 6 / 7 |

SPI przesuwa bajt #5 jako pierwszy, #1 jako ostatni, MSB first, 1 MHz.
40 bitów zajmuje co najmniej 40 µs plus narzut i zbocze LATCH.
Boot utrzymuje /OE HIGH, ładuje STEP HIGH, wejścia mostków LOW i nSLEEP LOW,
potem włącza /OE. Stan rejestrów jest wtedy `55 00 00 00 00` w kolejności
#1→#5. Boot nie wykonuje HOME ani nie rozpoczyna nut.

## Wszystkie wyjścia Q0–Q39

| Q | Połączenie | Q | Połączenie |
| ---: | --- | ---: | --- |
| 0 | FDD1 STEP | 1 | FDD1 DIR |
| 2 | FDD2 STEP | 3 | FDD2 DIR |
| 4 | FDD3 STEP | 5 | FDD3 DIR |
| 6 | FDD4 STEP | 7 | FDD4 DIR |
| 8 | DRV1 AIN1 | 9 | DRV1 AIN2 |
| 10 | DRV1 BIN1 | 11 | DRV1 BIN2 |
| 12 | DRV2 AIN1 | 13 | DRV2 AIN2 |
| 14 | DRV2 BIN1 | 15 | DRV2 BIN2 |
| 16 | DRV3 AIN1 | 17 | DRV3 AIN2 |
| 18 | DRV3 BIN1 | 19 | DRV3 BIN2 |
| 20 | DRV4 AIN1 | 21 | DRV4 AIN2 |
| 22 | DRV4 BIN1 | 23 | DRV4 BIN2 |
| 24 | DRV5 AIN1 | 25 | DRV5 AIN2 |
| 26 | DRV5 BIN1 | 27 | DRV5 BIN2 |
| 28 | DRV6 AIN1 | 29 | DRV6 AIN2 |
| 30 | DRV6 BIN1 | 31 | DRV6 BIN2 |
| 32 | Wolne, boot LOW | 33 | Wolne, boot LOW |
| 34 | Wolne, boot LOW | 35 | Wolne, boot LOW |
| 36 | Wspólne nSLEEP DRV1–6 | 37 | Wolne, boot LOW |
| 38 | Wolne, boot LOW | 39 | Wolne, boot LOW |

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
| DRV5 | HDD1 VCM | HDD2 VCM |
| DRV6 | HDD3 VCM | HDD4 VCM |

Znajdź pary przewodów cewek DVD omomierzem przy odłączonym zasilaniu.
Jedna cewka zajmuje cały mostek; nie łącz wyjść mostków ze sobą ani z masą.
VM i GND każdego modułu podłącz do właściwego obwodu zasilania.
Jeżeli moduł udostępnia nSLEEP, połącz je do Q36, sprawdzając jego wbudowane
pull-upy i ewentualne zworki. Nie myl nSLEEP z nFAULT.
AISEN/BISEN muszą być połączone według schematu konkretnego modułu
(z masą lub przez właściwe rezystory pomiaru prądu); nie zakładaj obecności
ograniczania prądu tylko dlatego, że użyto DRV8833. Firmware nie mierzy tych prądów,
nie odczytuje nFAULT i nie ma czujników temperatury. Moduły #7–8, jeśli są
w zestawie, nie mają przydziału w aktualnym układzie.

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
- [TI DRV8833 — mostki, VM, nSLEEP i xISEN](https://www.ti.com/lit/ds/symlink/drv8833.pdf)
- [Espressif ESP32-WROOM-32 — GPIO i zasilanie](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf)

Karta układu scalonego nie zastępuje schematu gotowego modułu ani identyfikacji
silnika, tranzystora i głośnika. Brakujące dane nie blokują odtworzenia logiki
mapowania, ale uniemożliwiają uznanie całego układu mocy za zweryfikowany.
