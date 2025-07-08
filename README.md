# Flowmeter Calibration Tools

This repository contains a small Arduino sketch, Python bridge and web page
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

1. Upload `Flowmeter/Flowmeter.ino` to an Arduino.
2. Run `python3 flowmeter.py` and select the correct serial port.
3. Open `index.html` in a browser.
4. Enter a target volume, regulator setting and supply pressure then press
   **Start** to capture a run.

The plotted curve can be saved to CSV or PNG. Each CSV contains run metadata
(start/end time, volume, regulator setting and supply pressure) followed by
the filtered pulses‑per‑second data. Record gauge readings manually using the
Supply pressure field.

The interface now shows live averaged pulses per second and can optionally stop
the calibration after a specified number of pulses or elapsed seconds.

Chart.js is used for plotting but you can experiment with real-time plugins or
other libraries such as Plotly if you prefer more advanced visuals.

For consistent results, keep the water source pressure and temperature steady
and perform multiple runs for each regulator setting.
