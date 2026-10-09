# MedSim IP-800 — BLE challenge (simulated insulin pump)

An **extra challenge for a BLE workshop**, meant to run alongside
[`ble_ctf`](https://github.com/hackgnar/ble_ctf) for participants who race ahead.

A Raspberry Pi plays a **simulated insulin/infusion pump** that advertises over
BLE. Participants recon the services, write commands to the pump's *Command
Control Point*, defeat a safety interlock, and ultimately drive a simulated
patient into an unsafe state. A **projector at the front** shows the patient's
vitals in real time with colored gauges (green/amber/red) and credits whoever
succeeds — so the whole class sees when someone "kills the patient".

The profile is based on a **simplified Bluetooth SIG Insulin Delivery Service
(0x183A)**. See [`docs/PROFILE.md`](docs/PROFILE.md) (participant handout) and
[`docs/FACILITATOR.md`](docs/FACILITATOR.md) (answer key — do not share).

## Everything on one Pi
```
┌─────────────────────────── Raspberry Pi ───────────────────────────┐
│  BLE peripheral (BlueZ)  ─┐                                         │
│  physiological model      ├── src/main.py (one asyncio loop)        │
│  web dashboard (aiohttp) ─┘          │                              │
└──────────────────────────────────────┼──────────── HDMI ──► projector
   ▲ BLE                                │ WebSocket
   │                                    ▼
 participants' phones/PCs        Chromium kiosk (fullscreen)
```

## Quick start
**On a Raspberry Pi (live run):**
```bash
./setup.sh
./.venv/bin/python -m src.main --autoreset 30
systemd/kiosk.sh          # projector fullscreen
```

**On any machine (dashboard only, no BLE):**
```bash
python3 -m venv .venv && ./.venv/bin/pip install aiohttp
./.venv/bin/python -m src.main --mock
# open http://localhost:8080/?debug  (debug buttons at the bottom right)
```

**Verify the profile / reference solution:**
```bash
pip install bleak
python3 selftest/attack_client.py --name solution --scenario full
```

## Flags
Nine flags on a difficulty ramp (recon → legal write → defeat the interlock →
kill the patient, plus stealth/bolus bonuses). A participant sets a **Player
Name**, earns flags by interacting, **retrieves** them over GATT and **submits**
them for a personal score — while the projector scoreboard is the public source
of truth. Flag strings are salted per player (cannot be copied).

## Files
| Path | Role |
|---|---|
| `src/model.py` | physiological model (insulin → glucose) |
| `src/ble_server.py` | BlueZ GATT peripheral (dbus-fast, per-connection attribution) |
| `src/controller.py` | opcode parsing, telemetry, death attribution |
| `src/flags.py` | per-player flag/score engine |
| `src/web.py` + `web/` | projector dashboard |
| `src/main.py` | orchestrator |
| `selftest/attack_client.py` | reference solution (bleak) |
| `docs/PROFILE.md` | participant handout |
| `docs/FACILITATOR.md` | answer key + operational notes |

> Educational use only, for authorized security training. No real medical
> device is involved; the model is a crude toy.
