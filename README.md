# Flowmeter Calibration Tools

This repository contains a small ESP8266 sketch, Python bridge and web page
for visualising pulses from a hall‑effect flow sensor or an HX711 based scale.

## Requirements

* Python 3
* `pyserial`
* `websockets`

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

1. Upload `Flowmeter/Flowmeter.ino` to an ESP8266 board. The sketch expects the
   flow sensor on pin **D2**, the valve control on **D8**, the ITV2050 driver on
   **D5** (0–10 V via a GP8101S) and the HX711 on **D6/D7**. An analog pressure
   feedback should connect to **A0**. At start‑up the sketch samples the idle
   voltage from this 220 Ω divider and subtracts it so 0 MPa reads near zero.
   The PWM pin on D5 is claimed and driven
   low before any serial output and `Serial.setDebugOutput(false)` keeps it
   quiet; when compiling, select **Debug Port: Disabled** and **Debug Level: None**
   (or define `-DNDEBUG`) to prevent the SDK from writing to the UART. The sketch
   prints a CSV frame roughly every 150 ms. Pulses are debounced in hardware and,
   if a HX711 scale is connected, weight is streamed alongside the pulse count.
   Pressure (in MPa) is reported on every frame along with the commanded set‑point.
2. Run `python3 flowmeter.py` and select the correct serial port.
3. Open `index.html` (Flow Mapper) in a browser.
4. Enter the regulator version along with starting and ending pressures (MPa).
   The page shows the corresponding 0–10 V drive levels. Choose whether to use
   the flow sensor or scale, then press **Start** to capture a run. The bridge
   ramps the pressure from the start value to the end value over the course of
   the run, stopping when the selected pulse or time limit is reached. At the
   end of each run it commands 0 MPa so the DAC returns to 0 V. The calibration
   volume is fixed at 1 L. A **Mode** dropdown also offers a *Manual* option
   with a slider that directly sets the pressure without starting a timed
   experiment, useful for quick bench tests.

The plotted curve can be saved to CSV or PNG. Each CSV contains run metadata
(start/end time, volume, regulator version, programmed start/end pressure) plus
the filtered pulses per second or grams depending on the sensor.

The interface shows live pulses per second or weight. When the scale is
selected, the chart plots the running average in litres per second rather than
raw weight. A median filter removes spikes before averaging and smoothing the
flow sensor data. Calibration can stop after a specified number of pulses,
grams or elapsed seconds. Auto‑stop ends a run if the selected sensor doesn't
change for about a second.

Live status panels list the current drive voltage, the commanded pressure and
the measured MPa beside the pulse count, elapsed time and average pulses per
second.

The status line indicates whether the WebSocket or ESP8266 connection drops.
Starting and stopping a run also play short tones so you can hear when the
valve opens or closes.

Pressing **Reset** clears the current run. When the scale sensor is selected it
sends a dedicated `t` command to tare the HX711 so the next readings are
reported relative to zero. The Python bridge temporarily subtracts the current
weight to keep the display steady while the ESP8266 performs the tare. Starting
a run opens the valve immediately and measures the difference from the current
counters so there is no delay.

Plotly is used for plotting, providing zoomable curves and hover details. Each
run is drawn as a separate trace with its pressure and regulator version in the
legend so multiple runs overlay for easy comparison, and completed runs are
summarised with the average pulses per second.

Each log entry includes a **Delete** button so unwanted runs can be removed from
the plot and excluded from CSV exports before saving.

CSV exports show all runs side by side: the first column lists the timestamps
while each additional column contains one run labelled with its pressure in MPa.
Comment lines report the total pulses for each run.

For consistent results, keep the water source pressure and temperature steady
and perform multiple runs for each regulator version.
