/* --------------------------------------------------------
   HX711 scale firmware  –  v2.0
   Outputs: <millis>\t<grams>\n      @ 20 Hz
   -------------------------------------------------------- */

#include <HX711.h>

// Pinout on scale driver
// SCK yellow driver side  / blue Arduino side
// DT  orange driver side / green Arduino side
// VCC white
// GND black

// Pin mapping – adjust to your wiring
constexpr byte PIN_DOUT = 4;  // changed from 2 to avoid conflict with flow sensor
constexpr byte PIN_SCK  = 5;

HX711 scale;

// Set this to the slope from your one-time calibration (counts per gram)
constexpr float COUNTS_PER_GRAM = -1153.584f;
// Number of samples used to determine the tare offset on startup
constexpr byte TARE_READS = 20;

long offset = 0;   // determined during tare

// -------- parameters you may tune -------------------------
constexpr unsigned long SAMPLE_PERIOD_MS = 50;   // 20 Hz
constexpr byte   SOFT_AVG = 8;   // =1 → no averaging, >1 → avg N reads
// ----------------------------------------------------------

void setup()
{
    Serial.begin(115200);
    while (!Serial) ;          // wait for host

    scale.begin(PIN_DOUT, PIN_SCK);

    // -------- tare on startup ---------------------------------------
    long acc = 0;
    for (byte i = 0; i < TARE_READS; ++i) {
        while (!scale.is_ready()) {}
        acc += scale.read();
    }
    offset = acc / TARE_READS;
}

void loop()
{
    static unsigned long t_last = 0;
    unsigned long now = millis();
    if (now - t_last >= SAMPLE_PERIOD_MS && scale.is_ready())
    {
        t_last = now;

        long acc = 0;
        for (byte i = 0; i < SOFT_AVG; ++i)
            acc += scale.read();
        long raw = acc / SOFT_AVG;
        float g = (raw - offset) / COUNTS_PER_GRAM;

        Serial.print(now);     // time-stamp first
        Serial.print('\t');
        Serial.println(g, 4);  // weight in grams
    }
}
