# Eksperyment: wspólny limit HDD 8 HIT/s

2026-10-24. Poprzedni limit 12 HIT/s wprowadził commit `bb962eb`.
Zmiana dotyczy budżetu uderzeń HDD, a nie liczby napędów FDD/HDD ani transpozycji.

Każdy preset dopuszcza teraz maksymalnie 8 komend HDD HIT w dowolnym ruchomym
oknie `[t, t + 1 s)`, łącznie dla wszystkich HDD. Istniejąca selekcja zachowuje
pierwszeństwo stopy i werbla przed słabszymi dodatkami. Pozostawione uderzenia
nie są przesuwane w czasie; nadmiarowe są pomijane z powodem `HDD_RATE_LIMIT`.
Końcowa kontrola obejmuje ręczne przypisania i reinforcement. Kompilator odrzuca
przekroczenie limitu. REAL i VIRTUAL korzystają ze wspólnego planu wykonania.
Dodatkowe impulsy artykulacji wirtualnego werbla nie są osobnymi komendami HIT.

## Weryfikacja offline

775 testów backendu przeszło poprawnie. Testy obejmują wszystkie dziewięć presetów,
granice ruchomego okna, pierwszeństwo akcentów, brak przesuwania czasów,
reinforcement oraz odrzucenie dziewiątej komendy HIT przez kompilator.
Przykład testujący stabilność routingu zwolniono z trzech uderzeń co 0,3 s do
trzech co 0,5 s, aby nadal badał routing poniżej nowego limitu, a nie selekcję.

Porównanie na `midi/0068-06-radiohead-2003-where_i_end_and_you_begin.mid`,
preset `instrument_roles_unison4`, z identyczną aktualną konfiguracją urządzeń:

| Pomiar | Limit 12 | Limit 8 |
| --- | ---: | ---: |
| Komendy HDD HIT w całym utworze | 1507 | 1438 |
| Maksimum w ruchomej sekundzie | 9 | 8 |
| Maksymalne przesunięcie względem źródłowego uderzenia | 0 ms | 0 ms |
| HIT w 0:20–0:32 | 83 | 74 |
| HIT w 2:07–2:22 | 93 | 93 |

To kontrola planowania, nie ocena brzmienia. Nie wykonywano odsłuchu na fizycznych
napędach, nie zmieniano firmware, parametrów impulsów ani limitów cewek.
Zgłoszenia dotyczące rytmu FDD i fałszowania pozostają osobnymi zadaniami.
