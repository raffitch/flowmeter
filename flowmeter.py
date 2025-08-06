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
LIVE_INTERVAL = 0.05                      # seconds
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
        self.latest_weight = None
        self.latest_pressure = None
        self.latest_pcmd     = None
        self.weight_offset = 0.0
        self.clients       = set()
        self.reset_event   = asyncio.Event()

        # calibration state
        self.cal_running   = False
        self.pulse_start   = 0
        self.weight_start  = 0.0
        self.current_sensor = "flow"
        self.t0            = 0.0
        self.target_litres = 1.0
        self.target_pulses = None
        self.target_weight = None
        self.target_seconds = None
        self.pressure_start = None
        self.pressure_end   = None

        self.status_queue = [json.dumps({"type":"status", "msg":"serial-open"})]

    def send(self, cmd: str) -> None:
        """Send a single-character command to the ESP8266 and log it."""
        self.ser.write(cmd.encode())

        self.ser.flush()

        print(f"→ ESP8266: {cmd}")

    def set_pressure(self, mp: float) -> None:
        mbar = max(0, min(900, int(float(mp) * 1000)))
        cmd = f"s {mbar}\n".encode()
        self.ser.write(cmd)
        self.ser.flush()
        print(f"→ ESP8266: s {mbar}")

    # ── serial→memory loop ────────────────────────────────────────────────
    async def serial_reader(self):
        while True:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
            except serial.SerialException as e:
                print(f"⚠ serial error: {e}")
                self.status_queue.append(json.dumps({"type":"status","msg":"esp-disconnected"}))
                break

            if "," in line:                      # CSV data frame
                parts = line.split(",")
                try:
                    ms = int(parts[0])
                    pc = int(parts[1])
                except (IndexError, ValueError):
                    pass
                else:
                    self.latest_millis = ms
                    self.latest_pulses = pc
                    if len(parts) >= 5:
                        try:
                            self.latest_weight = float(parts[2]) - self.weight_offset
                        except ValueError:
                            pass
                        try:
                            self.latest_pressure = float(parts[3])
                        except ValueError:
                            pass
                        try:
                            self.latest_pcmd = float(parts[4])
                        except ValueError:
                            pass
                    elif len(parts) == 4:
                        try:
                            self.latest_pressure = float(parts[2])
                        except ValueError:
                            pass
                        try:
                            self.latest_pcmd = float(parts[3])
                        except ValueError:
                            pass
                    elif len(parts) == 3:
                        try:
                            self.latest_pressure = float(parts[2])
                        except ValueError:
                            pass
                        self.latest_pcmd = None

            elif line in ("reset-ack", "tare-ack"):
                # Drop any leftover frames so the next data is from the fresh counter
                self.ser.reset_input_buffer()
                self.latest_pulses = 0
                self.latest_millis = 0
                self.latest_pressure = None
                self.latest_pcmd = None
                if line == "tare-ack":
                    self.weight_offset = 0.0  # ESP now reports zero-based weight
                print("↳ reset acknowledged" if line=="reset-ack" else "↳ tare acknowledged")
                self.reset_event.set()
                self.status_queue.append(json.dumps({"type":"status", "msg":"reset"}))
            elif line == "valve-open":
                print("🟢 Valve opened")
            elif line == "valve-closed":
                print("🔴 Valve closed")

            await asyncio.sleep(0.01)

    # ── broadcaster: push live data every LIVE_INTERVAL ───────────────────
    async def broadcaster(self):
        while True:
            if self.clients:
                while self.status_queue:
                    msg = self.status_queue.pop(0)
                    await asyncio.gather(*(c.send(msg) for c in self.clients), return_exceptions=True)
                msg = json.dumps({
                    "type":   "live",
                    "millis": self.latest_millis,
                    "pulses": self.latest_pulses,
                    "weight": self.latest_weight,
                    "pressure": self.latest_pressure,
                    "pCmd": self.latest_pcmd
                })
                await asyncio.gather(
                    *(c.send(msg) for c in self.clients),
                    return_exceptions=True
                )

            if self.cal_running:
                if self.pressure_start is not None and self.pressure_end is not None:
                    progresses = []
                    if self.target_seconds is not None:
                        progresses.append((time.time() - self.t0) / self.target_seconds)
                    if self.target_pulses is not None:
                        progresses.append((self.latest_pulses - self.pulse_start) / self.target_pulses)
                    if progresses:
                        prog = max(0.0, min(1.0, min(progresses)))
                        mp = self.pressure_start + (self.pressure_end - self.pressure_start) * prog
                        self.set_pressure(mp)
                if self.current_sensor == "scale" and self.target_weight is not None:
                    if (self.latest_weight or 0) - self.weight_start >= self.target_weight:
                        await self.finish_calibration()
                if self.current_sensor == "flow" and self.target_pulses is not None:
                    if self.latest_pulses - self.pulse_start >= self.target_pulses:
                        await self.finish_calibration()
                if self.target_seconds is not None:
                    if time.time() - self.t0 >= self.target_seconds:
                        await self.finish_calibration()
            await asyncio.sleep(LIVE_INTERVAL)

    async def finish_calibration(self):
        """Stop calibration, close valve and broadcast result."""
        self.send('c')
        self.set_pressure(0)  # ramp command back to 0 MPa
        self.ser.write(b'p 0\n')
        self.ser.flush()
        print("→ ESP8266: p 0")
        self.cal_running = False
        elapsed = time.time() - self.t0
        start_p = self.pressure_start or 0.0
        end_p   = self.pressure_end if self.pressure_end is not None else (self.latest_pressure or 0.0)
        if self.current_sensor == "scale":
            delta = (self.latest_weight or 0) - self.weight_start
            rate = delta / elapsed if elapsed > 0 else 0
            msg = json.dumps({
                "type": "cal",
                "sensor": "scale",
                "delta": round(delta, 2),
                "elapsed": round(elapsed, 2),
                "rate": round(rate, 2),
                "startP": round(start_p, 3),
                "endP": round(end_p, 3)
            })
        else:
            delta = self.latest_pulses - self.pulse_start
            rate = delta / elapsed if elapsed > 0 else 0
            msg = json.dumps({
                "type": "cal",
                "sensor": "flow",
                "delta": delta,
                "elapsed": round(elapsed, 2),
                "pps": round(rate, 2),
                "startP": round(start_p, 3),
                "endP": round(end_p, 3)
            })
        await asyncio.gather(*(c.send(msg) for c in self.clients), return_exceptions=True)
        self.target_pulses = None
        self.target_weight = None
        self.target_seconds = None
        self.pressure_start = None
        self.pressure_end   = None

    # ── websocket handler ────────────────────────────────────────────────
    async def ws_handler(self, ws):
        self.clients.add(ws)
        print("🌐 client connected")
        self.status_queue.append(json.dumps({"type":"status","msg":"client-connected"}))

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
                    # Fast start: open valve immediately and use differential counting
                    self.ser.reset_input_buffer()
                    p_start = data.get("pStart")
                    p_end   = data.get("pEnd")
                    if isinstance(p_start, (int, float)):
                        self.pressure_start = float(p_start)
                        self.set_pressure(self.pressure_start)
                    else:
                        self.pressure_start = None
                    if isinstance(p_end, (int, float)):
                        self.pressure_end = float(p_end)
                    else:
                        self.pressure_end = self.pressure_start
                    self.pulse_start    = self.latest_pulses
                    self.send('o')                # open valve now
                    self.cal_running    = True
                    # retain latest_pulses for delta calculations
                    self.weight_start  = self.latest_weight or 0.0
                    self.current_sensor = data.get("sensor", "flow")
                    self.t0            = time.time()
                    self.target_litres = float(data.get("volume", 1))
                    pulses_val = data.get("pulses")
                    weight_val = data.get("weight")
                    seconds_val = data.get("seconds")
                    self.target_pulses = (
                        int(pulses_val) if isinstance(pulses_val, (int, float)) and pulses_val > 0 else None
                    )
                    self.target_weight = (
                        float(weight_val) if isinstance(weight_val, (int, float)) and weight_val > 0 else None
                    )
                    try:
                        seconds_f = float(seconds_val)
                    except (TypeError, ValueError):
                        seconds_f = None
                    self.target_seconds = seconds_f if seconds_f and seconds_f > 0 else None
                    await ws.send(json.dumps({"type":"ack","status":"started"}))

                # ---- stop calibration ----
                elif cmd == "stop" and self.cal_running:
                    await self.finish_calibration()

                # ---- reset counter ----
                elif cmd == "reset":
                    # clear any queued frames so old data doesn't leak
                    self.ser.reset_input_buffer()
                    self.pressure_start = None
                    self.pressure_end = None
                    if self.current_sensor == "scale":
                        self.send('t')            # tare command
                        self.weight_offset = self.latest_weight or 0.0
                        self.latest_weight = 0.0
                    else:
                        self.send('r')            # reset pulse counter
                    self.latest_pulses = 0
                    self.latest_millis = 0
                    await ws.send(json.dumps({"type":"ack","status":"reset-sent"}))

                # ---- manual pressure set ----
                elif cmd == "set":
                    mp = data.get("mpa")
                    if isinstance(mp, (int, float)):
                        self.set_pressure(float(mp))

        finally:
            self.clients.discard(ws)
            print("🌐 client disconnected")
            self.status_queue.append(json.dumps({"type":"status","msg":"client-disconnected"}))

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
