/*
 * Combined flow sensor + HX711 scale firmware
 * Streams "millis,pulses,grams" over Serial every 500 ms
 *
 * Flow sensor wiring:
 *   Yellow  → D2  (signal)        (use INPUT_PULLUP)
 *   Red     → 5 V
 *   Black   → GND
 *
 * HX711 wiring:
 *   DT  → D4
 *   SCK → D5
 *   VCC → 5 V
 *   GND → GND
 */

#include <HX711.h>

const byte FLOW_PIN       = 2;          // flow sensor interrupt pin
const byte VALVE_SIG_PIN  = 8;          // relay signal pin
const byte PIN_DOUT       = 4;          // HX711 data  (DT)
const byte PIN_SCK        = 5;          // HX711 clock (SCK)

const unsigned long BAUD  = 115200;
const unsigned long INTERVAL_MS = 500;  // how often to send a CSV frame

constexpr float COUNTS_PER_GRAM = -1153.584f; // calibration slope
constexpr byte  TARE_READS = 20;               // samples for tare
constexpr byte  SOFT_AVG   = 8;                // weight averaging

HX711 scale;
long offset = 0;                               // HX711 tare offset

volatile unsigned long pulseCount = 0;

void setup() {
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), countPulse, RISING);

  pinMode(VALVE_SIG_PIN, OUTPUT);
  digitalWrite(VALVE_SIG_PIN, LOW);   // valve normally closed

  Serial.begin(BAUD);
  while (!Serial) ;

  scale.begin(PIN_DOUT, PIN_SCK);
  long acc = 0;
  for (byte i = 0; i < TARE_READS; ++i) {
    while (!scale.is_ready()) {}
    acc += scale.read();
  }
  offset = acc / TARE_READS;

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

    long acc = 0;
    for (byte i = 0; i < SOFT_AVG; ++i) {
      while (!scale.is_ready()) {}
      acc += scale.read();
    }
    long raw = acc / SOFT_AVG;
    float g = (raw - offset) / COUNTS_PER_GRAM;

    Serial.print(now);
    Serial.print(',');
    Serial.print(count);
    Serial.print(',');
    Serial.println(g, 4);

    lastPrint = now;
  }
}

void countPulse() { pulseCount++; }
