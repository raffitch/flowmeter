#!/usr/bin/env python3
"""
flow_calibrator.py
──────────────────
• Lists serial devices, lets you pick the ESP8266.
• Relays CSV frames ("millis,pulses") to the browser via WebSocket.
• Accepts 'start', 'stop', and 'reset' commands from the browser.
"""

import argparse, asyncio, json, sys, time, pathlib, webbrowser
import serial, serial.tools.list_ports, websockets

BAUD_RATE     = 115_200
LIVE_INTERVAL = 0.2                       # seconds
WS_HOST, WS_PORT = "localhost", 8765

# ── helper: choose serial port ─────────────────────────────────────────────
def choose_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        sys.exit("❌  No serial devices detected.")

    print("\nAvailable serial devices:\n")
    for i, p in enumerate(ports):
        print(f" {i}: {p.device:<15} {p.description}")
    idx = input(f"\nSelect port [0–{len(ports)-1}] (default 0): ").strip() or "0"
    try:
        return ports[int(idx)].device
    except (ValueError, IndexError):
        sys.exit("❌  Invalid selection.")

# ── flow server class ──────────────────────────────────────────────────────
class FlowServer:
    def __init__(self, port: str):
        print(f"🔗  Opening {port} @ {BAUD_RATE} …")
        self.ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2.0)  # allow ESP8266 reboot

        banner = ""
        start = time.time()
        while time.time() - start < 5:
            line = self.ser.readline().decode(errors="ignore").strip()
            if line:
                banner = line
                if line == "ready":
                    break
        print(f"🖥  ESP8266 says: {banner or '<no banner>'}")
        self.ser.reset_input_buffer()

        self.latest_pulses = 0
        self.latest_millis = 0
        self.clients       = set()

        # calibration state
        self.cal_running  = False
        self.pulse_start  = 0
        self.t0           = 0.0
        self.target_litres = 1.0
        self.target_pulses = None
        self.target_seconds = None

        self.status_queue = [json.dumps({"type":"status", "msg":"serial-open"})]

    def send(self, cmd: str) -> None:
        """Send a single-character command to the ESP8266 and log it."""
        self.ser.write(cmd.encode())

        self.ser.flush()

        print(f"→ ESP8266: {cmd}")

    # ── serial→memory loop ────────────────────────────────────────────────
    async def serial_reader(self):
        while True:
            line = self.ser.readline().decode(errors="ignore").strip()

            if "," in line:                      # CSV data frame
                parts = line.split(",")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    ms, pc = parts[0], parts[1]
                    self.latest_millis = int(ms)
                    self.latest_pulses = int(pc)

            elif line == "reset-ack":            # ESP8266 confirmation
                print("↳ reset acknowledged")
                self.status_queue.append(json.dumps(
                    {"type":"status", "msg":"counter-reset"}))
            elif line == "valve-open":
                print("🟢 Valve opened")
            elif line == "valve-closed":
                print("🔴 Valve closed")

            await asyncio.sleep(0.01)

    # ── broadcaster: push live data every LIVE_INTERVAL ───────────────────
    async def broadcaster(self):
        while True:
            if self.clients:
                msg = json.dumps({
                    "type":   "live",
                    "millis": self.latest_millis,
                    "pulses": self.latest_pulses
                })
                await asyncio.gather(
                    *(c.send(msg) for c in self.clients),
                    return_exceptions=True
                )

            if self.cal_running:
                if self.target_pulses is not None:
                    if self.latest_pulses - self.pulse_start >= self.target_pulses:
                        await self.finish_calibration()
                if self.target_seconds is not None:
                    if time.time() - self.t0 >= self.target_seconds:
                        await self.finish_calibration()
            await asyncio.sleep(LIVE_INTERVAL)

    async def finish_calibration(self):
        """Stop calibration, close valve and broadcast result."""
        self.send('c')
        self.cal_running = False
        delta = self.latest_pulses - self.pulse_start
        elapsed = time.time() - self.t0
        pps = delta / elapsed if elapsed > 0 else 0
        msg = json.dumps({
            "type":   "cal",
            "delta":  delta,
            "elapsed": round(elapsed, 2),
            "volume":  self.target_litres,
            "pps":     round(pps, 2)
        })
        await asyncio.gather(*(c.send(msg) for c in self.clients), return_exceptions=True)
        self.target_pulses = None
        self.target_seconds = None

    # ── websocket handler ────────────────────────────────────────────────
    async def ws_handler(self, ws):
        self.clients.add(ws)

        # push queued status messages once
        while self.status_queue:
            await ws.send(self.status_queue.pop(0))

        try:
            async for text in ws:
                try:
                    data = json.loads(text)
                    cmd = data.get("cmd", "").lower()
                except json.JSONDecodeError:
                    data = {}
                    cmd = text.strip().lower()

                # ---- start calibration ----
                if cmd == "start" and not self.cal_running:
                    # reset ESP8266 counter so each run begins at zero
                    self.send('r')                # reset
                    self.send('o')                # open valve
                    self.latest_pulses = 0
                    self.cal_running   = True
                    self.pulse_start   = 0
                    self.t0            = time.time()
                    self.target_litres = float(data.get("volume", 1))
                    self.target_pulses = data.get("pulses")
                    self.target_seconds = data.get("seconds")
                    await ws.send(json.dumps({"type":"ack","status":"started"}))

                # ---- stop calibration ----
                elif cmd == "stop" and self.cal_running:
                    await self.finish_calibration()

                # ---- reset counter ----
                elif cmd == "reset":
                    self.send('r')                # tell ESP8266
                    self.latest_pulses = 0
                    self.latest_millis = 0
                    await ws.send(json.dumps({"type":"ack","status":"reset-sent"}))
        finally:
            self.clients.discard(ws)

# ── main ──────────────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser(description="WebSocket bridge for flow sensor")
    ap.add_argument("-p", "--port", help="Serial port (e.g. COM3, /dev/ttyACM0)")
    args = ap.parse_args()

    port = args.port or choose_port()
    try:
        fs = FlowServer(port)
        print("✔ Connected")
    except serial.SerialException as e:
        sys.exit(f"❌  Could not open {port}: {e}")

    # start WebSocket server before opening the browser to avoid connection
    # errors when the page loads
    server = await websockets.serve(fs.ws_handler, WS_HOST, WS_PORT)

    async def open_interface():
        # give the websocket server a moment to start before opening the page
        await asyncio.sleep(2.0)
        webbrowser.open((pathlib.Path(__file__).parent/'index.html').resolve().as_uri())

    await asyncio.gather(
        fs.serial_reader(),
        fs.broadcaster(),
        server.wait_closed(),
        open_interface(),
    )

if __name__ == "__main__":
    asyncio.run(main())
