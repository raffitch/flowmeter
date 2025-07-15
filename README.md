# Flowmeter Calibration Tools

This repository contains a small ESP8266 sketch, Python bridge and web page
for visualising pulses from a hall‑effect flow sensor.

## Requirements

* Python 3
* `pyserial`
* `websockets`

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

1. Upload `Flowmeter/Flowmeter.ino` to an ESP8266 board. It prints a CSV frame
   every 200 ms. Pulses are debounced in hardware using a microsecond guard so
   spurious edges are ignored.
2. Run `python3 flowmeter.py` and select the correct serial port.
3. Open `index.html` in a browser.
4. Enter the regulator version and supply pressure (in MPa) then press
   **Start** to capture a run. The calibration volume is fixed at 1 L.

The plotted curve can be saved to CSV or PNG. Each CSV contains run metadata
(start/end time, volume, regulator version and supply pressure) followed by
the filtered pulses‑per‑second data. Record gauge readings manually using the
Supply pressure field.

The interface shows live pulses per second. A median filter removes single-frame
spikes, then a one‑second moving average and exponential smoothing clean up
outliers. Calibration can optionally stop after a specified number of pulses or
elapsed seconds. Seconds are counted from when **Start** is pressed, even if no
pulses arrive. Enable the **auto-stop** checkbox to end a run when the pulse
count hasn't changed for roughly a second.

Plotly is used for plotting, providing zoomable curves and hover details. Each
run is drawn as a separate trace with its pressure and regulator version in the
legend so multiple runs overlay for easy comparison, and completed runs are
summarised with the average pulses per second.

For consistent results, keep the water source pressure and temperature steady
and perform multiple runs for each regulator version.
