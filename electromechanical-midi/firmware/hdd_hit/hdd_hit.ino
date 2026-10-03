// ============================================================
// HDD jako mechaniczny instrument perkusyjny
// STROJENIE CZASU IMPULSU UDERZENIA
// ============================================================
//
// Hardware:
//   mostek H: 2x S8550 (PNP) + 2x S8050 (NPN) + 4x dioda flyback
//   zasilanie mostka: 5 V, cewka VCM HDD ~23,3 Ohm
//
// Pinout:
//   D7  = PNP_L        D8  = PNP_R
//   D9  = NPN_L        D10 = NPN_R
//
// Stan BEZPIECZNY (cewka bez pradu):
//   D7 HIGH   D8 HIGH   D9 LOW   D10 LOW
//
// Uderzenie (JEDYNY uzywany kierunek - daje mocne uderzenie, ramie
// samo wraca po wylaczeniu cewki):
//   D7 LOW    D8 HIGH   D9 LOW   D10 HIGH
//
// Cewka NIE jest trzymana pod pradem: po impulsie od razu allOff().
// Zadnego PWM - tylko czyste digitalWrite.
//
// TEN TEST: HIT_MS = 200
// ============================================================

#include <Arduino.h>

// ---------- pinout mostka H ----------
constexpr uint8_t PIN_PNP_L = 7;
constexpr uint8_t PIN_PNP_R = 8;
constexpr uint8_t PIN_NPN_L = 9;
constexpr uint8_t PIN_NPN_R = 10;

// ---------- parametry testu ----------
constexpr uint16_t HIT_MS       = 200;    // <== STROJONY CZAS IMPULSU
constexpr uint16_t STARTUP_MS   = 3000;  // odczekaj po starcie
constexpr uint16_t DEAD_TIME_MS = 20;    // krotki dead-time po impulsie
constexpr uint16_t PERIOD_MS    = 2000;  // jedno uderzenie co ~2 s

// Wszystkie tranzystory zatkane => cewka bez pradu.
// Kolejnosc: najpierw PNP (zdejmujemy zasilanie gornej galezi),
// potem NPN - dzieki temu flyback ma chwile na zwrot energii.
static inline void allOff()
{
    digitalWrite(PIN_PNP_L, HIGH);
    digitalWrite(PIN_PNP_R, HIGH);
    digitalWrite(PIN_NPN_L, LOW);
    digitalWrite(PIN_NPN_R, LOW);
}

void setup()
{
    // NAJWAZNIEJSZE: bezpieczne poziomy USTAWIONE ZANIM pin stanie sie
    // OUTPUT. Na AVR digitalWrite() przed pinMode() wlacza pull-up, wiec
    // PNP (HIGH) sa zatkane od pierwszej chwili, a NPN (LOW) nie dostaja
    // dodatniego napiecia na baze.
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
    Serial.print(F("HDD hit: HIT_MS="));
    Serial.println(HIT_MS);

    delay(STARTUP_MS);
}

void loop()
{
    // ---------- UDERZENIE ----------
    digitalWrite(PIN_PNP_L, LOW);    // PNP_L przewodzi
    digitalWrite(PIN_PNP_R, HIGH);   // PNP_R zatkany
    digitalWrite(PIN_NPN_L, LOW);    // NPN_L zatkany
    digitalWrite(PIN_NPN_R, HIGH);   // NPN_R przewodzi

    delay(HIT_MS);

    // ---------- natychmiast OFF ----------
    allOff();

    delay(DEAD_TIME_MS);
    delay(PERIOD_MS);
}
