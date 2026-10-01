#include <Arduino.h>
#include <math.h>

// ============================================================
// FDD -> ARDUINO UNO
// ============================================================

constexpr uint8_t DIR_PIN    = 2;
constexpr uint8_t STEP_PIN   = 3;
constexpr uint8_t TRACK0_PIN = 4;
constexpr uint8_t SELECT_PIN = 5;

constexpr uint8_t DIR_TOWARD_TRACK0 = HIGH;
constexpr uint8_t DIR_AWAY_TRACK0   = LOW;

// ============================================================
// MECHANIKA
// ============================================================

constexpr int MIN_TRACK = 4;
constexpr int MAX_TRACK = 72;

int currentTrack = 0;
bool movingAway = true;

// ============================================================
// NUTY Z POCZĄTKU TRACKU "JONNY GREENWOOD"
//
// Oryginał:
// C#4, A4, C#4, G#4
//
// Transpozycja -5 półtonów:
// G#3, E4, G#3, D#4
// ============================================================

struct NoteEvent {
    uint8_t midiNote;
    uint16_t durationMs;
    uint16_t gapAfterMs;
};

const NoteEvent phrase[] = {
    {56, 1000, 90},   // G#3  (oryginalnie C#4)
    {64, 500,  45},   // E4   (oryginalnie A4)
    {56, 500,  45},   // G#3
    {63, 1000, 90},   // D#4  (oryginalnie G#4)

    // po małym akordzie w oryginale lecą znowu pojedyncze
    {60, 500,  45},   // C4
    {59, 500,  45},   // B3
    {55, 500,  45},   // G3
    {48, 1800, 250}   // C3
};

constexpr uint8_t PHRASE_LENGTH =
    sizeof(phrase) / sizeof(phrase[0]);

// ============================================================
// LOW LEVEL
// ============================================================

void stepPulse()
{
    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(30);
    digitalWrite(STEP_PIN, HIGH);
}

bool isTrackZero()
{
    return digitalRead(TRACK0_PIN) == LOW;
}

// ============================================================
// HOMING
// ============================================================

bool homeHead()
{
    Serial.println(F("Homing..."));

    digitalWrite(DIR_PIN, DIR_TOWARD_TRACK0);
    delayMicroseconds(30);

    for (int i = 0; i < 90; i++)
    {
        if (isTrackZero())
        {
            currentTrack = 0;
            movingAway = true;

            Serial.println(F("TRACK0 OK"));
            return true;
        }

        stepPulse();
        delay(5);
    }

    Serial.println(F("ERROR: TRACK0"));
    return false;
}

// ============================================================
// STARTOWA POZYCJA
// ============================================================

bool prepareHead()
{
    if (!homeHead())
        return false;

    digitalWrite(DIR_PIN, DIR_AWAY_TRACK0);
    delayMicroseconds(30);

    for (int i = 0; i < 10; i++)
    {
        stepPulse();
        delay(5);
        currentTrack++;
    }

    movingAway = true;

    return true;
}

// ============================================================
// RUCH PODCZAS GRANIA
// ============================================================

void musicalStep()
{
    if (movingAway && currentTrack >= MAX_TRACK)
    {
        movingAway = false;

        digitalWrite(
            DIR_PIN,
            DIR_TOWARD_TRACK0
        );

        delayMicroseconds(30);
    }
    else if (!movingAway && currentTrack <= MIN_TRACK)
    {
        movingAway = true;

        digitalWrite(
            DIR_PIN,
            DIR_AWAY_TRACK0
        );

        delayMicroseconds(30);
    }

    stepPulse();

    if (movingAway)
        currentTrack++;
    else
        currentTrack--;
}

// ============================================================
// MIDI -> Hz
// ============================================================

float midiToFrequency(uint8_t midiNote)
{
    return 440.0f *
        powf(
            2.0f,
            (static_cast<int>(midiNote) - 69) / 12.0f
        );
}

// ============================================================
// GRANIE NUTY
// ============================================================

void playFrequency(
    float frequency,
    uint16_t durationMs
)
{
    const unsigned long intervalUs =
        static_cast<unsigned long>(
            1000000.0f / frequency
        );

    const unsigned long startTime = millis();

    unsigned long nextStepTime = micros();

    while (millis() - startTime < durationMs)
    {
        const unsigned long now = micros();

        if ((long)(now - nextStepTime) >= 0)
        {
            musicalStep();

            nextStepTime += intervalUs;
        }
    }
}

// ============================================================
// FRAZA
// ============================================================

void playPhrase()
{
    Serial.println();
    Serial.println(F("============================"));
    Serial.println(F(" JONNY GREENWOOD - INTRO"));
    Serial.println(F("============================"));

    for (uint8_t i = 0; i < PHRASE_LENGTH; i++)
    {
        const float freq =
            midiToFrequency(
                phrase[i].midiNote
            );

        Serial.print(F("MIDI "));
        Serial.print(phrase[i].midiNote);

        Serial.print(F(" -> "));
        Serial.print(freq, 2);

        Serial.println(F(" Hz"));

        playFrequency(
            freq,
            phrase[i].durationMs
        );

        delay(
            phrase[i].gapAfterMs
        );
    }

    Serial.println(F("Phrase done."));
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(115200);

    pinMode(DIR_PIN, OUTPUT);
    pinMode(STEP_PIN, OUTPUT);
    pinMode(TRACK0_PIN, INPUT_PULLUP);
    pinMode(SELECT_PIN, OUTPUT);

    digitalWrite(STEP_PIN, HIGH);
    digitalWrite(SELECT_PIN, LOW);

    delay(500);

    if (!prepareHead())
    {
        while (true)
        {
            delay(1000);
        }
    }
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    playPhrase();

    Serial.println(F("Restart za 4 sekundy..."));

    delay(4000);

    prepareHead();
}