"""
MedSim IP-800 — main orchestrator.

Runs in ONE asyncio loop:
  * model steps (~10 Hz, wall-clock dt) + death detection/attribution
  * BLE telemetry push (IDD Status + Heart Rate, ~1 Hz)
  * dashboard broadcast over WebSocket (~10 Hz)
  * auto-reset of the patient (optional)

On a Raspberry Pi:      python3 -m src.main
On a dev machine (no BLE): python3 -m src.main --mock
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import time

from . import config
from .model import PumpModel
from .flags import FlagEngine
from .controller import DeviceController
from .web import WebServer


async def run(args):
    model = PumpModel()
    flags = FlagEngine()
    controller = DeviceController(model, flags)
    webserver = WebServer(model, flags, controller, host=args.host, port=args.port)
    await webserver.start()
    print(f"[web] dashboard at http://{args.host}:{args.port}/  (fullscreen on the projector)")

    ble = None
    if not args.mock:
        from .ble_server import BLEServer
        ble = BLEServer(controller, adapter=args.adapter)
        await ble.start()
        print(f"[ble] advertising '{model_name()}' via {args.adapter}")
    else:
        print("[ble] MOCK mode: no BLE. Use the debug buttons in the dashboard.")

    webserver.auto_reset_s = args.autoreset

    sound_device = None if args.no_sound else args.sound_device
    if sound_device:
        ok = os.path.exists(config.SOUND_FILE) and shutil.which("aplay")
        print(f"[sound] flatline on death via {sound_device} "
              f"({'ready' if ok else 'aplay/file missing - will skip'})")

    await asyncio.gather(
        sim_loop(model, controller, webserver, ble, sound_device),
        broadcast_loop(webserver),
    )


def model_name():
    return config.DEVICE_NAME


def play_death_sound(device):
    """Fire-and-forget flatline tone via ALSA (aplay). Never raises."""
    if not device or not config.SOUND_FILE or not os.path.exists(config.SOUND_FILE):
        return
    if not shutil.which("aplay"):
        return
    try:
        subprocess.Popen(
            ["aplay", "-q", "-D", device, config.SOUND_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print("[sound] playback failed:", e)


async def sim_loop(model, controller, webserver, ble, sound_device=None):
    last = time.monotonic()
    last_telemetry = 0.0
    death_time = None
    while True:
        now = time.monotonic()
        dt = min(0.5, now - last)      # cap on pauses
        last = now

        just_died = model.step(dt)
        if just_died:
            controller.on_death()
            play_death_sound(sound_device)
            death_time = now

        # auto-reset
        if model.deceased and webserver.auto_reset_s > 0 and death_time is not None:
            if now - death_time >= webserver.auto_reset_s:
                model.revive()
                controller.flags.add_event("system", "reset",
                                           "auto-reset - new patient connected")
                death_time = None

        # BLE telemetry ~1 Hz
        if ble and now - last_telemetry >= 1.0:
            last_telemetry = now
            try:
                ble.push_status(controller.status_payload())
                ble.push_hr(controller.hr_measurement())
            except Exception as e:
                print("[ble] telemetry error:", e)

        await asyncio.sleep(0.1)


async def broadcast_loop(webserver):
    while True:
        await webserver.broadcast()
        await asyncio.sleep(0.1)


def main():
    ap = argparse.ArgumentParser(description="MedSim IP-800 BLE challenge")
    ap.add_argument("--mock", action="store_true",
                    help="Run without BLE (model + dashboard only, for dev/demo)")
    ap.add_argument("--adapter", default="hci0", help="BlueZ adapter (default hci0)")
    ap.add_argument("--host", default="0.0.0.0", help="Dashboard host")
    ap.add_argument("--port", type=int, default=8080, help="Dashboard port")
    ap.add_argument("--autoreset", type=int, default=0,
                    help="Auto-revive the patient N seconds after death (0=off)")
    ap.add_argument("--sound-device", default=config.SOUND_DEVICE_DEFAULT,
                    help="ALSA device for the flatline sound on death "
                         "(default: the Pi's 3.5mm jack)")
    ap.add_argument("--no-sound", action="store_true",
                    help="Disable the flatline death sound")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()
