#!/usr/bin/env python3
"""
flow_calibrator.py
──────────────────
• Lists serial devices, lets you pick the Arduino.
• Relays CSV frames ("millis,pulses") to the browser via WebSocket.
• Accepts 'start', 'stop', and 'reset' commands from the browser.
"""

import argparse, asyncio, json, sys, time
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

        banner = self.ser.readline().decode(errors="ignore").strip()
        print(f"🖥  Arduino says: {banner or '<no banner>'}")

        self.latest_pulses = 0
        self.latest_millis = 0
        self.clients       = set()

        # calibration state
        self.cal_running  = False
        self.pulse_start  = 0
        self.t0           = 0.0

        self.status_queue = [json.dumps({"type":"status", "msg":"serial-open"})]

    # ── serial→memory loop ────────────────────────────────────────────────
    async def serial_reader(self):
        while True:
            line = self.ser.readline().decode(errors="ignore").strip()

            if "," in line:                      # CSV data frame
                ms, pc              = line.split(",")
                self.latest_millis  = int(ms)
                self.latest_pulses  = int(pc)

            elif line == "reset-ack":            # Arduino confirmation
                self.status_queue.append(json.dumps(
                    {"type":"status", "msg":"counter-reset"}))

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
            await asyncio.sleep(LIVE_INTERVAL)

    # ── websocket handler ────────────────────────────────────────────────
    async def ws_handler(self, ws):
        self.clients.add(ws)

        # push queued status messages once
        while self.status_queue:
            await ws.send(self.status_queue.pop(0))

        try:
            async for text in ws:
                cmd = text.strip().lower()

                # ---- start calibration ----
                if cmd == "start" and not self.cal_running:
                    self.cal_running = True
                    self.pulse_start = self.latest_pulses
                    self.t0          = time.time()
                    await ws.send(json.dumps({"type":"ack","status":"started"}))

                # ---- stop calibration ----
                elif cmd == "stop" and self.cal_running:
                    self.cal_running = False
                    delta   = self.latest_pulses - self.pulse_start
                    elapsed = time.time() - self.t0
                    await ws.send(json.dumps({
                        "type":   "cal",
                        "delta":  delta,
                        "elapsed": round(elapsed, 2),
                        "ppl":    delta          # 1-litre run
                    }))

                # ---- reset counter ----
                elif cmd == "reset":
                    self.ser.write(b"r")         # tell Arduino
                    await ws.send(json.dumps({"type":"ack","status":"reset-sent"}))
        finally:
            self.clients.discard(ws)

# ── main ──────────────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser(description="WebSocket bridge for flow sensor")
    ap.add_argument("-p", "--port", help="Serial port (e.g. COM3, /dev/ttyACM0)")
    args = ap.parse_args()

    port = args.port or choose_port()
    fs   = FlowServer(port)

    await asyncio.gather(
        fs.serial_reader(),
        fs.broadcaster(),
        websockets.serve(fs.ws_handler, WS_HOST, WS_PORT)
    )

if __name__ == "__main__":
    asyncio.run(main())
