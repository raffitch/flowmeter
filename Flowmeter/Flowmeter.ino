/*
 * flow_sensor_1L.ino  –  Streams pulse counter over Serial and supports reset
 * Wire:
 *   Yellow  → D2  (signal)        (use INPUT_PULLUP)
 *   Red     → 5 V
 *   Black   → GND
 */

#ifdef ESP8266
const byte  FLOW_PIN      = D2;         // flow sensor signal
const byte  VALVE_SIG_PIN = D4;         // relay signal
#else
const byte  FLOW_PIN      = 2;          // interrupt pin
const byte  VALVE_SIG_PIN = 8;          // relay signal pin
#endif
#ifdef ESP8266
#  define LED_PIN LED_BUILTIN           // NodeMCU built‑in LED
#else
const byte  LED_PIN       = LED_BUILTIN; // signal reset acknowledgement
#endif
const unsigned long BAUD  = 115200;
// Data frame interval. 200 ms gives a good balance between latency and
// smoothing on the host side.
const unsigned long INTERVAL_MS = 200;  // how often to send a CSV frame

volatile unsigned long pulseCount = 0;
volatile unsigned long lastPulseUs = 0;      // for debouncing
const unsigned long MIN_PULSE_US = 1000;     // ignore pulses <1 ms apart

// ── HX711 scale support ─────────────────────────────────────────────
#include <HX711.h>
#ifdef ESP8266
constexpr byte HX_PIN_DOUT = D6;  // DT on NodeMCU v2
constexpr byte HX_PIN_SCK  = D7;  // SCK on NodeMCU v2
#else
constexpr byte HX_PIN_DOUT = 2;
constexpr byte HX_PIN_SCK  = 3;
#endif
HX711 scale;
constexpr float COUNTS_PER_GRAM = -1662.567f;  // adjust after calibration
constexpr byte  TARE_READS = 20;
constexpr byte  HX_AVG = 8;                    // averaging reads
long hxOffset = 0;
bool hxReady = false;

void setup() {
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), countPulse, RISING);

  pinMode(VALVE_SIG_PIN, OUTPUT);
  digitalWrite(VALVE_SIG_PIN, LOW);   // valve normally closed
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

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

  Serial.begin(BAUD);
  Serial.println(F("ready"));           // banner for host script
}

void loop() {
  /* -------- handle incoming commands -------- */
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'r') {                     // reset counter
      noInterrupts();
      pulseCount = 0;
      interrupts();
      Serial.println(F("reset-ack"));   // confirmation
      digitalWrite(LED_PIN, HIGH);      // short blink
      delay(50);
      digitalWrite(LED_PIN, LOW);
      // send an immediate zero frame so the host updates right away
      Serial.print(millis());
      Serial.print(',');
      Serial.print(pulseCount);
      if (hxReady && scale.is_ready()) {
        long acc = 0;
        for (byte i = 0; i < HX_AVG; ++i) acc += scale.read();
        long raw = acc / HX_AVG;
        float g = (raw - hxOffset) / COUNTS_PER_GRAM;
        Serial.print(',');
        Serial.print(g, 1);
      }
      Serial.println();
    } else if (c == 'o') {              // open valve
      digitalWrite(VALVE_SIG_PIN, HIGH);

      Serial.println(F("valve-open"));
    } else if (c == 'c') {              // close valve
      digitalWrite(VALVE_SIG_PIN, LOW);
      Serial.println(F("valve-closed"));
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
    if (hxReady && scale.is_ready()) {
      long acc = 0;
      for (byte i = 0; i < HX_AVG; ++i) acc += scale.read();
      long raw = acc / HX_AVG;
      g = (raw - hxOffset) / COUNTS_PER_GRAM;
    }

    Serial.print(now);
    Serial.print(',');
    Serial.print(count);
    if (!isnan(g)) {
      Serial.print(',');
      Serial.print(g, 1);
    }
    Serial.println();

    lastPrint = now;
  }
}

#ifdef ESP8266
IRAM_ATTR
#endif
void countPulse() {
  unsigned long now = micros();
  if (now - lastPulseUs >= MIN_PULSE_US) {
    pulseCount++;
    lastPulseUs = now;
  }
}
