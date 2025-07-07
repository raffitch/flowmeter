#!/usr/bin/env python3
"""
flow_calibrator.py
──────────────────
• Lists serial devices, lets you pick the Arduino.
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
    def __init__(self, port: str, scale_port: str|None=None):
        print(f"🔗  Opening {port} @ {BAUD_RATE} …")
        self.ser = serial.Serial(port, BAUD_RATE, timeout=1)

        self.scale_ser = None
        if scale_port:
            try:
                print(f"🔗  Opening scale on {scale_port} @ {BAUD_RATE} …")
                self.scale_ser = serial.Serial(scale_port, BAUD_RATE, timeout=1)
                # flush any startup noise
                time.sleep(2)
                self.scale_ser.reset_input_buffer()
            except serial.SerialException as e:
                print(f"⚠️  Could not open scale port {scale_port}: {e}")

        banner = self.ser.readline().decode(errors="ignore").strip()
        print(f"🖥  Arduino says: {banner or '<no banner>'}")

        self.latest_pulses = 0
        self.latest_millis = 0
        self.latest_weight = 0.0
        self.clients       = set()

        # calibration state
        self.cal_running  = False
        self.pulse_start  = 0
        self.t0           = 0.0
        self.target_litres = 1.0

        self.status_queue = [json.dumps({"type":"status", "msg":"serial-open"})]

        self.target_weight = 0.0

    def send(self, cmd: str) -> None:
        """Send a single-character command to the Arduino and log it."""
        self.ser.write(cmd.encode())

        self.ser.flush()

        print(f"→ Arduino: {cmd}")

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
            elif line == "valve-open":
                print("🟢 Valve opened")
            elif line == "valve-closed":
                print("🔴 Valve closed")

            await asyncio.sleep(0.01)

    # ── scale serial→memory loop ----------------------------------------
    async def scale_reader(self):
        if not self.scale_ser:
            return
        while True:
            line = self.scale_ser.readline().decode(errors='ignore').strip()
            if line:
                try:
                    _, g = line.split('\t')
                    self.latest_weight = float(g)
                    if (
                        self.target_weight > 0
                        and self.latest_weight >= self.target_weight
                        and self.cal_running
                    ):
                        await self.stop_due_to_weight()
                except ValueError:
                    pass
            await asyncio.sleep(0.01)

    async def stop_due_to_weight(self):
        self.send('c')
        self.cal_running = False
        delta = self.latest_pulses - self.pulse_start
        elapsed = time.time() - self.t0
        ppl = delta / self.target_litres if self.target_litres else 0
        msg = json.dumps({
            "type": "cal",
            "delta": delta,
            "elapsed": round(elapsed, 2),
            "volume": self.target_litres,
            "ppl": round(ppl, 2)
        })
        await self._notify_clients(msg)
        self.target_weight = 0.0

    async def _notify_clients(self, msg: str):
        if self.clients:
            await asyncio.gather(*(c.send(msg) for c in self.clients), return_exceptions=True)

    # ── broadcaster: push live data every LIVE_INTERVAL ───────────────────
    async def broadcaster(self):
        while True:
            if self.clients:
                msg = json.dumps({
                    "type":   "live",
                    "millis": self.latest_millis,
                    "pulses": self.latest_pulses,
                    "weight": self.latest_weight
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
                try:
                    data = json.loads(text)
                    cmd = data.get("cmd", "").lower()
                except json.JSONDecodeError:
                    data = {}
                    cmd = text.strip().lower()

                # ---- start calibration ----
                if cmd == "start" and not self.cal_running:
                    # reset Arduino counter so each run begins at zero
                    self.send('r')                # reset
                    self.send('o')                # open valve
                    self.latest_pulses = 0
                    self.cal_running   = True
                    self.pulse_start   = 0
                    self.t0            = time.time()
                    self.target_litres = float(data.get("volume", 1))
                    self.target_weight = float(data.get("weightTarget", 0))
                    await ws.send(json.dumps({"type":"ack","status":"started"}))

                # ---- stop calibration ----
                elif cmd == "stop" and self.cal_running:
                    self.send('c')                # close valve
                    self.cal_running = False
                    delta   = self.latest_pulses - self.pulse_start
                    elapsed = time.time() - self.t0
                    ppl = delta / self.target_litres if self.target_litres else 0
                    await ws.send(json.dumps({
                        "type":   "cal",
                        "delta":  delta,
                        "elapsed": round(elapsed, 2),
                        "volume": self.target_litres,
                        "ppl":    round(ppl, 2)
                    }))
                    self.target_weight = 0.0

                # ---- reset counter ----
                elif cmd == "reset":
                    self.send('r')                # tell Arduino
                    await ws.send(json.dumps({"type":"ack","status":"reset-sent"}))
        finally:
            self.clients.discard(ws)

# ── main ──────────────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser(description="WebSocket bridge for flow sensor")
    ap.add_argument("-p", "--port", help="Serial port (e.g. COM3, /dev/ttyACM0)")
    ap.add_argument("--scale-port", help="Serial port for HX711 scale")
    args = ap.parse_args()

    port = args.port or choose_port()
    try:
        fs = FlowServer(port, scale_port=args.scale_port)
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
        fs.scale_reader(),
        fs.broadcaster(),
        server.wait_closed(),
        open_interface(),
    )

if __name__ == "__main__":
    asyncio.run(main())
