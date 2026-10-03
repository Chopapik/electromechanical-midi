// ============================================================
// HDD VCM - TEST A/B Z DIODA D13 JAKO ZNACZNIKIEM
// ============================================================
//
// Poprzedni test byl niejednoznaczny: obie grupy wygladaly podobnie.
// Teraz kazda grupa ma SWOJ ZNACZNIK na wbudowanej diodzie Arduino:
//
//   DIODA D13 SWIECI   -> aktualnie testowany kierunek A
//                         (PNP_L LOW = D7, NPN_R HIGH = D10)
//
//   DIODA D13 ZGASZONA -> aktualnie testowany kierunek B
//                         (PNP_R LOW = D8, NPN_L HIGH = D9)
//
// Wzorzec:
//   [dioda ON  ~5 s]  4 uderzenia A co 1 s
//   [dioda OFF ~12 s] 4 uderzenia B co 1 s, potem dluga przerwa
//   ... i od nowa ...
//
// Dluga przerwa jest tylko po grupie B, wiec poczatek cyklu (dioda
// zapala sie) jest zawsze jednoznaczny.
//
// Impuls 20 ms, po kazdym od razu allOff() - cewka nie jest trzymana.
// Stan BEZPIECZNY: D7 HIGH, D8 HIGH, D9 LOW, D10 LOW
// ============================================================

#include <Arduino.h>

const byte PNP_L = 7;
const byte PNP_R = 8;
const byte NPN_L = 9;
const byte NPN_R = 10;
const byte LED_PIN = 13;   // wbudowana dioda Arduino - czysto informacyjna

constexpr uint16_t HIT_MS         = 20;
constexpr uint16_t SETTLE_MS      = 20;
constexpr uint16_t GAP_MS         = 1000;
constexpr uint8_t  HITS_PER_GROUP = 4;
constexpr uint16_t PHASE_TAIL_MS  = 2000;   // ogon fazy z dioda ON
constexpr uint16_t CYCLE_PAUSE_MS = 8000;   // dluga przerwa = koniec cyklu
constexpr uint16_t STARTUP_MS     = 3000;

void allOff()
{
    digitalWrite(PNP_L, HIGH);
    digitalWrite(PNP_R, HIGH);
    digitalWrite(NPN_L, LOW);
    digitalWrite(NPN_R, LOW);
}

void hitA()
{
    allOff();
    delay(SETTLE_MS);

    digitalWrite(PNP_L, LOW);
    digitalWrite(NPN_R, HIGH);

    delay(HIT_MS);

    allOff();
}

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
    Serial.println(F("HDD A/B z dioda: ON=A(D7+D10), OFF=B(D8+D9)"));

    delay(STARTUP_MS);
}

void loop()
{
    // ---------- FAZA A: dioda SWIECI ----------
    digitalWrite(LED_PIN, HIGH);
    Serial.println(F("DIODA ON  -> kierunek A (D7 LOW + D10 HIGH)"));

    for (uint8_t i = 0; i < HITS_PER_GROUP; i++)
    {
        hitA();
        delay(GAP_MS);
    }

    delay(PHASE_TAIL_MS);
    digitalWrite(LED_PIN, LOW);

    // ---------- FAZA B: dioda ZGASZONA ----------
    Serial.println(F("DIODA OFF -> kierunek B (D8 LOW + D9 HIGH)"));

    for (uint8_t i = 0; i < HITS_PER_GROUP; i++)
    {
        hitB();
        delay(GAP_MS);
    }

    delay(CYCLE_PAUSE_MS);
}
