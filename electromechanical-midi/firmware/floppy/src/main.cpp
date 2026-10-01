// ============================================================
// electromechanical-midi / firmware / floppy
//
// Arduino Uno jako PROSTY KONTROLER WYKONAWCZY stacji dyskietek.
//
//   host (Python)  --USB Serial-->  Arduino  --STEP/DIR-->  FDD
//
// Arduino NIE jest urzadzeniem USB MIDI i NIE parsuje plikow MIDI.
// Dostaje z hosta gotowa czestotliwosc w Hz i ja odtwarza.
//
// Protokol tekstowy (115200 8N1, linie zakonczone '\n'):
//
//   PING            -> PONG
//   PLAY <hz>       -> (brak odpowiedzi, patrz ACK_PLAY_STOP)
//   STOP            -> (brak odpowiedzi, patrz ACK_PLAY_STOP)
//   HOME            -> OK ... po dojechaniu -> READY
//   STATUS          -> STATUS track=<n> dir=<...> homed=<0|1> playing=<0|1> track0=<0|1> hz=<...>
//   cokolwiek innego-> ERR UNKNOWN_CMD
//
// Bledy: ERR NOT_HOMED / ERR BUSY / ERR FREQ_RANGE / ERR MISSING_FREQ
//        ERR BAD_FREQ / ERR HOME_FAILED / ERR POS_LOST / ERR HOST_TIMEOUT
//        ERR LINE_TOO_LONG / ERR UNKNOWN_CMD
//
// Uwaga o ACK_PLAY_STOP:
//   PLAY/STOP sa celowo CICHE. Odpowiadanie "OK" na kazda nuta zwieksza
//   ruch w obie strony i - co wazniejsze - kazdy Serial.println() jest
//   BLOKUJACY, gdy bufor TX (64 B) jest pelny. W najgorszym razie (host
//   przestal czytac, lawina bledow, --no-wait) zablokowaloby to petle
//   i zepsulo timing krokow. Host czyta odpowiedzi tylko okazjonalnie,
//   wiec nie mozemy polegac na tym, ze ktos je odbiera.
//
//   Wyjatki (PONG/READY/STATUS/ERR) sa krotkie i wystepuja rzadko.
//   Stale ACK_PLAY_STOP = true wlacza "OK" takze dla PLAY/STOP.
//
// Caly timing muzyczny (kiedy PLAY, kiedy STOP) nalezy do hosta.
//
// WATCHDOG: jesli host zamilknie na HOST_TIMEOUT_MS (np. zawiesil sie,
// wyjeto USB), firmware sam zatrzymuje kroki. Host podtrzymuje lacze
// wysylajac PING przy dlugich nutach i przerwach.
// ============================================================

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

// ============================================================
// PINOUT (nie zmieniac bez potrzeby - dziala na tym sprzecie)
// ============================================================

constexpr uint8_t PIN_DIR     = 2;  // FDD pin 18 DIR
constexpr uint8_t PIN_STEP    = 3;  // FDD pin 20 /STEP
constexpr uint8_t PIN_TRACK0  = 4;  // FDD pin 26 /TRACK0
constexpr uint8_t PIN_SELECT  = 5;  // FDD Drive Select

// Ustalone eksperymentalnie dla tej stacji:
constexpr uint8_t DIR_TOWARD_TRACK0 = HIGH;  // DIR HIGH = w strone TRACK0
constexpr uint8_t DIR_AWAY_TRACK0   = LOW;   // DIR LOW  = od TRACK0
constexpr uint8_t SELECT_ACTIVE     = LOW;   // Drive Select aktywny LOW

// ============================================================
// MECHANIKA
// ============================================================

constexpr int MIN_TRACK = 4;    // bezpieczny zakres programowego licznika
constexpr int MAX_TRACK = 72;   // (0 == TRACK0, licznik idzie w gore)

constexpr int START_TRACK       = 10;  // ile sciezek odjechac po homingu
constexpr int HOMING_MAX_STEPS  = 90;  // 80 sciezek + zapas

constexpr uint16_t HOMING_STEP_MS = 5;  // tempo dojazdu do TRACK0
constexpr uint16_t START_STEP_MS  = 5;  // tempo odjazdu od TRACK0

constexpr uint16_t STEP_PULSE_US = 30;  // szerokosc impulsu /STEP
constexpr uint16_t DIR_SETUP_US  = 30;  // setup czasu DIR przed krokiem

// Twardy limit predkosci krokow (1 ms = 1000 krokow/s). Normalna praca to
// 130-330 Hz, wiec limit nigdy nie przeszkadza - chroni tylko mechanike,
// gdyby host (albo blad w protokole) probowal krecic headem szybciej.
constexpr uint32_t MIN_STEP_INTERVAL_US = 1000;

// Watchdog: brak jakiejkolwiek komendy przez tyle ms zatrzymuje kroki.
// Host wysyla PING co KEEPALIVE (1 s), wiec to nie grozi dlugim nutom.
constexpr unsigned long HOST_TIMEOUT_MS = 3000;

// Ile kolejnych aktywnych odczytow /TRACK0 uznajemy za pewna utrate
// pozycji (filtr na pojedynczy glitch na linii czujnika).
constexpr uint8_t POSITION_LOSS_SAMPLES = 3;

// Zabezpieczenie przed utrata pozycji.
// TRACK0 to jedyny prawdziwy czujnik. Jesli podczas grania czujnik jest
// aktywny, a programowy licznik mowi, ze jestesmy znacznie dalej niz
// MIN_TRACK, to znaczy ze head zgubil kroki -> trzeba zrobic homing.
// Margines chroni przed falszywym alarmem, gdy czujnik ma szersza strefe
// niz jedna sciezka. Jesli Twoja stacja ma wyraznie szeroka strefe
// TRACK0, zwieksz POSITION_LOSS_MARGIN.
constexpr bool DETECT_POSITION_LOSS = true;
constexpr int  POSITION_LOSS_MARGIN = 6;

// ============================================================
// ZAKRES CZESTOTLIWOSCI PRZYJMOWANY OD HOSTA
//
// Host domyslnie sklada nuty do 130..330 Hz (COMFORT). Ten zakres jest
// tylko bezpiecznikiem mechanicznym - chodzi o to, zeby zadna literowka
// w protokole nie probowala krecic headem z absurdalna predkoscia.
// ============================================================

constexpr float MIN_PLAY_HZ = 40.0f;
constexpr float MAX_PLAY_HZ = 500.0f;

// ============================================================
// SERIAL
// ============================================================

constexpr unsigned long SERIAL_BAUD = 115200;
constexpr uint8_t CMD_BUF_SIZE = 40;

// Ustaw na true, jesli host ma czytac odpowiedzi OK dla PLAY/STOP.
// Domyslnie false - patrz komentarz na gorze pliku.
constexpr bool ACK_PLAY_STOP = false;

// ============================================================
// STACJA DYSKIETOWEK
//
// Cala logika jednej stacji jest zamknieta w tej klasie, zeby pozniej
// moc trzymac je w tablicy (wiele instrumentow) bez przepisywania
// homingu ani generatora krokow.
// ============================================================

class FloppyDrive
{
public:
    FloppyDrive(uint8_t dirPin,
                uint8_t stepPin,
                uint8_t track0Pin,
                uint8_t selectPin)
        : dirPin_(dirPin),
          stepPin_(stepPin),
          track0Pin_(track0Pin),
          selectPin_(selectPin)
    {
    }

    // --- inicjalizacja pinow (bez ruchu) ---
    void begin()
    {
        pinMode(dirPin_, OUTPUT);
        pinMode(stepPin_, OUTPUT);
        pinMode(track0Pin_, INPUT_PULLUP);
        pinMode(selectPin_, OUTPUT);

        digitalWrite(stepPin_, HIGH);            // /STEP nieaktywny
        digitalWrite(dirPin_, DIR_TOWARD_TRACK0);
        digitalWrite(selectPin_, SELECT_ACTIVE); // stacja wybrana

        track_ = 0;
        positionKnown_ = false;
        directionAway_ = false;
        playing_ = false;
        motion_ = Motion::Idle;
    }

    // --- wolane w kazdym obiegu loop(), nigdy nie blokuje ---
    void update()
    {
        updateMotion();

        if (motion_ == Motion::Idle)
            updatePlayback();
    }

    // --- homing + odjazd na pozycje startowa (nieblokujaco) ---
    void requestHome()
    {
        stopNote();

        positionKnown_ = false;
        directionAway_ = false;
        applyDirection();

        motionStepsLeft_ = HOMING_MAX_STEPS;
        motionNextMs_ = millis();
        motion_ = Motion::Homing;

        Serial.println(F("HOMING"));
    }

    // --- start/zmiana nuty; false = odmowa (host dostaje ERR) ---
    bool startNote(float hz)
    {
        if (!positionKnown_)
            return false;

        if (hz < MIN_PLAY_HZ || hz > MAX_PLAY_HZ)
            return false;

        if (motion_ != Motion::Idle)
            return false;

        stepIntervalUs_ = static_cast<uint32_t>(1000000.0f / hz + 0.5f);

        if (stepIntervalUs_ < MIN_STEP_INTERVAL_US)
            stepIntervalUs_ = MIN_STEP_INTERVAL_US;

        // Zmiana wysokosci w trakcie grania nie resetuje fazy krokow -
        // dzieki temu legato nie ma klikniecia. STOP + PLAY daje
        // natomiast swiezy start (uzywane przy powtorkach tej samej nuty).
        if (!playing_)
        {
            playing_ = true;
            nextStepUs_ = micros();
        }
        else
        {
            // Legato w gore: nowy okres jest krotszy od starego, wiec nie
            // czekamy z pierwszym klikiem pelnego starego okresu.
            const uint32_t now = micros();

            if (static_cast<long>(nextStepUs_ - now) >
                static_cast<long>(stepIntervalUs_))
            {
                nextStepUs_ = now + stepIntervalUs_;
            }
        }

        return true;
    }

    // Host zyje - wolane przy kazdej odebranej komendzie (watchdog).
    void noteHostActivity()
    {
        lastCommandMs_ = millis();
    }

    void stopNote()
    {
        playing_ = false;
    }

    bool positionKnown() const { return positionKnown_; }
    bool playing()       const { return playing_; }
    int  track()         const { return track_; }
    bool directionAway() const { return directionAway_; }

    // true, gdy trwa homing albo odjazd na pozycje startowa
    bool busy() const { return motion_ != Motion::Idle; }

    // surowy stan czujnika /TRACK0 (do diagnostyki sprzetu)
    bool track0Active() const
    {
        return digitalRead(track0Pin_) == LOW;  // /TRACK0 aktywne LOW
    }

    float currentHz() const
    {
        if (!playing_ || stepIntervalUs_ == 0)
            return 0.0f;

        return 1000000.0f / static_cast<float>(stepIntervalUs_);
    }

private:
    enum class Motion : uint8_t { Idle, Homing, SeekingStart };

    // ---------- niskopoziomowe ----------

    void stepPulse()
    {
        digitalWrite(stepPin_, LOW);   // /STEP aktywny
        delayMicroseconds(STEP_PULSE_US);
        digitalWrite(stepPin_, HIGH);  // /STEP nieaktywny
    }

    bool isTrackZero() const
    {
        return track0Active();
    }

    void applyDirection()
    {
        digitalWrite(dirPin_,
                     directionAway_ ? DIR_AWAY_TRACK0 : DIR_TOWARD_TRACK0);
        delayMicroseconds(DIR_SETUP_US);
    }

    // ---------- maszyna stanow ruchu ----------

    void updateMotion()
    {
        if (motion_ == Motion::Idle)
            return;

        const unsigned long now = millis();

        if (static_cast<long>(now - motionNextMs_) < 0)
            return;

        if (motion_ == Motion::Homing)
        {
            // Sprawdzamy czujnik PRZED krokiem, tak jak w dzialajacym
            // prototypie - jesli head juz stoi na TRACK0, nie ruszamy nim.
            if (isTrackZero())
            {
                track_ = 0;
                positionKnown_ = true;
                directionAway_ = true;
                applyDirection();

                motionStepsLeft_ = START_TRACK;
                motionNextMs_ = now + START_STEP_MS;
                motion_ = Motion::SeekingStart;
                return;
            }

            if (motionStepsLeft_ <= 0)
            {
                motion_ = Motion::Idle;
                positionKnown_ = false;
                Serial.println(F("ERR HOME_FAILED"));
                return;
            }

            stepPulse();
            motionStepsLeft_--;
            motionNextMs_ = now + HOMING_STEP_MS;
            return;
        }

        // Motion::SeekingStart - odjazd od TRACK0 na pozycje startowa
        if (motionStepsLeft_ <= 0)
        {
            motion_ = Motion::Idle;
            Serial.println(F("READY"));
            return;
        }

        stepPulse();
        track_++;
        motionStepsLeft_--;
        motionNextMs_ = now + START_STEP_MS;
    }

    // ---------- generator krokow grania ----------

    void updatePlayback()
    {
        if (!playing_)
            return;

        // Watchdog: host przestal sie odzywac (awaria / wyjety USB).
        if (millis() - lastCommandMs_ > HOST_TIMEOUT_MS)
        {
            playing_ = false;
            Serial.println(F("ERR HOST_TIMEOUT"));
            return;
        }

        const unsigned long now = micros();

        if (static_cast<long>(now - nextStepUs_) < 0)
            return;

        // Twardy limit predkosci - nigdy nie stepujemy szybciej niz
        // MIN_STEP_INTERVAL_US, nawet gdyby komendy przyszly lawina.
        if (static_cast<long>(now - lastStepUs_) <
            static_cast<long>(MIN_STEP_INTERVAL_US))
        {
            return;
        }

        musicalStep();
        lastStepUs_ = now;

        nextStepUs_ += stepIntervalUs_;

        // Jesli z jakiegos powodu jestesmy spoznieni, nie nadrabiamy
        // serii krokow (mechanika by tego nie lubila) - po prostu
        // przesuwamy harmonogram.
        if (static_cast<long>(now - nextStepUs_) > 0)
            nextStepUs_ = now + stepIntervalUs_;

        checkPosition();
    }

    // Jeden krok = jeden "klik" slyszalnego dzwieku.
    // Zmiana kierunku NIE zmienia czestotliwosci krokow - decyduje o niej
    // wylacznie stepIntervalUs_, wiec zawracanie nie zmienia wysokosci nuty.
    void musicalStep()
    {
        if (directionAway_ && track_ >= MAX_TRACK)
        {
            directionAway_ = false;
            applyDirection();
        }
        else if (!directionAway_ && track_ <= MIN_TRACK)
        {
            directionAway_ = true;
            applyDirection();
        }

        stepPulse();

        track_ += directionAway_ ? 1 : -1;
    }

    void checkPosition()
    {
        if (!DETECT_POSITION_LOSS)
            return;

        // Czujnik czytamy przy kazdym kroku. Pojedynczy glitch nie moze
        // przerywac utworu, wiec wymagamy kilku aktywnych odczytow z rzedu
        // (kolejne kroki, wiec realnie kilka ms).
        if (track_ > (MIN_TRACK + POSITION_LOSS_MARGIN) && isTrackZero())
        {
            positionLossSamples_++;

            if (positionLossSamples_ >= POSITION_LOSS_SAMPLES)
            {
                playing_ = false;
                positionKnown_ = false;
                motion_ = Motion::Idle;
                Serial.println(F("ERR POS_LOST"));
            }

            return;
        }

        positionLossSamples_ = 0;
    }

    // ---------- stan ----------

    const uint8_t dirPin_;
    const uint8_t stepPin_;
    const uint8_t track0Pin_;
    const uint8_t selectPin_;

    Motion motion_ = Motion::Idle;

    int  track_ = 0;
    bool positionKnown_ = false;
    bool directionAway_ = true;

    bool playing_ = false;

    uint32_t stepIntervalUs_ = 1000;
    uint32_t nextStepUs_ = 0;
    uint32_t lastStepUs_ = 0;

    uint8_t positionLossSamples_ = 0;
    unsigned long lastCommandMs_ = 0;

    int motionStepsLeft_ = 0;
    unsigned long motionNextMs_ = 0;
};

// ============================================================
// INSTANCJE
//
// MVP: jedna stacja. Rozszerzenie na wiele instrumentow =
// tablica FloppyDrive[] + wybor stacji w handlerze komend.
// ============================================================

FloppyDrive drive(PIN_DIR, PIN_STEP, PIN_TRACK0, PIN_SELECT);

// ============================================================
// PARSOWANIE KOMEND
// ============================================================

char cmdBuf[CMD_BUF_SIZE];
uint8_t cmdLen = 0;
bool discarding = false;   // odrzucamy reszte za dlugiej linii

void printStatus()
{
    Serial.print(F("STATUS track="));
    Serial.print(drive.track());

    Serial.print(F(" dir="));
    Serial.print(drive.directionAway() ? F("away") : F("toward"));

    Serial.print(F(" homed="));
    Serial.print(drive.positionKnown() ? 1 : 0);

    Serial.print(F(" playing="));
    Serial.print(drive.playing() ? 1 : 0);

    Serial.print(F(" track0="));
    Serial.print(drive.track0Active() ? 1 : 0);

    Serial.print(F(" hz="));
    Serial.println(drive.currentHz(), 2);
}

void handleCommand(char *line)
{
    const char *cmd = strtok(line, " \t");

    if (cmd == nullptr)
        return;

    if (strcasecmp(cmd, "PING") == 0)
    {
        Serial.println(F("PONG"));
        return;
    }

    if (strcasecmp(cmd, "STOP") == 0)
    {
        drive.stopNote();

        if (ACK_PLAY_STOP)
            Serial.println(F("OK"));

        return;
    }

    if (strcasecmp(cmd, "PLAY") == 0)
    {
        const char *arg = strtok(nullptr, " \t");

        if (arg == nullptr)
        {
            Serial.println(F("ERR MISSING_FREQ"));
            return;
        }

        const float hz = atof(arg);

        if (!(hz > 0.0f))          // !(x>0) lapie tez NaN
        {
            Serial.println(F("ERR BAD_FREQ"));
            return;
        }

        if (!drive.positionKnown())
        {
            Serial.println(F("ERR NOT_HOMED"));
            return;
        }

        if (drive.busy())
        {
            Serial.println(F("ERR BUSY"));
            return;
        }

        if (!drive.startNote(hz))
        {
            Serial.println(F("ERR FREQ_RANGE"));
            return;
        }

        if (ACK_PLAY_STOP)
            Serial.println(F("OK"));

        return;
    }

    if (strcasecmp(cmd, "HOME") == 0)
    {
        Serial.println(F("OK"));
        drive.requestHome();
        return;
    }

    if (strcasecmp(cmd, "STATUS") == 0)
    {
        printStatus();
        return;
    }

    Serial.println(F("ERR UNKNOWN_CMD"));
}

void pollSerial()
{
    while (Serial.available() > 0)
    {
        const int c = Serial.read();

        if (c < 0)
            return;

        if (c == '\r')
            continue;

        if (c == '\n')
        {
            if (discarding)
            {
                discarding = false;   // reszta za dlugiej linii jest odrzucona
            }
            else if (cmdLen > 0)
            {
                cmdBuf[cmdLen] = '\0';

                // Kazda (nawet bledna) komenda = host zyje (watchdog).
                drive.noteHostActivity();
                handleCommand(cmdBuf);
            }

            cmdLen = 0;
            continue;
        }

        if (discarding)
            continue;

        if (cmdLen >= (CMD_BUF_SIZE - 1))
        {
            // Za dluga linia: odrzucamy ja do konca, zeby jej ogon nie
            // zostal zinterpretowany jako nowa komenda.
            cmdLen = 0;
            discarding = true;
            Serial.println(F("ERR LINE_TOO_LONG"));
            continue;
        }

        cmdBuf[cmdLen++] = static_cast<char>(c);
    }
}

// ============================================================
// SETUP / LOOP
// ============================================================

void setup()
{
    Serial.begin(SERIAL_BAUD);

    drive.begin();

    // Czas na ustabilizowanie sie zasilania / enumeracje USB.
    delay(500);

    Serial.println(F("electromechanical-midi floppy controller v1"));
    Serial.println(F("COMFORT 130-330 Hz | komendy: PLAY <hz>, STOP, HOME, PING, STATUS"));

    drive.requestHome();
}

void loop()
{
    pollSerial();
    drive.update();
}
