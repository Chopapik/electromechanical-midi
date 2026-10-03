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
//   HOME BLIND      -> jak HOME, ale BEZ czujnika TRACK0: jedzie pelna
//                      szerokosc stacji do oporu i odjezdza START_TRACK.
//                      Awaryjne, gdy czujnik TRACK0 nie odpowiada (uszkodzona
//                      tasma/czujnik) - inaczej ERR HOME_FAILED na zawsze.
//   HIT             -> (brak odpowiedzi) jedno uderzenie perkusyjne HDD
//                      (VCM). Sekwencja park->settle->strike ~105 ms; kolejne
//                      HIT w trakcie trwania sa kolejkowane (jedno).
//   DRUM <0-255>    -> (brak odpowiedzi) amplituda bebna VHS; 0 = stop
//   DRUMF <hz>      -> (brak odpowiedzi) czestotliwosc kluczowania bebna;
//                      0 = tryb DC (zwykly PWM 976 Hz). 20..2000 Hz.
//   STATUS          -> STATUS track=<n> dir=<...> homed=<0|1> playing=<0|1>
//                             track0=<0|1> hz=<...>
//                             drum=<0-255> drum_out=<0-255> drumf=<0-2000>
//                             hdd=<0|1>
//   cokolwiek innego-> ERR UNKNOWN_CMD
//
// Bledy: ERR NOT_HOMED / ERR BUSY / ERR FREQ_RANGE / ERR MISSING_FREQ
//        ERR BAD_FREQ / ERR HOME_FAILED / ERR POS_LOST / ERR HOST_TIMEOUT
//        ERR MISSING_PWM / ERR BAD_PWM / ERR PWM_RANGE
//        ERR MISSING_DRUMF / ERR BAD_DRUMF / ERR DRUMF_RANGE
//        ERR LINE_TOO_LONG / ERR UNKNOWN_CMD
//
// VHS DRUM: to NIE jest zwiazane z MIDI ani z FDD - to zwykle manualne
// sterowanie PWM jednym sprawnym silnikiem bebna VHS (patrz sekcja nizej).
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
constexpr uint8_t PIN_DRUM    = 6;  // VHS drum: D6 --[100 kOhm]--> CN5 (ICTL)
constexpr uint8_t PIN_HDD_PNP_L = 7;  // HDD VCM mostek H: PNP lewy
constexpr uint8_t PIN_HDD_PNP_R = 8;  // HDD VCM mostek H: PNP prawy
constexpr uint8_t PIN_HDD_NPN_L = 9;  // HDD VCM mostek H: NPN lewy
constexpr uint8_t PIN_HDD_NPN_R = 10; // HDD VCM mostek H: NPN prawy

// Sekwencja uderzenia HDD (ustalona empirycznie w testach strojenia):
//   PARK 40 ms (D7 LOW + D10 HIGH) - odwozi ramie do parku,
//   SETTLE 40 ms                   - ramie osiada w parku,
//   STRIKE 25 ms (D8 LOW + D9 HIGH)- UDERZENIE.
constexpr uint16_t HDD_PARK_MS   = 40;
constexpr uint16_t HDD_SETTLE_MS = 40;
constexpr uint16_t HDD_STRIKE_MS = 25;

// Ustalone eksperymentalnie dla tej stacji:
constexpr uint8_t DIR_TOWARD_TRACK0 = HIGH;  // DIR HIGH = w strone TRACK0
constexpr uint8_t DIR_AWAY_TRACK0   = LOW;   // DIR LOW  = od TRACK0
constexpr uint8_t SELECT_ACTIVE     = LOW;   // Drive Select aktywny LOW

// ============================================================
// VHS DRUM MOTOR (mamy JEDEN sprawny egzemplarz - obchodzic sie ostroznie)
//
// Tor:  D6 --[100 kOhm]--> CN5 (ICTL)
//       CN6 = +12 V (przez bezpiecznik ~1 A, bez zmian)
//       CN3 = GND (wspolna masa z Arduino - bez tego sterowanie nie ma
//                  odniesienia)
//
// DLACZEGO D6 JEST BEZPIECZNE DLA SCHEDULERA KROKOW:
//   D6 to PD6 = OC0A, czyli kanal A Timer0. Timer0 napedza millis()/micros()
//   (prescaler 64, Fast PWM 8-bit, przerwanie TOIE0), a scheduler STEP liczy
//   wlasnie na micros(). Dlatego NIE WOLNO:
//     * zmieniac preskalera Timer0 ani bitow WGM - to zepsuloby millis()/micros()
//       i caly timing krokow,
//     * wolac analogWrite(5, ...) - D5 to PD5 = OC0B = FDD Drive Select.
//   analogWrite(PIN_DRUM, x) zmienia tylko COM0A1 i OCR0A. W TIMSK0 wlaczone
//   jest wylacznie TOIE0 (bez OCIE0A), wiec OCR0A jest wolnym rejestrem
//   porownania: zapis nie generuje przerwania i nie rusza licznika milisekund.
//   PWM na D6: 16 MHz / (64 * 256) = 976,5625 Hz, 8 bitow.
//
// DLACZEGO TO JEST BEZPIECZNE DLA SILNIKA:
//   Sprawdzony recznie warunek to "+5 V -> 100 kOhm -> CN5" i silnik ruszyl.
//   Wypelnienie 255 odtwarza DOKLADNIE ten warunek, wiec ten tor nie jest
//   w stanie podac na CN5 wiecej, niz to, co juz zadzialalo. Prad jest
//   ograniczony przez 100 kOhm do ~50 uA.
// ============================================================

// Limit programowy PWM bebna.
//
// 255 = 100% wypelnienia = D6 podane na stale +5 V, czyli DOKLADNIE ten
// warunek, ktory zostal sprawdzony recznie ("+5 V -> 100 kOhm -> CN5" i
// beben sie kreci). Powyzej 255 nic nie istnieje, wiec ten tor nie moze
// podac na CN5 wiecej, niz to, co juz zadzialalo.
constexpr uint8_t DRUM_MAX_PWM = 255;

// --- Tryb tonu (kluczowanie na audio) -------------------------------
//
// Pomiar wykazal: wypelnienie zmienia GLOSNOSC, a nie wysokosc. Silnik ma
// regulowane obroty, wiec wysokosc musi pochodzic z samego kluczowania.
// W trybie tonu D6 nie jest juz napedzany przez Timer0, tylko przez
// przerwanie Timer1 (CTC), ktore samo przelacza pin:
//
//   * Timer1 jest w tym firmware calkowicie wolny (Timer0 = millis/micros,
//     Timer2 nieuzywany), wiec NIC nie psuje timingu krokow FDD,
//   * przed wejsciem w tryb tonu czyscimy COM0A1, zeby odlaczyc OC0A od
//     pinu - inaczej Timer0 i nasz ISR walczylyby o D6,
//   * tick Timer1 = 0,5 us (prescaler 8), wiec rozdzielczosc okresu jest
//     bardzo dobra w calym zakresie 20..2000 Hz.
constexpr uint32_t DRUM_TICK_HZ = F_CPU / 8UL;   // 2 000 000
constexpr uint16_t DRUM_TONE_MIN_HZ = 20;
constexpr uint16_t DRUM_TONE_MAX_HZ = 2000;

// ============================================================
// MECHANIKA
// ============================================================

constexpr int MIN_TRACK = 4;    // bezpieczny zakres programowego licznika
constexpr int MAX_TRACK = 72;   // (0 == TRACK0, licznik idzie w gore)

constexpr int START_TRACK       = 10;  // ile sciezek odjechac po homingu
constexpr int HOMING_MAX_STEPS  = 90;  // 80 sciezek + zapas
// Homing na slepo: wiecej niz cala szerokosc stacji (80 sciezek), zeby
// dojechac do oporu niezaleznie od tego, gdzie glowica byla.
constexpr int BLIND_HOME_STEPS  = 95;

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
    void requestHome(bool blind = false)
    {
        stopNote();

        positionKnown_ = false;
        directionAway_ = false;      // zawsze w strone TRACK0
        applyDirection();

        if (blind)
        {
            motionStepsLeft_ = BLIND_HOME_STEPS;
            motionNextMs_ = millis();
            motion_ = Motion::BlindHoming;

            Serial.println(F("HOMING_BLIND"));
            return;
        }

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
    enum class Motion : uint8_t { Idle, Homing, BlindHoming, SeekingStart };

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

        if (motion_ == Motion::BlindHoming)
        {
            // Bez czujnika: jedziemy cala szerokosc stacji. Glowica dojedzie
            // do opory (TRACK0) niezaleznie od punktu startu, wiec pozycja
            // jest znana "z zalozenia". Opór jest tu normalnym elementem
            // homingu - tak samo konczy sie homing z czujnikiem.
            if (motionStepsLeft_ <= 0)
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
// HDD PERKUSJA (VCM) - nieblokujaca maszyna stanow
//
// Ramię NIE wraca samo po uderzeniu (sprawdzone empirycznie), dlatego
// kazdy hit zaczyna sie od aktywnego odwiezienia do parku. Cykl:
//   PARK 40 ms -> SETTLE 40 ms -> STRIKE 25 ms -> off
// Calkowity cykl ~105 ms => maks ~9,5 uderzenia/s.
// ============================================================

class HddPercussion
{
public:
    void begin()
    {
        // Bezpieczny stan ZANIM piny stana sie OUTPUT (inaczej reset
        // plytki moglby na chwile otworzyc tranzystory mostka).
        digitalWrite(PIN_HDD_PNP_L, HIGH);
        digitalWrite(PIN_HDD_PNP_R, HIGH);
        digitalWrite(PIN_HDD_NPN_L, LOW);
        digitalWrite(PIN_HDD_NPN_R, LOW);

        pinMode(PIN_HDD_PNP_L, OUTPUT);
        pinMode(PIN_HDD_PNP_R, OUTPUT);
        pinMode(PIN_HDD_NPN_L, OUTPUT);
        pinMode(PIN_HDD_NPN_R, OUTPUT);

        allOff();
    }

    // Wola z loop() - przechodzi przez fazy bez blokowania reszty.
    void update()
    {
        if (phase_ == Phase::Idle)
        {
            if (pending_)
            {
                pending_ = false;
                startPark();
            }

            return;
        }

        if (static_cast<long>(millis() - nextMs_) < 0)
            return;

        switch (phase_)
        {
        case Phase::Park:
            allOff();
            phase_ = Phase::Settle;
            nextMs_ = millis() + HDD_SETTLE_MS;
            break;

        case Phase::Settle:
            startStrike();
            break;

        case Phase::Strike:
            allOff();
            phase_ = Phase::Idle;
            break;

        case Phase::Idle:
            break;
        }
    }

    // Zlecenie uderzenia. Jesli sekwencja wlasnie trwa, kolejka (jedno).
    void trigger()
    {
        if (phase_ == Phase::Idle)
            startPark();
        else
            pending_ = true;
    }

    // Przerwanie trwajacej sekwencji (awaryjne; cewka bez pradu).
    void stop()
    {
        pending_ = false;
        phase_ = Phase::Idle;
        allOff();
    }

    bool busy() const
    {
        return phase_ != Phase::Idle;
    }

    void allOff()
    {
        digitalWrite(PIN_HDD_PNP_L, HIGH);
        digitalWrite(PIN_HDD_PNP_R, HIGH);
        digitalWrite(PIN_HDD_NPN_L, LOW);
        digitalWrite(PIN_HDD_NPN_R, LOW);
    }

private:
    enum class Phase : uint8_t { Idle, Park, Settle, Strike };

    void startPark()
    {
        allOff();
        digitalWrite(PIN_HDD_PNP_L, LOW);   // kierunek A: do parku
        digitalWrite(PIN_HDD_NPN_R, HIGH);

        phase_ = Phase::Park;
        nextMs_ = millis() + HDD_PARK_MS;
    }

    void startStrike()
    {
        allOff();
        digitalWrite(PIN_HDD_PNP_R, LOW);   // kierunek B: UDERZENIE
        digitalWrite(PIN_HDD_NPN_L, HIGH);

        phase_ = Phase::Strike;
        nextMs_ = millis() + HDD_STRIKE_MS;
    }

    Phase phase_ = Phase::Idle;
    bool pending_ = false;
    unsigned long nextMs_ = 0;
};

// ============================================================
// INSTANCJE
//
// MVP: jedna stacja. Rozszerzenie na wiele instrumentow =
// tablica FloppyDrive[] + wybor stacji w handlerze komend.
// ============================================================

FloppyDrive drive(PIN_DIR, PIN_STEP, PIN_TRACK0, PIN_SELECT);
HddPercussion hdd;

// ============================================================
// PARSOWANIE KOMEND
// ============================================================

char cmdBuf[CMD_BUF_SIZE];
uint8_t cmdLen = 0;
bool discarding = false;   // odrzucamy reszte za dlugiej linii

// ============================================================
// VHS DRUM - STAN
//
// Trzymamy DWIE wartosci:
//   drumRequested - co przyszlo z hosta (0-255), to widzi UI,
//   drumOutput    - co realnie poszlo na PWM (po limicie DRUM_MAX_PWM).
//
// UWAGA: beben NIE jest objety watchdogiem HOST_TIMEOUT_MS. Tamten watchdog
// zatrzymuje KROKI FDD, gdy host zamilknie - gdyby zatrzymywal tez beben,
// to po 3 s bez komend (a przy recznym sterowaniu tak wlasnie jest) silnik
// stawalby sam. Beben kreci sie do jawnego "DRUM 0", resetu plytki albo
// utraty zasilania.
// ============================================================

uint8_t drumRequested = 0;
uint8_t drumOutput = 0;
uint16_t drumToneHz = 0;        // 0 = tryb DC (Timer0 PWM), >0 = tryb tonu

volatile uint16_t drumPeriodTicks = 0;
volatile uint16_t drumHighTicks = 0;
volatile bool drumPhaseHigh = false;

// Przerwanie od Timer1 przelacza D6: najpierw HIGH na `drumHighTicks`,
// potem LOW na reszte okresu. Dwa przerwania na okres.
ISR(TIMER1_COMPA_vect)
{
    if (drumPhaseHigh)
    {
        PORTD &= static_cast<uint8_t>(~(1 << PD6));
        drumPhaseHigh = false;
        OCR1A = static_cast<uint16_t>(drumPeriodTicks - drumHighTicks - 1);
    }
    else
    {
        PORTD |= static_cast<uint8_t>(1 << PD6);
        drumPhaseHigh = true;
        OCR1A = static_cast<uint16_t>(drumHighTicks - 1);
    }
}

// Przelicza okres/wypelnienie dla aktualnego drumToneHz + drumOutput.
void drumToneRecalc()
{
    uint32_t period = DRUM_TICK_HZ / drumToneHz;

    if (period < 8UL)
        period = 8UL;

    if (period > 60000UL)
        period = 60000UL;

    uint32_t high = (period * drumOutput) / 255UL;

    if (high < 1UL)
        high = 1UL;

    if (high > period - 1UL)
        high = period - 1UL;

    noInterrupts();
    drumPeriodTicks = static_cast<uint16_t>(period);
    drumHighTicks = static_cast<uint16_t>(high);
    interrupts();
}

// Wlacza tryb tonu (D6 napedzany przez Timer1).
void drumToneEnable()
{
    // Odczep OC0A od pinu - inaczej Timer0 nadpisywalby nasz ISR.
    TCCR0A &= static_cast<uint8_t>(~(1 << COM0A1));

    pinMode(PIN_DRUM, OUTPUT);
    digitalWrite(PIN_DRUM, LOW);

    drumToneRecalc();

    noInterrupts();
    TCCR1A = 0;
    TCCR1B = static_cast<uint8_t>((1 << WGM12) | (1 << CS11));  // CTC, /8
    TCNT1 = 0;
    OCR1A = static_cast<uint16_t>(drumHighTicks - 1);
    TIFR1 = static_cast<uint8_t>(1 << OCF1A);
    TIMSK1 = static_cast<uint8_t>(1 << OCIE1A);
    drumPhaseHigh = false;
    interrupts();
}

// Wylacza tryb tonu i wraca do sprzetowego PWM Timer0.
void drumToneDisable()
{
    TIMSK1 = 0;
    TCCR1B = 0;
    drumPhaseHigh = false;

    digitalWrite(PIN_DRUM, LOW);
    analogWrite(PIN_DRUM, drumOutput);   // z powrotem COM0A1 + OCR0A
}

// Ustawia amplitude (0 = stop). Dziala w obu trybach.
uint8_t drumSet(uint8_t requested)
{
    drumRequested = requested;
    drumOutput = (requested > DRUM_MAX_PWM) ? DRUM_MAX_PWM : requested;

    if (drumToneHz == 0)
    {
        analogWrite(PIN_DRUM, drumOutput);
        return drumOutput;
    }

    if (drumOutput == 0)
        drumToneDisable();      // cisza, ale czestotliwosc zostaje w pamieci
    else
        drumToneEnable();

    return drumOutput;
}

// Ustawia czestotliwosc kluczowania (0 = tryb DC).
uint16_t drumSetTone(uint16_t hz)
{
    drumToneHz = hz;

    if (hz == 0)
    {
        drumToneDisable();
        return 0;
    }

    if (drumOutput > 0)
        drumToneEnable();

    return drumToneHz;
}

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
    Serial.print(drive.currentHz(), 2);

    Serial.print(F(" drum="));
    Serial.print(drumRequested);

    Serial.print(F(" drum_out="));
    Serial.print(drumOutput);

    Serial.print(F(" drumf="));
    Serial.print(drumToneHz);

    Serial.print(F(" hdd="));
    Serial.println(hdd.busy() ? 1 : 0);
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
        const char *arg = strtok(nullptr, " \t");

        if (arg != nullptr && strcasecmp(arg, "BLIND") == 0)
        {
            drive.requestHome(true);
            return;
        }

        drive.requestHome();
        return;
    }

    if (strcasecmp(cmd, "DRUM") == 0)
    {
        const char *arg = strtok(nullptr, " \t");

        if (arg == nullptr)
        {
            Serial.println(F("ERR MISSING_PWM"));
            return;
        }

        // "abc" nie moze przypadkiem znaczyc "DRUM 0" - odrzucamy.
        if (arg[0] < '0' || arg[0] > '9')
        {
            Serial.println(F("ERR BAD_PWM"));
            return;
        }

        const long value = atol(arg);

        if (value > 255)
        {
            Serial.println(F("ERR PWM_RANGE"));
            return;
        }

        // Celowo cicho (jak PLAY/STOP): to komenda sterujaca z suwaka,
        // a stan odczytasz przez STATUS. Limit DRUM_MAX_PWM dziala w drumSet().
        drumSet(static_cast<uint8_t>(value));
        return;
    }

    if (strcasecmp(cmd, "DRUMF") == 0)
    {
        const char *arg = strtok(nullptr, " \t");

        if (arg == nullptr)
        {
            Serial.println(F("ERR MISSING_DRUMF"));
            return;
        }

        if (arg[0] < '0' || arg[0] > '9')
        {
            Serial.println(F("ERR BAD_DRUMF"));
            return;
        }

        // Przyjmujemy tez ulamki ("DRUMF 164.81") - host wysyla Hz prosto
        // z MIDI. Firmware i tak pracuje na calkowitych Hz (tick 0,5 us),
        // wiec zaokraglamy.
        const float hz = atof(arg);

        if (!(hz >= 0.0f))          // !(x>=0) lapie tez NaN
        {
            Serial.println(F("ERR BAD_DRUMF"));
            return;
        }

        if (hz > static_cast<float>(DRUM_TONE_MAX_HZ))
        {
            Serial.println(F("ERR DRUMF_RANGE"));
            return;
        }

        const uint16_t rounded = static_cast<uint16_t>(hz + 0.5f);

        // 0 = tryb DC (zwykly PWM 976 Hz). 1..19 tez traktujemy jako DC,
        // bo ponizej 20 Hz to juz nie ton, a kluczowanie mechanicznie
        // szarpaloby silnikiem.
        drumSetTone(rounded < DRUM_TONE_MIN_HZ ? 0 : rounded);
        return;
    }

    if (strcasecmp(cmd, "HIT") == 0)
    {
        // Celowo cicho (jak PLAY/STOP): to komenda zdarzeniowa, stan
        // widac przez STATUS (hdd=1 w trakcie sekwencji). HDD jest
        // niezalezny od FDD - dziala takze, gdy stacja nie zrobila homingu.
        hdd.trigger();
        return;
    }

    if (strcasecmp(cmd, "HDD") == 0)
    {
        // "HDD 0" = awaryjne przerwanie trwajacej sekwencji (cewka bez pradu).
        const char *arg = strtok(nullptr, " \t");

        if (arg != nullptr && strcmp(arg, "0") == 0)
        {
            hdd.stop();
        }

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
    // NAJPIERW uspokajamy beben VHS. Po resecie D6 jest wejsciem (high-Z),
    // wiec zanim cokolwiek innego sie wydarzy, ustawiamy je twardo na 0:
    // najpierw jako zwykly pin, potem jako PWM z OCR0A = 0.
    pinMode(PIN_DRUM, OUTPUT);
    digitalWrite(PIN_DRUM, LOW);
    analogWrite(PIN_DRUM, 0);

    hdd.begin();   // HDD: bezpieczny OFF mostka H (zanim piny beda OUTPUT)

    Serial.begin(SERIAL_BAUD);

    drive.begin();

    // Czas na ustabilizowanie sie zasilania / enumeracje USB.
    delay(500);

    Serial.println(F("electromechanical-midi floppy controller v1"));
    Serial.println(F("COMFORT 130-330 Hz | komendy: PLAY <hz>, STOP, HOME, PING, STATUS, HIT, DRUM <0-255>"));

    drive.requestHome();
}

void loop()
{
    pollSerial();
    drive.update();
    hdd.update();
}
