// ============================================================
// HDD VCM jako PERKUSJA - PELNY CYKL: PARKOWANIE -> UDERZENIE
// ============================================================
//
// Ustalilismy empirycznie (testy 20/19/18/15/10 ms + obserwacja ramienia):
//
//   * ramie NIE wraca samo - trzeba je aktywnie odwiezc do parku,
//   * impuls B wyrywa ramie z parku => UDERZENIE,
//   * gdy ramie stoi poza parkiem, impuls B nic nie robi,
//   * wiec do wielokrotnych uderzen potrzebne sa OBA kierunki.
//
// Kierunki:
//   PARK   (A) = PNP_L LOW (D7) + NPN_R HIGH (D10)  - odwozi ramie do parku
//   STRIKE (B) = PNP_R LOW (D8) + NPN_L HIGH (D9)   - wyrywa ramie => HIT
//
// Cykl:
//   [PARK PARK_MS] -> allOff -> [SETTLE_MS na osiadniecie w parku]
//   -> [STRIKE HIT_MS] -> allOff -> [RESPITE_MS do nastepnego cyklu]
//
// Dioda D13 mrugnie w chwili uderzenia (znacznik do obserwacji).
// Cewka nie jest trzymana: po kazdym impulsie natychmiast allOff().
//
// Stan BEZPIECZNY: D7 HIGH, D8 HIGH, D9 LOW, D10 LOW
// ============================================================

#include <Arduino.h>

const byte PNP_L = 7;
const byte PNP_R = 8;
const byte NPN_L = 9;
const byte NPN_R = 10;
const byte LED_PIN = 13;

// ---------- parametry USTALONE EMPIRYCZNIE ----------
//   PARK_MS = 40  - z zapasem odwozi ramie do parku
//   HIT_MS  = 25  - najlepsze uderzenie (30 ms juz nic nie dodaje)
constexpr uint16_t PARK_MS         = 40;    // impuls parkujacy (kierunek A)
constexpr uint16_t PARK_SETTLE_MS  = 40;    // czas na osiadniecie w parku
constexpr uint16_t HIT_MS          = 25;    // impuls uderzenia (kierunek B)
constexpr uint16_t RESPITE_MS      = 900;   // przerwa do nastepnego cyklu
constexpr uint16_t STARTUP_MS      = 3000;

void allOff()
{
    digitalWrite(PNP_L, HIGH);
    digitalWrite(PNP_R, HIGH);
    digitalWrite(NPN_L, LOW);
    digitalWrite(NPN_R, LOW);
}

// Kierunek A - odwozi ramie do pozycji parkowania.
void parkPulse()
{
    allOff();
    digitalWrite(PNP_L, LOW);
    digitalWrite(NPN_R, HIGH);
    delay(PARK_MS);
    allOff();
}

// Kierunek B - wyrywa ramie z parku: UDERZENIE.
void strikePulse()
{
    allOff();
    digitalWrite(PNP_R, LOW);
    digitalWrite(NPN_L, HIGH);
    delay(HIT_MS);
    allOff();
}

void setup()
{
    digitalWrite(PNP_L, HIGH);
    digitalWrite(PNP_R, HIGH);
    digitalWrite(NPN_L, LOW);
    digitalWrite(NPN_R, LOW);
    digitalWrite(LED_PIN, LOW);

    pinMode(PNP_L, OUTPUT);
    pinMode(PNP_R, OUTPUT);
    pinMode(NPN_L, OUTPUT);
    pinMode(NPN_R, OUTPUT);
    pinMode(LED_PIN, OUTPUT);

    allOff();

    Serial.begin(115200);
    Serial.println(F("HDD perkusja: PARK 40ms -> STRIKE 25ms, 1 uderzenie/s"));

    // Najpierw zaparkuj ramie, zeby pierwszy cykl byl powtarzalny.
    parkPulse();
    delay(PARK_SETTLE_MS);

    delay(STARTUP_MS);
}

void loop()
{
    // 1) odwiez ramie do parku
    parkPulse();
    delay(PARK_SETTLE_MS);

    // 2) UDERZENIE (dioda mrugnie)
    digitalWrite(LED_PIN, HIGH);
    strikePulse();
    digitalWrite(LED_PIN, LOW);

    // 3) przerwa do nastepnego uderzenia
    delay(RESPITE_MS);
}
