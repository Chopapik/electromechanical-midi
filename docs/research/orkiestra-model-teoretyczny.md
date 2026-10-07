# Orkiestra elektromechaniczna — model teoretyczny urządzeń

Stan researchu: 7 października 2026. Zakres: FDD 3,5″, bipolarny krokowiec sled CD/DVD, HDD VCM jako perkusja oraz jako źródło tonu. Bez pomiarów sprzętu użytkownika, bez analizy jego firmware i bez implementacji.

## A. Executive summary

**Da się zbudować użyteczny profil startowy, ale nie da się uczciwie wyznaczyć jednego potwierdzonego „pasma muzycznego” dla całej klasy FDD, DVD albo HDD.** Najmocniejsze źródła opisują elektrykę i pozycjonowanie. Najsłabiej udokumentowane są głośność, akustyczne przejścia między nutami i trwałość podczas grania.

1. **FDD:** kilka kart producentów wskazuje 3 ms między krokami, czyli około 333 kroków/s. To granica deklarowanej pracy pozycjonującej w tych modelach, nie uniwersalna granica wydobycia dźwięku. Przy zmianie kierunku występuje duża różnica: TEAC FD-235HF-C891 podaje 4 ms, Samsung SFD-321B i Panasonic JU-257A6P — 18 ms. [S1–S5]
2. **Nie dodawać 15 ms settling do każdego kroku ani automatycznie do każdej nuty.** Settling dotyczy ustalenia głowicy przed operacją dyskową; muzyka wykorzystuje właśnie nieustalone drgania. Nie jest to zmierzony czas ustalenia wysokości dźwięku.
3. **80 cylindrów, 160 ścieżek i 160 przełączeń STEP to różne rzeczy.** W typowym napędzie dwustronnym 160 ścieżek oznacza 80 na stronę. Przejście 0→79 wymaga 79 zewnętrznych poleceń kroku. Nie wolno planować przejazdu na 160 kroków na podstawie liczby ścieżek na dysku.
4. **DVD:** konkretna karta Minebea PL15S-020 podaje 20 kroków/obrót, 10 Ω/fazę, 5 V, moment trzymający 3 mN·m oraz moment pull-out 2,5 mN·m przy 400 PPS i 1,3 mN·m przy 1400 PPS. Producent przedstawia te wartości jako referencyjne. Nie są to parametry każdego silniczka z DVD. [S8]
5. **HDD tonal ma sens fizyczny i istnieją działające projekty**, ale VCM nie zapewnia takiego centrowania jak membrana typowego głośnika. Trzeba modelować położenie średnie, napięcie indukowane ruchem, zakres wychylenia, harmoniczne oraz rezonanse. [S12–S17]
6. **Czas przejścia nie powinien zależeć tylko od półtonów.** Dla poruszającego się krokowca ważniejsze są różnica prędkości w krokach/s, kierunek, obciążenie i zapas momentu. Dla VCM — aktualne prądy, położenie, prędkość, faza i drgania własne.
7. **Proponowane poniżej zakresy aranżera to jawne hipotezy do symulacji.** Nie są potwierdzeniem stabilności ani bezpiecznymi nastawami prądów, napięć i uderzeń.

Najbardziej obiecujący podział funkcji: FDD — niższe melodie i harmonia; DVD — dodatkowy głos tonalny zależny od konkretnego mechanizmu; HDD percussion — pojedyncze uderzenia z kontrolą resetu; HDD tonal — eksperymentalny środek pasma, lead i tekstury. To wniosek projektowy, nie wynik porównawczego testu akustycznego.

## B. Jak czytać liczby

- **FACT:** wartość lub obserwacja rzeczywiście występująca w wskazanym źródle. Obowiązuje dla jego modelu i warunków.
- **DERIVED:** wynik podanego równania. Dokładność obliczenia nie oznacza dokładności modelu fizycznego.
- **HYPOTHESIS:** świadomie dobrane założenie startowe lub scenariusz analizy wrażliwości.
- **HIGH:** mocne źródło albo jednoznaczne wyprowadzenie w określonych warunkach.
- **MEDIUM:** dane referencyjne, ograniczone warunki, odczyt transkrypcji lub przeniesienie przybliżonego modelu.
- **LOW:** brak pomiarów muzycznych, analogia albo arbitralna polityka aranżera.

**Niepewność nie zawsze jest przedziałem statystycznym.** Dla specyfikacji „minimum 3 ms” znamy dolną granicę wymaganego odstępu, a nie rozkład egzemplarzy. Dla profili LOW podaję przedziały alternatywnych założeń. Nie są to przedziały ufności ani obietnica, że wszystkie urządzenia mieszczą się w tych widełkach. Brak danych zapisuję jako `null`/„nieznane”, nie jako zero.

Wartości obliczone są zaokrąglone; niepewność fizyczna dziedziczy niepewność parametrów i założeń. Stałe matematyczne oraz dokładne definicje jednostek nie wymagają osobnego przedziału.

| Urządzenie | Co jest mocno podparte źródłami | Proponowany zakres roboczy symulatora, HYPOTHESIS/LOW | Główne ograniczenie |
|---|---|---|---|
| FDD | 3 ms/krok w kilku modelach; 4 lub 18 ms przy zawracaniu | preferowane 100–300 Hz; eksperymentalnie 65–500 Hz | zawracanie, sterownik wewnętrzny, nierówne brzmienie |
| DVD sled | charakterystyka momentu konkretnego PL15S-020 | preferowane 150–600 kroków/s; eksploracja 80–1000 kroków/s | obciążenie sled, R/L, synchronizm; nieznane przełożenie na ton |
| HDD percussion | model VCM, istnienie uderzeń o ograniczniki | planistycznie 5 hitów/s; scenariusze 2–10/s; burst 10/s w krótkim oknie | energia zderzenia, powrót, grzanie, zużycie |
| HDD tonal | modele dynamiczne i rezonanse konkretnych konstrukcji, działające projekty audio | preferowane 200–800 Hz; eksploracja 100–1500 Hz | centrowanie, wychylenie, rezonanse wzbudzane również harmonicznymi |

Uzasadnienia i niepewności granic znajdują się w profilach. Zwłaszcza liczby dla HDD nie są limitami producenta. „Eksploracja” oznacza obszar modelowania, nie polecenie testowania go pełną mocą.

## C1. FDD: dokumentacja, częstotliwość i zawracanie

### Dane producentów

| Model / rodzina | Track-to-track / odstęp STEP | Settling | Zawracanie | STEP / DIR | Pozycje i status |
|---|---:|---:|---:|---|---|
| TEAC FD-235HF-C891, Rev. A [S1] | ≥3 ms dla kolejnych kroków w tym samym kierunku | ≤15 ms; łącznie ≤18 ms od końcowego kroku | odstęp ≥4 ms | impuls ujemny ≥0,8 µs; DIR stabilny ≥0,8 µs przed końcowym zboczem impulsu | 80 cylindrów; FACT/HIGH dla ms i geometrii; MEDIUM dla µs z transkrypcji |
| TEAC FD-235HF-A291 [S1b] | ≥3 ms | zakończenie ruchu z settling w 18 ms | ≥4 ms | karta skanowana, nie wyprowadzam dodatkowych timingów z nieczytelnego diagramu | potwierdzenie drugiego wariantu, nie całej rodziny |
| Samsung SFD-321B, OEM/SEMA [S2] | ≥3 ms | ≤15 ms | Turn Around ≥18 ms | diagram zawiera minimum 1 µs dla impulsu i timingów interfejsu; opis STEP wskazuje zbocze narastające | 160 ścieżek łącznie; FACT/HIGH dla ms, MEDIUM dla przypisania timingów µs |
| Sony MPF920 / MPF820 [S3] | 3 ms | ≤15 ms | nie podano w skróconej karcie | nie podano | FACT/MEDIUM: karta marketingowa ma również podejrzane opisy interfejsu i jednostek transferu |
| Panasonic JU-257A6P [S4] | 3 ms | 15 ms | Turn Around min. 18 ms | nieustalone w pozyskanym czytelnym fragmencie | FACT/MEDIUM dla pozyskanej tabeli OEM |
| Alps DF354H / DF354N [S5] | 3 ms | 15 ms | nie znaleziono | nie znaleziono | karta DF35; FACT/MEDIUM, nie wszystkie rewizje Alps |
| Mitsumi D359M3 / D359M3D | brak wystarczająco odczytanej karty timingów | nieustalone | nieustalone | nieustalone | odnaleziony katalog i listingi nie uzasadniają kompletnego profilu |
| Chinon FZ-357 | brak zweryfikowanej pierwotnej karty timingów | nieustalone | nieustalone | nieustalone | nie przenoszę automatycznie 3/15 ms z zestawień wtórnych |

Niepewność FACT: wskazane minimum/maksimum jest zakresem specyfikacji; tolerancja fizyczna pozostałych wartości nie jest podana. Nie używam identycznych wartości z kilku modeli jako rozkładu statystycznego wszystkich FDD.

**Uwaga do mikrosekund:** transkrypcje starych dokumentów gubią znak µ. „0.8s” w odczycie TEAC nie oznacza 0,8 sekundy. Przed późniejszym pisaniem drivera trzeba odczytać oryginalny diagram danej rewizji. Różnią się też opisy aktywnego zbocza: dokumentacja TEAC mówi o końcu ujemnego impulsu, Samsung wprost o zboczu narastającym, a autor Floppotronu opisuje zbocze opadające. [S1, S2, S6] W modelu liczymy **jedno efektywne zdarzenie kroku na pełny impuls**, bez założenia, że oba zbocza powodują pozycjonowanie.

### Przeliczanie czasu na MIDI

\[
f_s=\frac{1}{T_s},\qquad f_n=440\,2^{(n-69)/12},\qquad n=69+12\log_2(f/440).
\]

Poniższa tabela jest DERIVED/HIGH warunkowo dla `f_audio = f_s`. Dodatkowa niepewność modelu akustycznego pozostaje nieznana.

| Odstęp między efektywnymi STEP | Częstotliwość | Ułamkowy numer MIDI | Najwyższa nuta równo temperowana ≤ tej częstotliwości |
|---:|---:|---:|---|
| 2 ms | 500 Hz | 71,213 | 71 — B4/H4, 493,88 Hz |
| 2,5 ms | 400 Hz | 67,350 | 67 — G4, 392,00 Hz |
| 3 ms | 333,333 Hz | 64,194 | 64 — E4, 329,63 Hz |
| 4 ms | 250 Hz | 59,213 | 59 — B3/H3, 246,94 Hz |
| 5 ms | 200 Hz | 55,350 | 55 — G3, 196,00 Hz |

Stosuję nazewnictwo C4=MIDI 60. 400 Hz nie jest G4; G4 jedynie mieści się poniżej tej granicy. Warianty 2–5 ms są zadanymi scenariuszami, nie pięcioma znalezionymi specyfikacjami napędów.

### Czy audio równa się STEP?

Model startowy ciągu klików:

\[
p(t)=\sum_j a_j\,h(t-t_j),\qquad t_{j+1}-t_j=1/f_s.
\]

`h(t)` jest odpowiedzią akustyczną mechaniki i montażu. Dla równych klików widmo ma linie przy `f_s, 2f_s, 3f_s…`; rezonanse mogą mocniej podbić harmoniczną niż podstawę. Zmienne `a_j` i różny kształt klików w kolejnych fazach mogą wprowadzać podharmoniczne i modulację.

**Założenie `f_audio≈f_s` ma sens jako punkt startowy, ale nie jako gwarancja dominującego piku FFT.** Oddzielamy częstotliwość powtarzania impulsów, ton postrzegany i najwyższy pik widma.

Jeżeli timer przełącza STEP HIGH/LOW co `Ttoggle`, pełny impuls trwa `2Ttoggle` i:

\[
f_s=\frac{1}{2T_{toggle}}.
\]

To częste źródło czynnika 2 w kodzie. Jest to zależność elektryczna, a nie dowód, że mechanika zawsze gra oktawę niżej. Wewnętrzne podkroki napędu także nie muszą odpowiadać zewnętrznym poleceniom 1:1 — TEAC C891 opisuje dwa kroki silnika na ścieżkę. [S1]

### Porównanie z projektami

- **Floppotron:** autor opisuje ciąg klików głowicy oraz grupowanie FDD dla obwiedni głośności. FDD służą niższym partiom, skanery wyższym; HDD tworzą uderzenia. To potwierdza praktyczną użyteczność, ale artykuł nie publikuje krzywej błędów kroku, stałego pasma FDD ani zmierzonej kary zawracania. [S6]
- **Moppy / Moppy2:** pierwotne repozytoria są dostępne i dokumentują projekt muzyczny. Nie udało się w tym researchu wiarygodnie odczytać bieżącego pliku generującego impulsy Moppy2; nie przypisuję mu konkretnej przerwy DIR ani granicy Hz. Dostępne kopie starszego kodu używają liczników przełączeń, ale nie traktuję kopii forumowych jako specyfikacji aktualnego Moppy2. [S7]
- **MCU on Eclipse:** autor własnej implementacji podaje około 400–440 Hz jako ograniczenie swojego rozwiązania. Jednocześnie tekst błędnie wiąże 440 Hz z MIDI 48 (standardowo MIDI 48 to 130,81 Hz). Jest to dowód praktyki konkretnego projektu, a nie precyzyjna tabela MIDI czy uniwersalny limit. [S18]

**Wniosek:** nie znalazłem pierwotnego dowodu, że wszystkie muzyczne FDD stabilnie śledzą 1 kHz. Nie traktuję samego odtwarzania nagrania jako potwierdzenia prawidłowego wykonywania każdego kroku.

### Trzy zakresy

| Warstwa | Propozycja | Status / niepewność |
|---|---|---|
| A. Datasheet | `f_s≤333,33/s` dla wymienionych modeli 3 ms; indywidualny timing DIR | DERIVED/HIGH dla tych modeli; brak akustycznej dolnej granicy |
| B. Roboczy muzyczny prior | 65–400 Hz, preferencja 100–300 Hz | HYPOTHESIS/LOW; dolny próg rozważać 40–100 Hz, górny 330–500 Hz |
| C. Agresywny obszar symulacji | >400 do 800 Hz | HYPOTHESIS/LOW; 800 to wybrany kraniec eksperymentalny, nie dowiedziony limit; możliwość niepowodzenia już poniżej |

Zakres A nadal nie gwarantuje równego tonu podczas zawracania. Dolna granica B oznacza wybór aranżacyjny „ciągły ton zamiast wolnych klików”, nie minimalną prędkość mechanizmu.

### Zawracanie i artefakty długiej nuty

Dla `N` rzeczywistych kroków w jedną stronę:

\[
T_{rev}\approx N/f_s,\quad r_{rev}\approx f_s/N.
\]

To częstość **zdarzeń zawracania**. Pełny cykl tam–z powrotem ma częstotliwość `f_s/(2N)`. Gdy oba końce brzmią inaczej, w widmie obwiedni pojawi się także ta niższa częstotliwość.

| f_s | N=40: odstęp / zdarzenia na sekundę | N=80: odstęp / zdarzenia na sekundę | N=160: hipotetyczny przejazd |
|---:|---:|---:|---:|
| 110 Hz | 364 ms / 2,75 | 727 ms / 1,375 | 1455 ms / 0,6875 |
| 220 Hz | 182 ms / 5,50 | 364 ms / 2,75 | 727 ms / 1,375 |
| 440 Hz | 91 ms / 11,0 | 182 ms / 5,50 | 364 ms / 2,75 |

DERIVED/HIGH dla idealnego ruchu bez przerw. N=80 jest zaokrągleniem porównawczym; rzeczywisty przejazd między cylindrami 0 i 79 ma 79 kroków. N=160 pokazuje żądany scenariusz matematyczny, **nie jest prawidłową nastawą travel typowego PC FDD**. Jeżeli „160” oznacza przełączenia poziomu pinu, trzeba przeliczyć je na efektywne impulsy.

Przerwę należy modelować jako **wydłużenie odstępu**, nie zawsze jako dodatkowe pełne 4/18 ms:

\[
\delta_{rev}(f)=\max(0,T_{rev,min}-1/f).
\]

Przy 220 Hz (`T=4,545 ms`) TEAC nie wymaga dodatkowego odstępu ponad ten już występujący, a profil Samsung wymaga około 13,455 ms wydłużenia. Przy 440 Hz wychodzi odpowiednio 1,727 i 15,727 ms, przy czym 440 Hz już przekracza specyfikację zwykłych kroków 3 ms. To porównanie czasów, nie legalizacja pracy przy 440 Hz.

Z wydłużeniem:

\[
r_{rev}\approx\frac{1}{N/f+\delta_{rev}},\qquad
g\approx\frac{\delta_{rev}}{N/f+\delta_{rev}}.
\]

`g` jest udziałem dodatkowej przerwy, nie spadkiem głośności w dB. Dla 440 Hz, N=80 i δ=15,727 ms: około 5,06 zawrotu/s oraz 8,0% dodatkowego czasu przerwy. Taki regularny ubytek pobudzeń może powodować słyszalne pulsowanie. Rzeczywista słyszalność zależy od wybrzmiewania `h(t)`; nie da się jej ustalić wyłącznie z ms.

Opis ruchu tam–z powrotem w projektach jest zgodny z tym modelem jakościowo. **Brak znalezionego pomiaru Moppy/Floppotron potwierdzającego dokładne amplitudy lub częstotliwości tych artefaktów.**

### Długość nut i zmiany

Proponowany model planistyczny:

\[
D_{min}(f)=\max(D_0,1000N_c/f)\ [ms].
\]

HYPOTHESIS/LOW: `D0=20 ms` (scenariusze 10–40), `Nc=4` cykle (scenariusze 3–8). Dla 110 Hz daje 36,4 ms, dla 220 i 440 Hz po 20 ms. Preferencja: co najmniej 80 ms lub 8 cykli, zależnie co większe; widełki polityki 50–150 ms i 6–12 cykli. To kryterium czytelności nuty, nie zdolności odebrania polecenia.

Sugerowany limit ciągu nowych nut: nominalnie 15/s, zakres założeń 8–25/s, dodatkowo `rate≤1000/Dmin`. Brak podstaw do uniwersalnego `maxTransitionSemitonesPerSecond` — pole pozostaje `null`.

## C2. DVD/CD sled: silnik, obciążenie i dźwięk

### Potwierdzony silnik i analogi

| Parametr | Minebea PL15S-020 [S8] | Status / niepewność |
|---|---:|---|
| Zastosowanie | CD/DVD pickup oraz głowica FDD | FACT/HIGH: lista zastosowań, nie identyfikacja każdego dawcy |
| Kroki/obrót | 20 | FACT/HIGH; brak tolerancji w karcie |
| Kąt pełnego kroku | 18° | DERIVED/HIGH: 360°/20 |
| Sterowanie referencyjne | bipolar constant voltage, 2-2 phase | FACT/HIGH |
| Napięcie / R fazy | 5 V / 10 Ω | FACT/HIGH dla karty; brak podanej tolerancji R |
| Prąd asymptotyczny fazy | 0,5 A | DERIVED/HIGH: V/R, rotor nieruchomy, pominięty mostek |
| Holding torque | 3 mN·m | FACT/MEDIUM, producent określa dane jako referencyjne |
| Pull-out przy 400 / 1400 PPS | 2,5 / 1,3 mN·m | FACT/MEDIUM, warunki katalogowe |
| Maks. pull-in | 1450 PPS | FACT/MEDIUM, wartość referencyjna, nie gwarancja dla całego sled |
| Skok śruby | 3 mm/obrót | FACT/MEDIUM, tabela rysunku |
| Przesuw/pełny krok | 0,15 mm | DERIVED/HIGH warunkowo: 3/20 |
| L, J, Kt, detent torque | nie podano | nieznane — nie wyliczam fikcyjnych danych |

Ważny błąd jednostek do uniknięcia: `30×10⁻⁴ N·m = 0,003 N·m`, a nie 0,03 ani 0,3 N·m.

Producent Stegia podaje dla małych silników PM 15S [S9]: 15S20B1000: R=10 Ω, L=4,1 mH, 18°, I=0,4 A, holding=5 mN·m, detent=0,5 mN·m; 15S20B2000: R=20 Ω, L=6,7 mH, 18°, I=0,4 A, holding=7,8 mN·m, detent=0,6 mN·m. To **analogi rozmiaru i konstrukcji, nie potwierdzone silniki z CD/DVD**. FACT/MEDIUM, tolerancji nie podano. Ich τ wynosi odpowiednio 0,410 i 0,335 ms. Podane na stronie 12 V i 0,4 A nie oznaczają prostego zasilania cewki stałym napięciem 12 V; nie wolno ignorować regulacji prądu.

Nie znalazłem reprezentatywnego zbioru kart konkretnych odzyskanych sledów, który uzasadniałby „typowy rozkład R/L/J wszystkich DVD”. Jedna dobrze opisana konstrukcja i analogi nie są takim rozkładem. Nie uwzględniam dwupinowych silników DC ani cewek focus/tracking jako bipolarnego steppera sled.

### Model elektryczny: gdzie uproszczenie RL przestaje działać

Dla nieruchomego wirnika, napięcia V i startu z zerowego prądu:

\[
\tau=L/R,\qquad i(t)=\frac VR(1-e^{-t/\tau}).
\]

Wygodny wskaźnik:

\[
\eta_{RL}(f_s)=1-e^{-1/(f_s\tau)},\qquad I_{step}=\frac VR\eta_{RL}.
\]

**Nie jest to kompletny model cyklicznej komutacji.** Prąd nie zeruje się automatycznie między krokami. Dla stanu początkowego `i0` i w przybliżeniu stałego back-EMF `e`:

\[
i(t)=i_\infty+(i_0-i_\infty)e^{-t/\tau},\qquad i_\infty=(V-e)/R.
\]

Przy odwróceniu napięcia z +V na −V, gdy wcześniej `i0≈V/R`, prąd przechodzi przez zero po `τ ln 2` w modelu bez ruchu. W sekwencji pełnokrokowej dana faza może utrzymywać polaryzację przez dwa kroki. W microsteppingu „czas mikro-kroku” nie jest czasem narastania prądu od zera.

W analizie wrażliwości przyjmuję R=10 Ω, V=5 V oraz L=1/5/20 mH, czyli τ=0,1/0,5/2 ms. **HYPOTHESIS/LOW:** trzy scenariusze, nie statystyka DVD. Środkowy ma oparcie w skali analogów [S9], skrajne celowo rozszerzają niepewność.

| f_s [krok/s] | Istep/I∞, τ=0,1 ms | τ=0,5 ms | τ=2 ms |
|---:|---:|---:|---:|
| 100 | 1,000 | 1,000 | 0,993 |
| 250 | 1,000 | 1,000 | 0,865 |
| 500 | 1,000 | 0,982 | 0,632 |
| 1000 | 1,000 | 0,865 | 0,393 |
| 1500 | 0,999 | 0,736 | 0,283 |
| 2000 | 0,993 | 0,632 | 0,221 |

DERIVED/HIGH warunkowo; wartości należy pomnożyć przez 0,5 A. Niepewność między kolumnami pochodzi z założonego L, a nie błędu arytmetyki.

Relacja `torque≈Kt·Istep` jest wskaźnikiem skali, nie pełną charakterystyką silnika krokowego. Moment zależy również od kąta obciążenia, obu faz i położenia wirnika. Spadek katalogowy 2,5→1,3 mN·m między 400 a 1400 PPS wynosi 48% [S8]; sama krzywa RL dla małej τ nie wyjaśnia całości. Pozostają back-EMF, rezonanse, synchronizm i obciążenie.

### Model mechaniczny i granica przyspieszenia

\[
J_{eq}\ddot\theta+b\dot\theta+T_f+T_{load}=T_e(i_A,i_B,\theta),
\]

\[
J_{eq}=J_{rotor}+J_{screw}+m_{sled}\left(\frac p{2\pi}\right)^2
\]

dla bezpośredniej idealnej śruby o skoku p. Przekładnia dodaje odpowiednie kwadraty przełożeń, a tarcie i sprawność wymagają osobnego ujęcia.

\[
a_{step,max}(f)\lesssim\frac{T_{available}(f)-T_{load}-T_f}{J_{eq}\alpha},\qquad
\alpha=2\pi/N_{steps/rev}.
\]

Jednostka: **krok/s²**, nie Hz audio/s bez poznania mapowania. Warunek dodatniego zapasu momentu jest konieczny, ale nie wystarcza do gwarancji synchronizmu. Start ogranicza pull-in, bieg z rampą pull-out. Przejście przez rezonans może być problematyczne także przy małym przyspieszeniu.

Brak `J_eq` i obciążenia oznacza brak źródłowego `maxAcceleration`. Do symulatora: nominalnie 5000 krok/s², scenariusze 1000–20000, HYPOTHESIS/LOW. Nie przypisuję tej wartości Minebea ani DRV8833. Patent dotyczący seek sled potwierdza znaczenie sterowania pozycją i liczbą impulsów, lecz nie dostarcza pasma muzycznego. [S20]

### Metoda komutacji a muzyka

| Metoda | Co można wywnioskować | Czego nie można obiecać |
|---|---|---|
| Wave drive, jedna faza | mniejsza moc cieplna przy tym samym prądzie fazy; skoki pobudzenia | że będzie najgłośniejszy albo najczystszy |
| Full-step, dwie fazy | większy wektor wzbudzenia niż jedna faza przy tym samym prądzie fazy; dobry punkt startu do wyraźnych impulsów mechanicznych | że przewaga momentu utrzyma się przy identycznej mocy cieplnej i każdej prędkości |
| Half-step | mniejsze przyrosty kąta; bez korekcji prądów przeplata stany o różnej sile wzbudzenia | podwojenia czystego pasma audio |
| Microstepping z kontrolą prądu | zwykle redukuje tętnienia, drgania i hałas; może pomóc płynności | że da mocniejszy instrument; może właśnie wyciszyć pożądany dźwięk |

Podstawa elektryczna: [S10, S11]. Ranking głośności/„czystości” to HYPOTHESIS/LOW. Mniej zgubionych kroków zależy od całego układu, nie samej nazwy trybu. Full-step nie jest bezwarunkowo najlepszy, a microstepping nie gwarantuje fizycznego wykonania każdego mikro-kroku.

**DRV8833 jest podwójnym mostkiem, nie gotowym indekserem sinusoidalnego microsteppingu.** Ma current chopping zależny od xISEN i rezystora pomiarowego (`Itrip≈0,2 V/Rsense`), oraz tryby fast/slow decay. Zwykłe PWM napięcia nie gwarantuje sinusoidalnego prądu. Model musi znać decay, ograniczenie prądu i spadki mostka. [S11] Zabezpieczenie termiczne drivera nie określa dopuszczalnej temperatury silnika.

### f_audio kontra f_step

Sekwencja dwufazowego full-step ma cztery stany elektryczne. Przy częstości komutacji `f_s` prądy faz mają podstawowy okres czterech kroków, ale zdarzenia mechaniczne występują co krok. Zależnie od symetrii i toru akustycznego mogą dominować `f_s`, `f_s/2`, `f_s/4` oraz ich harmoniczne.

**Cztery stany nie dowodzą automatycznie `f_audio=f_s/4`.** Do pierwszego modelu użyć `pitchRatio` jako nieznanego parametru z kandydatami 1, 1/2, 1/4, 2. Lista jest HYPOTHESIS/LOW i nie wyczerpuje zachowania przy utracie synchronizmu. Nie losować jednego współczynnika przy każdej nucie; ustalić oddzielne scenariusze silnik/sterowanie.

Przy `pitchRatio=1/4` granica 1000 kroków/s daje 250 Hz podstawy, nie 1000 Hz. Dlatego profil DVD przechowuje osobno zakres komutacji i warunkowy zakres tonu.

Długość nut: hipoteza `max(30 ms,4/f_audio)`; nominalnie preferować ≥100 ms. Przejazd sled i konieczność powrotu obowiązują także tutaj — sam model RL nie wystarczy do długiej nuty.

## C3. HDD VCM — wspólna baza fizyczna

### Dwa opublikowane zestawy parametrów

| Parametr | Model A: HDD 13 kTPI [S12] | Model B: model użyty w publikacji 2024 [S13] |
|---|---:|---:|
| R cewki | 5,9 Ω | 8 Ω |
| L cewki | 0,368 mH | 1 mH |
| Kt | 0,075 N·m/A | 0,09183 N·m/A |
| J | 2,54×10⁻⁶ kg·m² | 6,3857×10⁻⁶ kg·m² |
| Dodatkowy Rs | nie używam w obliczeniu | 0,2 Ω w opublikowanym torze |
| Ograniczenie wzmacniacza | ±1,9 A w modelu, saturacja 12 V | saturacja wzmacniacza 12 V |
| τ=L/R samej cewki | 62,4 µs | 125 µs |

FACT/MEDIUM dla parametrów opublikowanych modeli; tolerancji tej tabeli nie przyjmuję za znane. DERIVED/HIGH warunkowo dla τ. To **dwa przykłady, nie typowy zakres wszystkich HDD**. Limit wzmacniacza nie oznacza dozwolonego prądu ciągłego odzyskanej cewki. Napięcie 12 V z modelu nie jest zaleceniem zasilania DRV8833.

Pełniejszy model:

\[
L\dot i+Ri+K_e\dot\theta=v,
\]
\[
J\ddot\theta+b\dot\theta+k(\theta-\theta_0)+T_f+T_{stop}(\theta,\dot\theta)=K_ti.
\]

`k` może być małe, nieliniowe i związane m.in. z taśmą elastyczną. Nie przypisuję mu wartości typowej sprężyny głośnika. Dochodzą tarcie łożyska, magnes parkowania, rampy i kontakt głowic z talerzem. Zmiana mechaniki lub zdjęcie pokrywy zmienia drgania i akustykę.

**Seek time i settling kompletnego HDD nie są czasami odpowiedzi otwartej cewki.** Zawierają pracę serwa, czujników i zoptymalizowane trajektorie. Nie znaleziono wiarygodnej konwersji katalogowego seek na cooldown muzycznej perkusji; dlatego tych pól nie wypełniam z katalogu dysku.

## C4. HDD VCM — percussion

### Impuls i energia

Dla zerowego prądu początkowego, nieruchomego układu elektrycznego i bez back-EMF:

\[
Q_I=\frac VR\left[t_p-\tau(1-e^{-t_p/\tau})\right],
\]
\[
\mathcal J_\theta=K_tQ_I,\qquad \Delta\omega=\frac{K_tQ_I}{J}.
\]

`QI` ma jednostkę A·s. Nie jest energią. Przy zaniedbaniu sił przeciwnych i starcie ze spoczynku:

\[
E_k\approx\frac{(K_tQ_I)^2}{2J},
\]
\[
\Delta\theta(t_p)=\frac{K_tV}{JR}\left[\frac{t_p^2}{2}-\tau t_p+\tau^2(1-e^{-t_p/\tau})\right].
\]

Dla `tp≫τ`: `QI≈(V/R)(tp−τ)`, więc energia rośnie w przybliżeniu jak `V²(tp−τ)²`. Dla `tp≪τ`: `QI≈Vtp²/(2L)` i energia jak `V²tp⁴`. To pokazuje, dlaczego liniowe mapowanie MIDI velocity na szerokość impulsu nie musi dawać liniowej siły.

**Sama energia po impulsie nie daje siły uderzenia.** Potrzebne są odległość do ogranicznika, prędkość kontaktu, podatność, tłumienie, czas kontaktu i odbicie. Dla momentu impulsu kontaktowego przy współczynniku restytucji `e_r`:

\[
\mathcal J_{contact}\approx J(1+e_r)|\omega_{impact}|.
\]

Siła liniowa zależy dodatkowo od promienia kontaktu. „Hit strength” najlepiej reprezentować jako energię zderzenia i typ kontaktu, a dopiero potem modelować głośność.

### Przykład obliczeniowy pokazujący błąd prostego RL

Model B, V=1 V wybrane **tylko jako scenariusz**, początek i=ω=θ=0. Wersja sprzężona uwzględnia back-EMF, przyjmuje `Ke=Kt` w jednostkach SI, b=k=0 i brak kontaktu. Wszystkie wyniki DERIVED; zgodność rachunku HIGH, przewidywanie realnego uderzenia LOW.

| tp | QI bez back-EMF [A·s] | Δω bez back-EMF [rad/s] | Ek bez back-EMF [mJ] | Δθ bez back-EMF | Δω z back-EMF | Δθ z back-EMF |
|---:|---:|---:|---:|---:|---:|---:|
| 0,2 ms | 0,00001253 | 0,180 | 0,000104 | 0,00077° | 0,179 | 0,00077° |
| 1 ms | 0,00010938 | 1,573 | 0,00790 | 0,0402° | 1,487 | 0,0389° |
| 3 ms | 0,00035938 | 5,168 | 0,0853 | 0,426° | 4,179 | 0,372° |
| 5 ms | 0,00060938 | 8,763 | 0,245 | 1,225° | 6,100 | 0,967° |
| 10 ms | 0,00123438 | 17,751 | 1,006 | 5,023° | 8,828 | 3,160° |

To nie przedział gwarantowanych wyników: obie kolumny są modelami. Różnica przy 10 ms pokazuje, że sam mały τ elektryczny nie usprawiedliwia pominięcia back-EMF. W tym przykładzie skala `JR/Kt²≈6,06 ms` jest istotna dla dynamiki prędkości. Przy ograniczniku liniowe rozwiązanie traci ważność jeszcze wcześniej.

### Click, hit, crash-stop

| Rodzaj | Model zdarzenia | Co decyduje |
|---|---|---|
| Lekki click | pobudzenie konstrukcji bez kontaktu lub delikatny kontakt | stromość momentu, lokalne rezonanse; dźwięk możliwy bez uderzenia |
| Średni hit | kontakt przy ograniczonej energii, następnie kontrolowany reset | położenie startowe, energia przed kontaktem, materiał ogranicznika |
| Mocny crash-stop | większa energia zderzenia z mechaniczną granicą | zużycie, odbicie, deformacja; nie tylko temperatura cewki |

Autor Floppotronu potwierdza użycie ograniczników i dobór różnych HDD według barwy. [S6] Patenty opisują absorpcję energii i odbicia crash-stopów. Nie potwierdzają wytrzymałości na dowolnie długie serie muzyczne. [S19] Nie rekomenduję mocnego crash-stopu jako domyślnego trybu ciągłego.

### Grzanie i szybkość rytmu

\[
D=t_pr,\quad I_{rms}\approx I_{peak}\sqrt D,\quad P_{Cu}=RI_{rms}^2.
\]

Te przybliżenia wymagają prawie prostokątnego prądu oraz jego zaniku między uderzeniami. Dokładniejszy model:

\[
I_{rms}^2=r\int_{\text{pełny cykl hit+reset+decay}}i^2(t)dt.
\]

Dla pojedynczego narastania RL od zera energia miedziana podczas załączenia:

\[
E_{Cu,on}=\frac{V^2}{R}\left[t_p-2\tau(1-e^{-t_p/\tau})+\frac\tau2(1-e^{-2t_p/\tau})\right].
\]

Dochodzi energia po wyłączeniu, hamowanie i impuls powrotny. Symetryczne impulsy „tam i z powrotem” mogą podwoić aktywny czas w porównaniu z samym `tp·r`. Krótkie duty nie gwarantuje małego prądu szczytowego.

Przykład scenariusza: 0,3 A, 3 ms i 10 hitów/s daje D=0,03, Irms≈0,052 A i P≈0,0216 W przy R=8 Ω, **wyłącznie dla jednej prostokątnej fazy impulsu**. Równa faza powrotna daje około 0,0432 W. Wartości są DERIVED/HIGH dla zadanych założeń, nie znamionami HDD.

Model temperatury:

\[
C_{th}\dot{\Delta T}=Ri^2-\Delta T/R_{th}.
\]

Brak Rth, Cth i dopuszczalnej temperatury konkretnej cewki oznacza brak wyznaczalnego termicznego cooldown. Osobno:

\[
t_{cycle}\ge t_{out}+t_{contact}+t_{return}+t_{settle},\qquad r\le1/t_{cycle}.
\]

Do planowania, HYPOTHESIS/LOW: impulsy nominalnie 0,2–5 ms, typowo w modelu 1 ms; powrót i odstęp start–start nominalnie 200 ms; 5 hitów/s ciągle, krótkie serie 10/s. Alternatywne scenariusze: 0,1–10 ms, 2–10/s ciągle, 5–20/s w serii. **Żadna z tych liczb nie jest bezpiecznym maksimum fizycznym.** Impuls 0,2 ms może nie spowodować uderzenia, a 1 ms przy innym napięciu i położeniu może być nadmierny. Maksimum wymaga ograniczenia energii, prądu i geometrii; pole `safePulseMaxMs` pozostaje nieznane.

Burst musi mieć czas trwania: tutaj wybór polityki to 0,5 s, scenariusze 0,1–1 s. Nie wystarczy wpisać „20 Hz burst” bez długości i budżetu energii.

## C5. HDD VCM — tonal

### Istnienie projektów nie oznacza płaskiego pasma

Projekt Teda Sheflina używa sprzężenia położenia z potencjometru na osi ramienia. To konkretny dowód, że pozycja średnia wymaga uwagi, a nie tylko podania sygnału audio. [S16] Spin Doctor wykorzystuje pary HDD i podział pasma zwrotnicą; autor opisuje nierówną odpowiedź pojedynczego dysku. Nie publikuje skalibrowanej charakterystyki SPL, więc nie wyprowadzam z niego dokładnych granic Hz. [S17]

Nie chodzi tu o odtwarzanie WAV jako cel orkiestry. Projekty audio są dowodem działania VCM jako transducera; sinus lub prostokąt wyznaczony z nuty MIDI pobudza tę samą mechanikę.

### Transmitancja i amplituda

Dla wejścia prądowego, małych wychyleń i modelu liniowego:

\[
H_i(s)=\frac{\Theta(s)}{I(s)}=\frac{K_t}{Js^2+bs+k}.
\]

Przy wejściu napięciowym należy uwzględnić elektrykę i back-EMF:

\[
H_v(s)=\frac{K_t}{(Ls+R)(Js^2+bs+k)+K_tK_es}.
\]

Mody elastyczne można przedstawić dodatkowym `Hres(s)`; rzetelniejszy model modalny zawiera sumę odpowiedzi z podpisanymi współczynnikami sprzężenia i antyrezonansami. Sam iloczyn dodatnich „podbitek rezonansowych” może dać fizycznie błędną odpowiedź.

\[
|\Theta|=\frac{K_tI_{pk}}{\sqrt{(k-J\omega^2)^2+(b\omega)^2}}.
\]

W obszarze zdominowanym przez bezwładność:

\[
|\Theta|\approx\frac{K_tI_{pk}}{J(2\pi f)^2}.
\]

Przy stałym prądzie zejście o oktawę zwiększa wychylenie czterokrotnie. Dla ograniczenia kąta:

\[
I_{pk,max}(f)\lesssim\frac{J(2\pi f)^2\theta_{allow}}{K_t}.
\]

`θallow` wynika z obu odległości do ograniczników i pozycji średniej, nie z samej częstotliwości. W najprostszym obszarze inercyjnym:

\[
f_{min}\gtrsim\frac1{2\pi}\sqrt{\frac{K_tI_{pk}}{J\theta_{allow}}}.
\]

Dlatego „minimalna bezpieczna częstotliwość HDD” bez prądu i dozwolonego wychylenia nie jest określona.

Przykład Modelu B przy sinusoidalnym `Ipk=0,1 A`, promieniu 50,8 mm, bez b/k i rezonansów (DERIVED/HIGH warunkowo, fizycznie LOW):

| f | Amplituda kąta | Amplituda ruchu końcówki |
|---:|---:|---:|
| 50 Hz | 0,835° | 0,740 mm |
| 100 Hz | 0,209° | 0,185 mm |
| 200 Hz | 0,0522° | 0,0463 mm |
| 500 Hz | 0,00835° | 0,00740 mm |
| 1000 Hz | 0,00209° | 0,00185 mm |

To **nie jest krzywa głośności**. SPL wymaga modelu promieniowania, powierzchni, obudowy i sposobu mocowania. W niektórych przybliżeniach ciśnienie wiąże się z przyspieszeniem powierzchni, więc spadek wychylenia `1/f²` nie oznacza automatycznie takiego samego spadku głośności. Przy sterowaniu napięciem dodatkowo zmienia się prąd.

### Rezonanse — konkretne przykłady

| Źródło / konstrukcja | Częstotliwości | Co wolno z tego wywnioskować |
|---|---|---|
| Xu i in., badania head actuator assembly [S14] | quasi-rigid-body w zakresie 3–5 kHz | FACT/MEDIUM: zakres opisanej klasy zespołów, nie całego rynku |
| Model A HDD 13 kTPI [S12] | 4500, 5400, 5550, 5670, 7300, 7450, 8000, 9650 Hz | FACT/MEDIUM: lista modów jednego modelu; nie nazywam wszystkich „rezonansem ramienia” |
| Badawcze zawieszenie stal–krzem Berkeley [S15] | bending 306 Hz; pitch 1700; roll 1925; bending 2050; torsion 2362; dalsze bending 4487, torsion 6438, sway 9637 Hz | FACT/MEDIUM, tabela konkretnego prototypu; nie domyślne rezonanse seryjnego HDD |

Niepewność: źródła nie dostarczają rozkładu tych modów dla odzyskiwanych dysków. Zakresu 3–5 kHz nie należy rozszerzać na wszystkie rodzaje drgań. Lokalne zawieszenie i duży zespół ramienia mogą mieć zupełnie różne mody.

Model A podaje m.in. ζ=0,018 przy 4500 Hz i ζ=0,001 przy 5670 Hz [S12]. Dla obwiedni swobodnego zaniku do około 2%:

\[
t_{2\%}\approx\frac4{\zeta\,2\pi f_r}.
\]

Daje to odpowiednio około **7,9 ms i 112 ms** (DERIVED). Wysoki rezonans nie musi więc szybko wygasać. Te czasy nie są automatycznie settling całego urządzenia ani jego obowiązkową karą każdej nuty — zależą od wzbudzenia danego modu.

### Square, sine, PWM

- **Sinus prądu:** najmniej harmonicznych pobudzenia w modelu liniowym; prostsza analiza wychylenia. Wymaga rzeczywistej kontroli prądu.
- **Prostokąt bipolarny:** dla poziomów ±I ma podstawę o amplitudzie `4I/π`, następnie nieparzyste harmoniczne `4I/(3π), 4I/(5π)…`. Przy prostokątnym napięciu RL i back-EMF zmieniają prądy harmonicznych. Głośniejsze, ostrzejsze brzmienie jest prawdopodobne, ale nie gwarantowane.
- **PWM:** nośna przełączania i częstotliwość nuty są różnymi parametrami. Resztki ripple oraz sposób decay mogą tworzyć dodatkowy dźwięk i grzanie. Sam duty nie jest pomiarem prądu.
- **Mostek H:** umożliwia oba kierunki prądu; nie rozwiązuje automatycznie centrowania, limitu wychylenia ani sprzężenia prądowego.

Przy rezonansie 4500 Hz również nuta 1500 Hz może go pobudzać trzecią harmoniczną, 900 Hz piątą, a około 642,9 Hz siódmą. DERIVED/HIGH dla częstotliwości; skala odpowiedzi nieznana. Zatem ograniczenie podstawy do <1 kHz nie gwarantuje ominięcia wyższych rezonansów.

`avoidBands` powinno obejmować tylko mody ustalone dla danego egzemplarza. Na etapie teoretycznym przechowujemy `candidateResonances`, a w modelu ryzyka badamy również `harmonic*noteFrequency`. Nie wprowadzam uniwersalnego zakazu wszystkich nut w szerokim paśmie tylko dlatego, że jeden artykuł znalazł tam rezonans.

### Centrowanie oraz wybór roli

W idealnym układzie `k=0` nie ma preferowanego środka. Zerowy średni prąd nie usuwa początkowej prędkości ani przesunięcia; niesymetryczny start/stop lub offset może prowadzić do kontaktu. Model powinien zachowywać stan między nutami. Dodana sprężyna albo serwo centrowania tworzy nowy układ dynamiczny — nie wolno zachować bez zmian starego profilu rezonansów.

| Rola | Ocena teoretyczna |
|---|---|
| Bass | największy koszt wychylenia; nie wybierałbym jako domyślnego basu bez centrowania i pomiaru |
| Mid | rozsądny kandydat; najpierw modelować 200–800 Hz z małą amplitudą |
| Lead | możliwy, lecz harmoniczne i rezonanse mogą dominować barwę |
| Noise/percussion | bardzo naturalne zastosowanie impulsów i nieliniowości |
| Drone | możliwy; wymaga budżetu cieplnego i stabilnego położenia średniego, nawet bez wielu przejść |

Zakresy użyteczne 100–1500 Hz i preferowane 200–800 Hz są HYPOTHESIS/LOW. Nie są pomiarem pasma; dolną granicę eksploracji rozważać 50–200 Hz, górną 800–3000 Hz, zależnie od amplitudy i modów. Rzeczywiste dobrze brzmiące pasmo może mieć dziury i nie tworzyć jednego przedziału.

## D. Przejścia f1 → f2

### Odległość muzyczna a fizyczna

\[
\Delta f=|f_2-f_1|,\qquad \Delta n=12|\log_2(f_2/f_1)|.
\]

| Przejście | Δf | Δn |
|---|---:|---:|
| 110→220 Hz | 110 Hz | 12 półtonów |
| 220→330 Hz | 110 Hz | 7,020 półtonu |
| 220→440 Hz | 220 Hz | 12 półtonów |
| 300→320 Hz | 20 Hz | 1,117 półtonu |

DERIVED/HIGH dla zadanych częstotliwości. Ta sama oktawa może wymagać podwojonej zmiany prędkości. Półtony nadają się do kosztu aranżacyjnego lub percepcyjnego, ale nie zastępują równań ruchu. `Note on` ze stanu spoczynku wymaga osobnej reguły, bo `log(f2/0)` nie istnieje.

### FDD

Nie ma źródłowej krzywej akustycznego transition time. Proponuję dwa oddzielne wyniki:

1. `commandDelay`: oczekiwanie na poprawny termin następnego kroku, z zachowaniem impulsu i właściwego DIR.
2. `qualityTransient`: hipoteza kilku cykli i zaniku odpowiedzi poprzedniego pobudzenia.

W policyjnym modelu zgodnym z timingami:

\[
t_{cmd}\ge\max(0,T_{required}-t_{sinceLastStep}).
\]

Dla zwykłego kroku `Trequired` pochodzi ze specyfikacji; dla zawrotu z osobnego timingu. Nie zerować odliczania tak, żeby dwa impulsy trafiły zbyt blisko siebie.

Przybliżenie jakościowe HYPOTHESIS/LOW:

\[
t_{quality}=\max(t_0,1000N_q/f_2)+t_{ring},
\]

z `t0=5 ms` (2–20), `Nq=2` (1–4), `tring` nieznane. Nominalnie przy pominiętym `tring` dla czterech przejść otrzymujemy 9,1 / 6,1 / 5 / 6,25 ms. To czas oceny nowego tonu, **nie udowodniona martwa przerwa**. Jeśli następuje zawracanie, dochodzi harmonogram DIR. Różnica f może dodatkowo pogorszyć synchronizm; bez charakterystyki napędu brak uczciwego współczynnika tej kary.

### DVD sled

Dla tego samego kierunku i przyjętego stałego limitu:

\[
t_{ramp}=|f_{s2}-f_{s1}|/a_s.
\]

Dokładniej `t=∫df_s/a_available(f_s)`. Przy przeciwnych kierunkach zamiast różnicy modułów używamy różnicy **prędkości ze znakiem**; trzeba wyhamować i rozpędzić w drugą stronę. Dla równej wartości obu prędkości daje to `2f_s/a_s`, plus luz i drgania.

| Przejście, zakładając pitchRatio=1 | Rampa przy 5000 krok/s² | Zakres przy 20000…1000 krok/s² |
|---|---:|---:|
| 110→220 | 22 ms | 5,5–110 ms |
| 220→330 | 22 ms | 5,5–110 ms |
| 220→440 | 44 ms | 11–220 ms |
| 300→320 | 4 ms | 1–20 ms |

DERIVED z HYPOTHESIS/LOW przyspieszenia. Nie jest to pomiar sled. Jeśli `pitchRatio=1/4`, wymagane różnice komutacji i te czasy przy stałym `a_s` rosną czterokrotnie. Rampa wydaje glissando: nie należy udawać, że przez cały jej czas gra już docelowa nuta.

Przy zawracaniu model musi także sprawdzić odległość hamowania `d_steps=f_s²/(2a_s)` w uproszczeniu ciągłym. Stały próg pozycji bez uwzględnienia prędkości może prowadzić do kontaktu z końcem prowadnicy.

### HDD tonal

VCM nie potrzebuje rozpędzać wirnika do prędkości odpowiadającej nucie jak krokowiec w ruchu obrotowym. Zmienia się okres wymuszenia. Układ zachowuje położenie, prędkość, prąd i stany modalne:

\[
x(t)=x_{ss,2}(t)+e^{A(t-t_0)}[x(t_0)-x_{ss,2}(t_0)].
\]

To właściwszy model przejścia niż `a·Δf` albo `b·Δn`. Ciągłość fazy ogranicza skok sygnału, ale nie gwarantuje braku przejściowego ruchu i wzbudzenia rezonansów.

Do uproszczonego aranżera HYPOTHESIS/LOW:

\[
t_{transition}\approx\max(1000N_q/f_2,t_{modal,relevant},t_{electrical})+t_{envelope}.
\]

Tylko mody rzeczywiście wzbudzane wchodzą do `t_modal,relevant`. Dla porównania scenariuszy wybieram Nq=3 (2–6), `tmodal=10 ms` (5–120), a narastanie obwiedni oceniam osobno. Przed obwiednią cztery przejścia dają nominalnie 13,6 / 10 / 10 / 10 ms. Szeroki zakres modalny pochodzi z przykładów zaniku, a nie z pomiaru nut. Nie używać go jako obowiązkowej przerwy po każdej nucie.

### HDD percussion

Nie ma przejść tonalnych f1→f2 w tym samym znaczeniu. Jest zmiana interwału uderzeń i energii. Kara to spóźnienie spowodowane niedokończonym resetem lub przekroczeniem budżetu cieplnego/kontaktowego:

\[
penalty=\max(0,t_{ready}-t_{requested}).
\]

Jeżeli częstotliwości 110/220/330/440 Hz interpretować jako uderzenia na sekundę, wychodzą one poza proponowany profil perkusyjny. Takie pobudzenie należy rozpatrywać jako tryb tonalny albo serię zderzeń, a nie zwykłe nuty bębna.

## E. Profile teoretyczne dla aranżera

Poniższy zapis jest **JSON-like, dokumentacyjny**, nie implementacja ani gotowy plik konfiguracyjny firmware. Żeby każda liczba zachowała pochodzenie bez setek powtarzalnych linii, stosuję notację:

`Q(wartość, niepewność, confidence, status, podstawa)`.

Dla zakresu `[min,max]` niepewność zawiera zakres możliwego doboru każdego końca. `UNKNOWN` oznacza brak danych. `EXACT_POLICY` oznacza dokładnie wybrany parametr symulacji, nie pewność fizyczną. Jednostki są zapisane w nazwach pól. Źródła S1–S20 rozwinięto niżej. H1–H4 to jawne założenia autora raportu opisane w sekcjach danego urządzenia.

```text
FDD: {
  purpose: "simulation_prior_not_hardware_guarantee",
  pitchRatio: Q(1, "nieznane; harmoniczne/podharmoniczne możliwe", MEDIUM, HYPOTHESIS, "model ciągu klików; S6"),
  stableHz: Q([65, 330], {lower:[40,100], upper:[250,400]}, LOW, HYPOTHESIS, "H1: konserwatywny prior tonalny, nie gwarancja"),
  musicalHz: Q([65, 500], {lower:[40,100], upper:[330,800]}, LOW, HYPOTHESIS, "H1; S18 tylko wsparcie okolic 400 Hz w jednym projekcie"),
  preferredHz: Q([100, 300], {lower:[65,150], upper:[250,400]}, LOW, HYPOTHESIS, "H1: niższe partie + margines wobec 3 ms"),
  datasheetMinStepMs: Q(3, "[3,infinity) wymagany odstęp w wskazanych modelach", HIGH, FACT, "S1,S2; nie cały rynek"),
  physicalTravelSteps: Q(79, "odległość 0→79; marginesy użytkowe osobno", HIGH, DERIVED, "S1: 80 cylindrów"),
  schedulerTravelSteps: Q(60, [40,75], LOW, HYPOTHESIS, "H1: roboczy przejazd z marginesem, po ustaleniu położenia"),
  minNoteMs: "max(minNoteFloorMs,1000*minCycles/f_audio)",
  minNoteFloorMs: Q(20, [10,40], LOW, HYPOTHESIS, "H1: czytelność nuty"),
  minCycles: Q(4, [3,8], LOW, HYPOTHESIS, "H1"),
  preferredNoteMs: Q(80, [50,150], LOW, HYPOTHESIS, "H1; dodatkowo preferować kilka pełnych cykli"),
  maxNoteChangeRatePerSec: Q(15, [8,25], LOW, HYPOTHESIS, "H1; dodatkowo 1000/minNoteMs"),
  reversalIntervalMs: {
    TEAC_C891: Q(4, "minimum; brak tolerancji między egzemplarzami", HIGH, FACT, "S1"),
    SAMSUNG_SFD321B: Q(18, "minimum", HIGH, FACT, "S2"),
    PANASONIC_JU257A6P: Q(18, "minimum", MEDIUM, FACT, "S4"),
    unknownModelPrior: Q(18, [4,18], LOW, HYPOTHESIS, "zbiór przykładów, nie gwarancja innych modeli")
  },
  reversalPenaltyMs: "max(0,reversalIntervalMs-1000/f_step)",
  acousticTransitionModel: "max(t0Ms,1000*Nq/f2)+ringdownMs; oddzielnie harmonogram STEP/DIR",
  t0Ms: Q(5, [2,20], LOW, HYPOTHESIS, "H1"),
  Nq: Q(2, [1,4], LOW, HYPOTHESIS, "H1"),
  ringdownMs: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak pomiaru odpowiedzi akustycznej"),
  maxTransitionSemitonesPerSecond: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak podstaw do stałego limitu")
}

DVD_SLED: {
  purpose: "simulation_prior; konkretna mechanika i tryb komutacji wymagane",
  driveMode: "two_phase_full_step",
  referenceMotor: "PL15S-020, nie identyfikacja silnika użytkownika",
  phaseResistanceOhm: Q(10, "tolerancja nie podana", HIGH, FACT, "S8"),
  inductanceScenarioMh: Q([1,5,20], "scenariusze LOW/MID/HIGH; nie rozkład rynku", LOW, HYPOTHESIS, "H2; analogi S9"),
  rotorInertiaKgM2: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak danych S8"),
  pitchRatio: Q(1, "kandydaci 0.25,0.5,1,2; brak potwierdzenia", LOW, HYPOTHESIS, "H2: różne składowe komutacji i akustyki"),
  stableStepRatePerSec: Q([100,600], {lower:[50,150], upper:[300,1000]}, LOW, HYPOTHESIS, "H2: zapas na obciążenie sled"),
  musicalStepRatePerSec: Q([80,1000], {lower:[40,150], upper:[500,1450]}, LOW, HYPOTHESIS, "H2; 1450 jest tylko punktem odniesienia S8"),
  preferredStepRatePerSec: Q([150,600], {lower:[80,200], upper:[400,800]}, LOW, HYPOTHESIS, "H2"),
  stableHz: "pitchRatio*stableStepRatePerSec; warunkowe",
  musicalHz: "pitchRatio*musicalStepRatePerSec; warunkowe",
  preferredHz: "pitchRatio*preferredStepRatePerSec; warunkowe",
  accelerationLimitStepsPerSec2: Q(5000, [1000,20000], LOW, HYPOTHESIS, "H2; nie wynik datasheetu"),
  transitionModel: "integral(abs(df_step)/availableAcceleration); prędkość ze znakiem",
  minNoteFloorMs: Q(30, [15,60], LOW, HYPOTHESIS, "H2"),
  minCycles: Q(4, [3,8], LOW, HYPOTHESIS, "H2"),
  minNoteMs: "max(minNoteFloorMs,1000*minCycles/f_audio)",
  preferredNoteMs: Q(100, [60,200], LOW, HYPOTHESIS, "H2"),
  maxNoteChangeRatePerSec: Q(10, [5,20], LOW, HYPOTHESIS, "H2; sprawdzać także rampę i czas nuty"),
  travelSteps: Q(null, UNKNOWN, LOW, HYPOTHESIS, "zależne od całego sled"),
  maxTransitionSemitonesPerSecond: Q(null, UNKNOWN, LOW, HYPOTHESIS, "zastąpiono przyspieszeniem fizycznym")
}

HDD_PERCUSSION: {
  purpose: "rhythm_planning_prior_not_safe_drive_settings",
  electricalMechanicalReference: "model B z S13; parametry tabeli w sekcji C3",
  pulseMs: Q([0.2,5], {lower:[0.1,1], upper:[2,10]}, LOW, HYPOTHESIS, "H3: analiza impulsów, nie gwarancja kontaktu"),
  pulseTypicalMs: Q(1, [0.2,3], LOW, HYPOTHESIS, "H3; napięcie/prąd i pozycja obowiązkowo osobno"),
  safePulseMaxMs: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak granicy termicznej i energii zderzenia"),
  maxContinuousHitsPerSec: Q(5, [2,10], LOW, HYPOTHESIS, "H3: planowanie z czasem resetu"),
  maxBurstHitsPerSec: Q(10, [5,20], LOW, HYPOTHESIS, "H3; wyłącznie z limitem okna i energii"),
  burstWindowMs: Q(500, [100,1000], LOW, HYPOTHESIS, "H3: wybór planistyczny"),
  preferredHitRatePerSec: Q([1,5], {lower:[0.5,2], upper:[3,8]}, LOW, HYPOTHESIS, "H3"),
  nominalStartToStartMs: Q(200, [100,500], LOW, HYPOTHESIS, "H3; obejmuje hit/reset, nie sam cooldown"),
  cooldownModel: "max(mechanicalReadyTime, thermalBudgetReadyTime, impactBudgetReadyTime)",
  thermalRthKPerW: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak danych konkretnej cewki"),
  thermalCthJPerK: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak danych konkretnej cewki"),
  safePeakCurrentA: Q(null, UNKNOWN, LOW, HYPOTHESIS, "limit wzmacniacza nie jest ratingiem cewki"),
  safeImpactEnergyJ: Q(null, UNKNOWN, LOW, HYPOTHESIS, "brak krzywej trwałości crash-stopu"),
  hardCrashStopDefault: false,
  readyStateRequires: ["known_start_position", "reset_complete", "current_and_energy_budget"]
}

HDD_TONAL: {
  purpose: "exploratory_tonal_prior",
  usableHz: Q([100,1500], {lower:[50,200], upper:[800,3000]}, LOW, HYPOTHESIS, "H4: koszt wychylenia i rezonanse, brak krzywej SPL"),
  preferredHz: Q([200,800], {lower:[100,300], upper:[500,1200]}, LOW, HYPOTHESIS, "H4"),
  stableHz: Q(null, UNKNOWN, LOW, HYPOTHESIS, "bez centrowania i modów nie deklarować stabilnego pasma"),
  candidateResonanceBandsHz: [
    Q([3000,5000], "zakres QR opisanej klasy zespołów; inne mody poza nim", MEDIUM, FACT, "S14")
  ],
  referenceModelResonancesHz: Q([4500,5400,5550,5670,7300,7450,8000,9650], "jeden model A; niepewność transferu na inny HDD nieznana", MEDIUM, FACT, "S12"),
  avoidBandsHz: null,
  avoidBandsStatus: "unknown_not_empty_safe_band",
  harmonicRiskModel: "oceniaj podstawę i harmoniczne względem modów oraz ich sprzężenia",
  amplitudeModel: "coupled_RL_backEMF_mechanics; excursion/current/thermal limits",
  allowedExcursionRad: Q(null, UNKNOWN, LOW, HYPOTHESIS, "geometria i pozycja średnia nieznane"),
  minNoteFloorMs: Q(20, [10,50], LOW, HYPOTHESIS, "H4"),
  minCycles: Q(4, [3,8], LOW, HYPOTHESIS, "H4"),
  minNoteMs: "max(minNoteFloorMs,1000*minCycles/f_audio)",
  preferredNoteMs: Q(80, [50,200], LOW, HYPOTHESIS, "H4"),
  maxNoteChangeRatePerSec: Q(15, [5,30], LOW, HYPOTHESIS, "H4; dodatkowo ocena aktualnego stanu"),
  transitionModel: "state_continuity + relevant_modal_decay + envelope",
  transitionCycles: Q(3, [2,6], LOW, HYPOTHESIS, "H4"),
  modalTransientPriorMs: Q(10, [5,120], LOW, HYPOTHESIS, "H4; scenariusz, przykłady zaniku w S12"),
  centerPositionControl: "required_condition_or_explicit_drift_model",
  maxTransitionSemitonesPerSecond: Q(null, UNKNOWN, LOW, HYPOTHESIS, "nieadekwatny pojedynczy limit")
}
```

`null` w polach granic bezpieczeństwa oznacza, że profil służy symulacji i nie nadaje się do automatycznego wyznaczania nastaw mocy. Nie wolno zastępować go nieskończonością ani interpretować jako „brak ograniczenia”. Parametrów modelu A i B nie należy dowolnie mieszać w jednej realizacji — są skorelowanymi zestawami konkretnych modeli.

## F. Jak używać profilu w przyszłym aranżerze

Wystarczą trzy osobne oceny zamiast jednej flagi „zagra/nie zagra”:

1. **Timing:** czy można zaplanować impulsy, rampy, zawracanie lub reset przed następnym zdarzeniem?
2. **Jakość muzyczna:** czy zostanie wystarczająco dużo cykli docelowej nuty, czy nastąpi glissando, modulacja DIR albo rezonansowe wybrzmiewanie?
3. **Obciążenie fizyczne:** czy model mieści prąd, wychylenie, temperaturę i energię kontaktu w znanych granicach? Nieznana granica daje „unknown”, nie „pass”.

Nie zmniejszać automatycznie polifonii tylko dlatego, że pojedyncza nuta ma duży skok półtonów. Najpierw porównać alternatywne urządzenia, ich stan i czas do następnego zawrotu/resetu. Utrata kroków może zmienić położenie bez całkowitego zaniku tonu — licznik wysłanych STEP nie jest pomiarem pozycji.

Do pierwszej symulacji warto uruchamiać wariant optymistyczny, nominalny i pesymistyczny z podanych przedziałów. Wynik „niski drop rate” tylko w wariancie optymistycznym powinien pozostać niepewny. Nie udawać statystycznego Monte Carlo z populacji urządzeń, której rozkładu nie znamy.

## G. Największe niewiadome

| Niewiadoma | Dlaczego ma znaczenie | Co uczciwie zostaje nieznane |
|---|---|---|
| Transfer akustyczny urządzenie→powietrze | identyczne prądy/kroki mogą dawać inną głośność i barwę | dB SPL, loudness(f), jakość tonu |
| Rewizja i algorytm wewnętrznego FDD | zmienia timing, podkroki i wzbudzenie | model muzycznej pracy ponad specyfikacją |
| L, Kt, J i masa sled | decydują o momencie oraz rampie | rzeczywiste maxAcceleration i pull-in całego mechanizmu |
| Mapowanie komutacji DVD na wysokość | możliwe podharmoniczne i dominujące harmoniczne | jednoznaczny zakres MIDI |
| Centrowanie VCM | offset i warunki początkowe zmieniają wychylenie | stabilność długiego tonu |
| Mody i tłumienie konkretnego HDD | długi ringdown i lokalne naprężenia | uniwersalne avoidBands |
| Ciepło i crash-stop | to dwa niezależne limity | bezpieczny prąd, pulseMax, cooldown i liczba cykli życia |
| Kryterium „dobrze brzmi” | zależy od roli muzycznej i montażu | jeden obiektywny preferredHz dla całej klasy |

Nie ma podstaw, by obecnie twierdzić: „DVD zawsze lepiej zagra lead”, „HDD tonal zawsze zagra bas”, „FDD potrzebuje 15 ms po zmianie nuty” albo „cztery fazy dają zawsze ton f/4”.

## H. Późniejsze eksperymenty weryfikujące — nie wykonywane w tym raporcie

Kolejność od testów rozstrzygających podstawowe założenia do charakterystyki muzycznej:

1. **Jednoznaczne liczenie STEP.** Zmierzyć pełne impulsy i rzeczywiste przesunięcia; oddzielić zbocza, podkroki sterownika i cylindry. Wynik rozstrzyga problem współczynnika 2 i travel.
2. **Stała nuta i widmo.** Dla kilku częstotliwości sterowania porównać częstotliwość podstawową, największy pik i harmoniczne. Nie wybierać automatycznie najwyższego piku jako nuty.
3. **Ten sam ton bez zawrotu i z zawrotem.** Zachować prąd/zasilanie, montaż i mikrofon. Sprawdzić, czy zakłócenie pokrywa się w czasie z DIR. To rozdziela błąd impulsów od mechaniki powrotu.
4. **Cztery przejścia z briefu.** Porównać bezpośrednią zmianę okresu i rampę, w środku travel, a następnie blisko zawrotu. Mierzyć osobno onset, błąd wysokości i utratę pozycji.
5. **R i L faz DVD/cewki HDD.** Z pomiaru prądu po krótkim pobudzeniu wyznaczyć τ; porównać wirnik nieruchomy i ruch, żeby ujawnić back-EMF. Nastawy dopiero po ustaleniu ograniczeń prądowych.
6. **DVD: moment i synchronizm pod realnym obciążeniem.** Zmapować pull-in, pull-out, kierunek, pozycję i tryby komutacji; mierzyć realny ruch, nie sam dźwięk.
7. **HDD: najpierw centrowanie i wychylenie bez kontaktu.** Sprawdzić drift, symetrię, start/stop i odpowiedź na małe pobudzenie. Dopiero potem badać pasmo tonalne.
8. **Modalny sweep małą amplitudą.** Wykryć rezonanse oraz antyrezonanse i rozdzielić drgania ramienia od obudowy. Ocenić harmoniczne square, nie tylko sinus na częstotliwości podstawowej.
9. **Perkusja: kontrolowany start i reset.** Sprawdzić, czy identyczny impuls daje powtarzalny kontakt przy identycznym położeniu. Rejestrować prąd, timing kontaktu i odbicie; mocne zderzenia nie są pierwszym testem.
10. **Seria o ograniczonej energii i obserwacja temperatury.** Ustalić budżet cieplny osobno od mechanicznego. Dopiero wtedy nadawać pola `safe*` i dopuszczać długie serie/drone.

Kryteria oceny, np. dopuszczalny błąd stroju, spadek amplitudy czy częstość błędów kroku, powinny być ustalone przed pomiarem. Ten raport ich nie udaje jako istniejących norm instrumentu.

## I. Rejestr źródeł i jakość dowodów

Linki prowadzą do źródeł wykorzystanych albo jawnie oznaczonych jako niepełne. Daty starych dokumentów pochodzą z dokumentów, nie z mylących dat indeksowania wyszukiwarki. Archiwalny hosting PDF nie zmienia autorstwa karty producenta.

| ID | Źródło / URL | Klasa i użycie |
|---|---|---|
| S1 | [TEAC FD-235HF-C891, Specification Rev. A, §4.5, §4.7, §8.3, §9.2](https://www.scribd.com/document/295226615/TEAC-FD-235HF-C891-Micro-Floppy-Disk-Drive-Specification) | dokument producenta w transkrypcji; liczby 3/4/15/18 ms, geometria; µs ostrożnie |
| S1b | [TEAC FD-235HF-A291, PDF](https://hxc2001.com/download/datasheet/floppy/thirdparty/Teac/TEAC-FD235HF-A291.PDF) | skan specyfikacji producenta; dodatkowy wariant FD-235 |
| S2 | [Samsung SFD-321B OEM manual, SEMA, s. 4, 18, 22](https://jope.fi/drives/SAMSUNG-SFD321B-070103.pdf) | pierwotna instrukcja OEM, 3/15/18 ms i timing |
| S3 | [Sony MPF920/MPF820, karta 09/2001](https://www.sunteam.nl/index.php?attachment_id=2&dispatch=attachments.getfile) | karta producenta; 3/15 ms; ostrożność z pozostałymi błędami tabeli |
| S4 | [Panasonic JU-257A6P Application Manual, F1905680A4, 1997, §1.2](https://bitsavers.trailing-edge.com/pdf/panasonic/floppy/JU-2x7/F1905680A4_JU-257A_Application_Manual_199705.pdf) | producent; odczyt dostępnej tabeli 3/15/18 ms |
| S5 | [Alps DF35, DF354H/DF354N, karta producenta](https://manualzilla.com/doc/7183736/alps-electronics-fdd-1.44mb-df354-black) | transkrypcja karty; 3/15 ms |
| S6 | [Paweł Zadrożniak, The Floppotron 3.0, 2022](https://silent.org.pl/home/2022/06/13/the-floppotron-3-0/) | autor projektu: FDD, obwiednie, skanery i perkusja HDD; brak krzywych muzycznych |
| S7 | [Moppy2](https://github.com/samphonic/Moppy2) oraz [MoppyClassic](https://github.com/samphonic/MoppyClassic) | pierwotne repozytoria; odczyt szczegółowych plików w tym researchu ograniczony — nie dowód wartości timingów |
| S8 | [Minebea PL15S-020, karta 2004, PDF](https://forums.parallax.com/uploads/attachments/45257/55274.pdf) | producent; R, V, kroki, śruba i referencyjna charakterystyka momentu |
| S9 | [Stegia PM stepper, tabela 15S](https://stegia.com/sv/motorer/pm-stegmotor/) | producent/dostawca rozwiązań; analogi R/L i torque, nie potwierdzeni dawcy DVD |
| S10 | [NMB, Stepping Motor Engineering](https://nmbtc.com/resources/stepping-motor-engineering/) oraz [TI, How to Reduce Audible Noise in Stepper Motors](https://www.ti.com/lit/an/slvaes8/slvaes8.pdf) | dokumentacja producentów; tryby kroku, tętnienia i hałas |
| S11 | [Texas Instruments DRV8833, Rev. E, §7.3](https://www.ti.com/lit/ds/symlink/drv8833.pdf) | datasheet; mostki, decay, current chopping i xISEN |
| S12 | [A two-degree-of-freedom time-optimal solution for hard disk drive servo problems, Appendix Table AI](https://www.researchgate.net/publication/229773625_A_two-degree-of-freedom_time-optimal_solution_for_hard_disk_drive_servo_problems) | publikacja naukowa, model 13 kTPI; parametry i mody; nie rating cewki do audio |
| S13 | [Shaikh i in., H∞ Loop-Shaping Continuous-Time Controller Design for Nonlinear HDD Systems, IEEE Access 2024, tab. 1–2](https://publikace.k.utb.cz/bitstream/handle/10563/1012172/Fulltext_1012172.pdf?isAllowed=y&sequence=1) | publikacja naukowa; Model B i ujęcie modalne; model odziedziczony z wcześniejszej literatury, nie nowy zbiór pomiarów dysków |
| S14 | [Xu i in., Design and analysis of a passive damping device in a head actuator assembly, 2002](https://journals.sagepub.com/doi/abs/10.1243/0954406021525061) | publikacja naukowa; dostępny opis QR 3–5 kHz; nie pełny zbiór surowych danych |
| S15 | [Berkeley CML, raport G01003, tab. 5.1, s. 112](https://cml.berkeley.edu/wp-content/uploads/gold-reports/G01003.pdf) | badawcze zawieszenie stal–krzem; konkretne mody, nie seria komercyjnych HDD |
| S16 | [Ted Sheflin, Hard Drive Voice Coil Speaker, 2023](https://hackaday.io/project/190947-hard-drive-voice-coil-speaker/details) | autor projektu maker; potwierdzenie działania i centrowania; brak kalibrowanego pasma |
| S17 | [Innerlogics, Spin Doctor](https://blog.innerlogics.com/spin-doctor/) | autor projektu maker; para HDD ze zwrotnicą, nierówne pasmo; brak ilościowej charakterystyki |
| S18 | [Erich Styger, Making Music with Floppy Disk Drives, 2016](https://mcuoneclipse.com/2016/06/15/tutorial-making-music-with-floppy-diskdrives/) | autor implementacji; praktyczny zakres około 400 Hz, ale niespójne mapowanie MIDI w tekście |
| S19 | [US8451564B2, Impact energy dispersing crash stop](https://patents.google.com/patent/US8451564B2/en) oraz [US6567232, retract with bounce detector](https://patents.justia.com/patent/6567232) | patenty techniczne; kontakt, absorpcja energii, odbicie; nie krzywe trwałości muzycznej |
| S20 | [JP2008282451A, Seek method of optical disk device](https://patents.google.com/patent/JP2008282451A/en) | patent techniczny sled stepper; nie specyfikacja nut |

### Granice przeprowadzonego researchu

Nie uzyskano kompletnego źródłowego profilu timingów Mitsumi i Chinon, reprezentatywnej bazy indukcyjności silników DVD, krzywych SPL odzyskanych urządzeń, termicznych ratingów odsłoniętych VCM ani trwałości crash-stopów przy graniu. Nie potwierdzono także tabel transitionPenalty pochodzących od autorów Moppy/Floppotron. Materiały wtórne, ogłoszenia sprzedażowe i niesprawdzone poradniki nie zostały użyte do wypełniania tych luk fałszywie precyzyjnymi liczbami.

**Najważniejszy rezultat:** profile powinny przechowywać stan mechaniczny, pochodzenie danych i niepewność. Sama tabela `minHz/maxHz/minNoteMs` bez tych informacji byłaby wygodna, ale przewidywałaby zachowanie sprzętu z nadmierną pewnością.
