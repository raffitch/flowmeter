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
   flow sensor on pin **D2**, the valve control on **D8** and the HX711 on **D6/D7**.
   It prints a CSV frame roughly every 150 ms. Pulses are debounced in hardware
   and, if a HX711 scale is connected, weight is streamed alongside the pulse
   count.
2. Run `python3 flowmeter.py` and select the correct serial port.
3. Open `index.html` in a browser.
4. Enter the regulator version and supply pressure (in MPa). Choose whether to
   use the flow sensor or scale, then press **Start** to capture a run. The
   calibration volume is fixed at 1 L.

The plotted curve can be saved to CSV or PNG. Each CSV contains run metadata
(start/end time, volume, regulator version and supply pressure) followed by the
filtered pulses per second or grams depending on the sensor. Record gauge
readings manually using the Supply pressure field.

The interface shows live pulses per second or weight. When the scale is
selected, the chart plots the running average in litres per second rather than
raw weight. A median filter removes spikes before averaging and smoothing the
flow sensor data. Calibration can stop after a specified number of pulses,
grams or elapsed seconds. Auto‑stop ends a run if the selected sensor doesn't
change for about a second.

Pressing **Reset** clears the current run. When the scale sensor is selected it
sends a dedicated `t` command to tare the HX711 so the next readings are
reported relative to zero. The Python bridge temporarily subtracts the current
weight to keep the display steady while the ESP8266 performs the tare.

Plotly is used for plotting, providing zoomable curves and hover details. Each
run is drawn as a separate trace with its pressure and regulator version in the
legend so multiple runs overlay for easy comparison, and completed runs are
summarised with the average pulses per second.

For consistent results, keep the water source pressure and temperature steady
and perform multiple runs for each regulator version.
