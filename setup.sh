#!/usr/bin/env bash
# Setup on a Raspberry Pi (Raspberry Pi OS / Debian, BlueZ required).
set -euo pipefail
echo "== MedSim IP-800 setup =="

if ! command -v bluetoothctl >/dev/null; then
  echo "[*] Installing BlueZ…"
  sudo apt-get update && sudo apt-get install -y bluez python3-venv
fi

echo "[*] Creating venv + dependencies…"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# Disable the audio stack (PipeWire) on this headless BLE target.
# PipeWire registers a BLE MIDI GATT service whose characteristic requires
# encryption; D-Bus GATT clients (bleak, gratttool, bluetoothctl) trip on it
# during service resolution and every read/write then fails with ATT 0x0e.
# gatttool (raw ATT) is unaffected. Masking the audio stack removes the service
# so ALL tools work without pairing. See docs/FACILITATOR.md.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if systemctl --user list-unit-files pipewire.service >/dev/null 2>&1; then
  echo "[*] Masking the audio stack (PipeWire) — its BLE MIDI service breaks D-Bus GATT tools…"
  systemctl --user mask --now \
    pipewire.service pipewire.socket pipewire-pulse.service \
    pipewire-pulse.socket wireplumber.service 2>/dev/null || \
    echo "    (could not mask via --user; if you use D-Bus tools, see docs/FACILITATOR.md)"
else
  echo "[*] No PipeWire user units found — nothing to mask."
fi

echo
echo "Done. Start the pump with:"
echo "    ./.venv/bin/python -m src.main --autoreset 30"
echo
echo "Dashboard: http://<pi-ip>:8080/   (run kiosk with systemd/kiosk.sh)"
echo "NOTE: the BLE peripheral requires bluetoothd running and a free adapter."
echo "      Close other BT usage. Verify the profile with selftest/attack_client.py."
