// ============================================================
// HDD VCM - TEST JEDNEGO KIERUNKU (bez mieszania A/B)
// ============================================================
//
// W poprzednim tescie oba kierunki ladowaly naprzemiennie i ramie
// zachowywalo sie nieprzewidywalnie. Tutaj testujemy DOKLADNIE JEDEN
// kierunek na raz - kierunek wybiera stala DIRECTION ponizej.
//
//   DIRECTION = 'A'  ->  PNP_L LOW (D7) + NPN_R HIGH (D10)   prad L -> R
//   DIRECTION = 'B'  ->  PNP_R LOW (D8) + NPN_L HIGH (D9)    prad R -> L
//
// Impuls HIT_MS = 20 ms (tyle, ile w Twoim dzialajacym tescie),
// potem od razu allOff() - cewka NIE jest trzymana.
//
// Dioda D13 swieci ciagle = plytka zyje i wystawia impulsy.
//
// Stan BEZPIECZNY: D7 HIGH, D8 HIGH, D9 LOW, D10 LOW
// ============================================================

#include <Arduino.h>

const byte PNP_L = 7;
const byte PNP_R = 8;
const byte NPN_L = 9;
const byte NPN_R = 10;
const byte LED_PIN = 13;

// ---------- CO TESTOWAC ----------
constexpr char DIRECTION = 'B';          // <== 'A' albo 'B'

constexpr uint16_t HIT_MS     = 22;      // czas impulsu
constexpr uint16_t SETTLE_MS  = 20;      // dead-time przed impulsem
constexpr uint16_t PERIOD_MS  = 2000;    // jedno uderzenie co ~2 s
constexpr uint16_t STARTUP_MS = 3000;

void allOff()
{
    digitalWrite(PNP_L, HIGH);
    digitalWrite(PNP_R, HIGH);
    digitalWrite(NPN_L, LOW);
    digitalWrite(NPN_R, LOW);
}

// Wystawienie impulsu w wybranym kierunku.
void hit()
{
    allOff();
    delay(SETTLE_MS);

    if (DIRECTION == 'A')
    {
        digitalWrite(PNP_L, LOW);    // lewy koniec cewki -> +5 V
        digitalWrite(NPN_R, HIGH);   // prawy koniec cewki -> GND
    }
    else
    {
        digitalWrite(PNP_R, LOW);    // prawy koniec cewki -> +5 V
        digitalWrite(NPN_L, HIGH);   // lewy koniec cewki -> GND
    }

    delay(HIT_MS);

    allOff();
}

void setup()
{
    // Bezpieczne poziomy ZANIM piny stana sie OUTPUT.
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

    // Dioda swieci = test trwa.
    digitalWrite(LED_PIN, HIGH);

    Serial.begin(115200);
    Serial.print(F("HDD test kierunku: "));
    Serial.print(DIRECTION);
    Serial.print(F("  HIT_MS="));
    Serial.println(HIT_MS);

    delay(STARTUP_MS);
}

void loop()
{
    hit();
    delay(PERIOD_MS);
}
