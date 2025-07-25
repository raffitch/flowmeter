/*
 * flow_sensor_1L.ino  –  Streams pulse counter over Serial and supports reset
 * Wire:
 *   Yellow  → D2  (signal)        (use INPUT_PULLUP)
 *   Red     → 5 V
 *   Black   → GND
 */

const byte  FLOW_PIN      = 2;          // interrupt pin
const byte  VALVE_SIG_PIN = 8;          // relay signal pin
const unsigned long BAUD  = 115200;
const unsigned long INTERVAL_MS = 500;  // how often to send a CSV frame

volatile unsigned long pulseCount = 0;

void setup() {
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), countPulse, RISING);

  pinMode(VALVE_SIG_PIN, OUTPUT);
  digitalWrite(VALVE_SIG_PIN, LOW);   // valve normally closed

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

    Serial.print(now);
    Serial.print(',');
    Serial.println(count);

    lastPrint = now;
  }
}

void countPulse() { pulseCount++; }
