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
the filtered pulses‑per‑second data.

For consistent results, keep the water source pressure and temperature steady
and perform multiple runs for each regulator setting.

## HX711 scale

`Flowmeter/Flowmeter.ino` also reads a load cell via the HX711 amplifier and includes the weight in each CSV frame. Connect the HX711 pins as follows:

```
HX711 DT  → Arduino D4
HX711 SCK → Arduino D5
VCC → 5 V
GND → GND
```

After uploading the sketch, run `python3 flowmeter.py` as usual. The web interface will display the live weight and you can set a weight target to stop the run automatically.
