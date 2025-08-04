/*
 * flow_sensor_1L.ino  –  Streams pulse counter over Serial and supports reset
 * Wire:
 *   Yellow  → D2  (signal)        (use INPUT_PULLUP)
 *   Red     → 5 V
 *   Black   → GND
 */

const byte  FLOW_PIN       = D2;         // flow sensor signal
const byte  VALVE_SIG_PIN  = D8;         // relay signal pin
const byte  PRESS_SENSE_PIN= A0;         // analog pressure feedback
const byte  LED_PIN        = LED_BUILTIN; // on-board LED for feedback
const unsigned long BAUD  = 115200;
// Data frame interval. 150 ms keeps the host responsive while still
// smoothing a little on the ESP8266 side.
const unsigned long INTERVAL_MS = 150;  // how often to send a CSV frame

const float    PFS     = 0.9f;           // ITV-313L full-scale (MPa)
const uint8_t  PWM_PIN = D5;             // GP8101S control (0-10 V)
const uint16_t PWM_MAX = 1023;
volatile int   setpoint_mbar = 0;

volatile unsigned long pulseCount = 0;
volatile unsigned long lastPulseUs = 0;      // for debouncing
const unsigned long MIN_PULSE_US = 1000;     // ignore pulses <1 ms apart

// ── HX711 scale support ─────────────────────────────────────────────
#include <HX711.h>
#include <math.h>
constexpr byte HX_PIN_DOUT = D6;  // DT on NodeMCU v2
constexpr byte HX_PIN_SCK  = D7;  // SCK on NodeMCU v2
HX711 scale;
constexpr float COUNTS_PER_GRAM = -1115.637f;  // adjust after calibration
constexpr byte  TARE_READS = 20;
constexpr byte  HX_AVG = 8;                    // averaging reads
long hxOffset = 0;
bool hxReady = false;

float readPressureMPa(){
  int adc = analogRead(PRESS_SENSE_PIN);
  float vCore = adc / 1023.0f;       // 0–1 V
  float vMon = vCore * 5.4f;
  float pMPa = (vMon - 1.0f) / 4.0f * 0.9f;
  if (pMPa < 0) pMPa = 0;
  return pMPa;
}

void setup() {
  // claim PWM pin before any serial output so it stays quiet
  pinMode(PWM_PIN, OUTPUT);
  digitalWrite(PWM_PIN, LOW);

  Serial.begin(BAUD);
  Serial.setDebugOutput(false);

  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), countPulse, RISING);

  pinMode(VALVE_SIG_PIN, OUTPUT);
  digitalWrite(VALVE_SIG_PIN, LOW);   // valve normally closed
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  analogWriteFreq(20000);             // 20 kHz PWM
  analogWriteRange(PWM_MAX);          // use full 10-bit range
  analogWrite(PWM_PIN, 0);            // start with 0 V

  // ── initialise HX711 scale -------------------------------------------
  scale.begin(HX_PIN_DOUT, HX_PIN_SCK);
  unsigned long t0 = millis();
  while (!scale.is_ready() && millis() - t0 < 3000) {
    // wait for the amplifier to settle (up to 3 s)
  }
  hxReady = scale.is_ready();
  if (hxReady) {
    long acc = 0;
    for (byte i = 0; i < TARE_READS; ++i) {
      while (!scale.is_ready()) {}
      acc += scale.read();
    }
    hxOffset = acc / TARE_READS;
  } else {
    Serial.println(F("hx711-not-ready"));
  }

  Serial.println(F("ready"));           // banner for host script
}

void loop() {
  static float pCmd = 0;                              // filtered set-point (MPa)
  float pTarget = 0.001f * setpoint_mbar;             // mbar → MPa
  pCmd += 0.05f * (pTarget - pCmd);                   // τ ≈100 ms in a 1 kHz loop
  uint16_t duty = (uint16_t)round(pCmd / 0.9f * PWM_MAX);
  analogWrite(D5, duty);

  /* -------- handle incoming commands -------- */
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'r') {                     // reset counter only
      noInterrupts();
      pulseCount = 0;
      lastPulseUs = micros();
      interrupts();

      Serial.println(F("reset-ack"));   // confirmation
      digitalWrite(LED_PIN, HIGH);      // short blink
      delay(50);
      digitalWrite(LED_PIN, LOW);
      // send an immediate zero frame so the host updates right away
      Serial.print(millis());
      Serial.print(',');
      Serial.print(pulseCount);
      float g = NAN;
      if (hxReady) {
        long acc = 0;
        for (byte i = 0; i < HX_AVG; ++i) acc += scale.read();
        long raw = acc / HX_AVG;
        g = (raw - hxOffset) / COUNTS_PER_GRAM;
        Serial.print(',');
        Serial.print(g, 1);
      }
      float mp = readPressureMPa();
      Serial.print(',');
      Serial.print(mp, 3);
      Serial.print(',');
      Serial.print(pCmd, 3);
      Serial.println();
    } else if (c == 't') {              // tare HX711
      if (hxReady) {
        long acc = 0;
        for (byte i = 0; i < TARE_READS; ++i) {
          while (!scale.is_ready()) {}
          acc += scale.read();
        }
        hxOffset = acc / TARE_READS;
      }

      Serial.println(F("tare-ack"));    // confirmation
      digitalWrite(LED_PIN, HIGH);      // short blink
      delay(50);
      digitalWrite(LED_PIN, LOW);
      Serial.print(millis());
      Serial.print(',');
      Serial.print(pulseCount);
      float g = NAN;
      if (hxReady) {
        long acc = 0;
        for (byte i = 0; i < HX_AVG; ++i) acc += scale.read();
        long raw = acc / HX_AVG;
        g = (raw - hxOffset) / COUNTS_PER_GRAM;
        Serial.print(',');
        Serial.print(g, 1);
      }
      float mp = readPressureMPa();
      Serial.print(',');
      Serial.print(mp, 3);
      Serial.print(',');
      Serial.print(pCmd, 3);
      Serial.println();
    } else if (c == 'o') {              // open valve
      digitalWrite(VALVE_SIG_PIN, HIGH);

      Serial.println(F("valve-open"));
    } else if (c == 'c') {              // close valve
      digitalWrite(VALVE_SIG_PIN, LOW);
      Serial.println(F("valve-closed"));
    } else if (c == 'p') {              // set pressure in kPa (0-900)
      int kpa = Serial.parseInt();
      if (kpa < 0) kpa = 0;
      if (kpa > 900) kpa = 900;
      float pMPa = kpa / 1000.0f;
      uint16_t duty = (uint16_t)round(pMPa / 0.9f * PWM_MAX);
      analogWrite(D5, duty);
      Serial.print(F("pressure-set,"));
      Serial.println(kpa);
    } else if (c == 's') {              // 's 473' means 0.473 MPa
      setpoint_mbar = Serial.parseInt();
    }
  }

  /* -------- periodic data frame -------- */
  static unsigned long lastPrint = 0;
  const unsigned long now = millis();

  if (now - lastPrint >= INTERVAL_MS) {
    noInterrupts();
    unsigned long count = pulseCount;
    interrupts();

    float g = NAN;
    if (hxReady) {
      long acc = 0;
      for (byte i = 0; i < HX_AVG; ++i) acc += scale.read();
      long raw = acc / HX_AVG;
      g = (raw - hxOffset) / COUNTS_PER_GRAM;
    }

    float mp = readPressureMPa();

    Serial.print(now);
    Serial.print(',');
    Serial.print(count);
    if (!isnan(g)) {
      Serial.print(',');
      Serial.print(g, 1);
    }
    Serial.print(',');
    Serial.print(mp, 3);
    Serial.print(',');
    Serial.print(pCmd, 3);
    Serial.println();

    lastPrint = now;
  }
}

IRAM_ATTR void countPulse() {
  unsigned long now = micros();
  if (now - lastPulseUs >= MIN_PULSE_US) {
    pulseCount++;
    lastPulseUs = now;
  }
}
