// ============================================================
// HDD VCM - TEST DIAGNOSTYCZNY: DLUGIE WYSTEROWANIE
// ============================================================
//
// Po co: przy krotkich impulsach (10-200 ms) slychac klik, ale ramie
// stoi. Krotki impuls nie odroznia dwoch przyczyn:
//   (a) mostek NIE przewodzi / cewka nie dostaje pradu,
//   (b) mostek przewodzi, ale 200 ms to za malo na ruszenie ramienia.
//
// Ten test wysterowuje cewke CIAGLE przez HOLD_MS = 2000 ms.
//   * ramie sie ruszy  -> mostek i cewka dzialaja, wracamy do strojenia
//                         krotszych impulsow,
//   * ramie stoi        -> przez cewke NIE plynie prad (okablowanie mostka,
//                         E/C w PNP, diody flyback, zly przekroj cewki).
//
// Cewka NIE jest trzymana na stale: 2 s ON, potem 4 s przerwy (33%).
// To test jednorazowy - docelowo impuls bedzie krotki.
//
// Stan BEZPIECZNY (cewka bez pradu):
//   D7 HIGH   D8 HIGH   D9 LOW   D10 LOW
// Uderzenie (jedyny kierunek):
//   D7 LOW    D8 HIGH   D9 LOW   D10 HIGH
// ============================================================

#include <Arduino.h>

constexpr uint8_t PIN_PNP_L = 7;
constexpr uint8_t PIN_PNP_R = 8;
constexpr uint8_t PIN_NPN_L = 9;
constexpr uint8_t PIN_NPN_R = 10;

constexpr uint16_t HOLD_MS    = 2000;  // <== CIAGLE wysterowanie
constexpr uint16_t OFF_MS     = 4000;  // przerwa, zeby cewka odpoczela
constexpr uint16_t STARTUP_MS = 3000;

static inline void allOff()
{
    digitalWrite(PIN_PNP_L, HIGH);
    digitalWrite(PIN_PNP_R, HIGH);
    digitalWrite(PIN_NPN_L, LOW);
    digitalWrite(PIN_NPN_R, LOW);
}

void setup()
{
    // Bezpieczne poziomy ZANIM piny stana sie OUTPUT (patrz hdd_hit.ino).
    digitalWrite(PIN_PNP_L, HIGH);
    digitalWrite(PIN_PNP_R, HIGH);
    digitalWrite(PIN_NPN_L, LOW);
    digitalWrite(PIN_NPN_R, LOW);

    pinMode(PIN_PNP_L, OUTPUT);
    pinMode(PIN_PNP_R, OUTPUT);
    pinMode(PIN_NPN_L, OUTPUT);
    pinMode(PIN_NPN_R, OUTPUT);

    allOff();

    Serial.begin(115200);
    Serial.print(F("HDD hold test: HOLD_MS="));
    Serial.println(HOLD_MS);

    delay(STARTUP_MS);
}

void loop()
{
    Serial.println(F("HIT 2s"));
    digitalWrite(PIN_PNP_L, LOW);
    digitalWrite(PIN_PNP_R, HIGH);
    digitalWrite(PIN_NPN_L, LOW);
    digitalWrite(PIN_NPN_R, HIGH);

    delay(HOLD_MS);

    allOff();
    Serial.println(F("OFF"));

    delay(OFF_MS);
}
