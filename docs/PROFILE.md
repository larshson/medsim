# MedSim IP-800 — GATT profile (participant handout)

This is a **simulated** insulin/infusion pump for security training. It mimics a
real device but runs a physiological model internally. The screen at the front
shows the patient's state in real time.

The profile is based on a **simplified subset of the Bluetooth SIG Insulin
Delivery Service (0x183A)**. Full IDS uses sequence counters and per-command
E2E-CRC — we deliberately left that out to keep the challenge focused on BLE
recon and writes. The attack surface is the **Command Control Point**.

## Services

### Device Information (0x180A) — standard, readable

| Characteristic | UUID | Access | Content |
| ----------------- | ------ | ------ | --------------------------------- |
| Manufacturer Name | 0x2A29 | read | manufacturer |
| Model Number | 0x2A24 | read | model |
| Serial Number | 0x2A25 | read | serial number |
| Firmware Revision | 0x2A26 | read | firmware string *(read closely…)* |
| Hardware Revision | 0x2A27 | read | hardware revision |

### Battery (0x180F) — standard

| Characteristic    | UUID   | Access | Content                           |
| ----------------- | ------ | ------ | --------------------------------- |
| Battery Level | 0x2A19 | read/notify | 0–100 % |

### Heart Rate (0x180D) — standard, patient telemetry
| Characteristic    | UUID   | Access | Content                           |
| ----------------- | ------ | ------ | --------------------------------- |
| Heart Rate Measurement | 0x2A37 | read/notify | Standard format: `[flags=0x00][BPM:uint8]` |

### Insulin Delivery Service (0x183A) — simplified
| Characteristic | UUID | Access | Content |
| ------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------- |
| IDD Features | 0x2B23 | read | `[features:uint8][factory_max_centiUpH:uint16][hard_ceiling_centiUpH:uint16]` (LE) |
| IDD Status | 0x2B22 | read/notify | see below |
| IDD Command Control Point | 0x2B25 | write | see opcodes below |

**IDD Status payload** (little-endian):
```
[flags:uint8][basal_centiUpH:uint16][maxlimit_centiUpH:uint16][reservoir:uint16][glucose_centi_mmolL:uint16]
flags: bit0=therapy active, bit1=maintenance unlocked, bit2=alarms silenced,
       bit3=occlusion, bit4=patient deceased
```
All `centi` fields are the value × 100 (e.g. basal 2.50 U/h = 250).

**Command Control Point opcodes** (`[opcode:uint8][params…]`):

| Opcode | Name | Params | Effect |
| ------ | ------------------- | -------------------- | ------------------------------------------- |
| 0x01 | Set Basal Rate | uint16 LE, centi-U/h | set basal rate (clamped to the max limit) |
| 0x02 | Set Bolus | uint16 LE, centi-U | give a bolus (clamped to the bolus cap) |
| 0x03 | Set Max Basal Limit | uint16 LE, centi-U/h | **protected** — requires maintenance unlock |
| 0x04 | Maintenance Unlock | 4-byte key | unlock maintenance mode |
| 0x05 | Silence Alarms | uint8 (1=silence) | silence the alarms |
| 0x06 | Stop Therapy | — | emergency stop |

### CTF service (custom) — identity, flags, scoring
| Characteristic | UUID | Access | Content |
| -------------- | ---------------- | ---------- | ------------------------------------------- |
| Player Name | `…-000000000002` | read/write | write your handle (shown on the scoreboard) |
| Flag | `…-000000000003` | read | your earned flag strings |
| Submit Flag | `…-000000000004` | write→read | write a flag string, read for the result |
| Score | `…-000000000005` | read | your score |

Full CTF-service UUID base: `4d454453-494d-4d00-0000-0000000000XX`.

## Objectives — the 9 flags
Each objective below is one flag. We tell you **what** to achieve, never **how** —
working out the technique (which characteristic, which command, which value, and
where a secret might be hidden) is the challenge. They roughly get harder from top
to bottom.

| Flag | Objective |
|---|---|
| F1 | Read the device's Model Number |
| F2 | Read the pump's IDD Features |
| F3 | Set a basal rate within the safe limit |
| F4 | Attempt a dose above the safety limit (trip the interlock) |
| F5 | Unlock maintenance mode |
| F6 | Raise or disable the maximum basal limit |
| F7 | Drive the patient into a fatal overdose |
| F8 | Kill the patient with the alarms silenced |
| F9 | Kill the patient with a single bolus |

These are the same titles that light up on the projector scoreboard as you earn
them.

## How flags are reported (so nothing is guesswork)
1. **Set your Player Name first** — write it to the Player Name characteristic so
   your progress shows under your name on the projector (otherwise an anonymous
   address).
2. Work the objectives above. The instant you complete one it shows up:
   - on the **projector scoreboard** — your row lights up that flag, and
   - in your **Flag characteristic** — read it to get your earned flag strings.
3. Read the **Score characteristic** any time for `Score: n/9 (earned: X)`.
4. To bank a flag for points, **write its string to Submit Flag**, then **read**
   Submit Flag for the result.

Flag strings are **personal** (salted per player) — copying someone else's earns
nothing. And the big achievements — actually driving the patient into an unsafe
state — are visible to the whole class on the screen.

Tooling tips: `nRF Connect` (mobile), `bleak`/`bluetoothctl`/`gatttool` (PC).

