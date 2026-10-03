// ============================================================
// HDD VCM - TEST: CZY RAMIE WRACA SAMO?
// ============================================================
//
// Podejrzenie: ramie jest trzymane magnesem parkujacym, impuls B
// wyrywa je i uderza w ogranicznik, ale ramie TAM ZOSTAJE - nie ma
// sily, ktora je cofnie. Dlatego ten sam impuls raz uderza (gdy ramie
// stoi w parku), a raz nie rusza nic (gdy ramie juz wisi na koncu).
//
// Ten test robi DOKLADNIE JEDNO uderzenie na cykl i daje dluga cisze,
// zeby bylo widac, czy ramie wraca na pozycje wyjsciowa:
//
//   [6 s ciszy]  <- ramie powinno stac w parku
//   [1x impuls B 25 ms]  <- uderzenie
//   [6 s ciszy]  <- OBSERWUJ: czy ramie wrocilo?
//   ... powtorka ...
//
// Kierunek B = PNP_R LOW (D8) + NPN_L HIGH (D9) - ten, ktory uderza.
// Stan BEZPIECZNY: D7 HIGH, D8 HIGH, D9 LOW, D10 LOW
// ============================================================

#include <Arduino.h>

const byte PNP_L = 7;
const byte PNP_R = 8;
const byte NPN_L = 9;
const byte NPN_R = 10;
const byte LED_PIN = 13;

constexpr uint16_t HIT_MS     = 25;     // wyraznie powyzej progu
constexpr uint16_t SETTLE_MS  = 20;
constexpr uint16_t REST_MS    = 6000;   // cisza PRZED uderzeniem
constexpr uint16_t WATCH_MS   = 6000;   // cisza PO uderzeniu - obserwacja
constexpr uint16_t STARTUP_MS = 3000;

void allOff()
{
    digitalWrite(PNP_L, HIGH);
    digitalWrite(PNP_R, HIGH);
    digitalWrite(NPN_L, LOW);
    digitalWrite(NPN_R, LOW);
}

// Kierunek B: prawy koniec cewki -> +5 V, lewy -> GND.
void hitB()
{
    allOff();
    delay(SETTLE_MS);

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
    Serial.println(F("HDD: 1 uderzenie B co ~12 s - obserwuj powrot ramienia"));

    delay(STARTUP_MS);
}

void loop()
{
    // --- cisza przed uderzeniem ---
    digitalWrite(LED_PIN, LOW);
    Serial.println(F("REST 6s"));
    delay(REST_MS);

    // --- UDERZENIE (dioda zapala sie na czas impulsu) ---
    digitalWrite(LED_PIN, HIGH);
    Serial.println(F(">>> HIT (B)"));
    hitB();
    digitalWrite(LED_PIN, LOW);

    // --- dluga cisza: czy ramie wrocilo? ---
    Serial.println(F("OBSERWUJ 6s"));
    delay(WATCH_MS);
}
