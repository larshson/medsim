"""
Central configuration for MedSim IP-800 — UUIDs, constants, flags.

The GATT profile is based on a SIMPLIFIED subset of the Bluetooth SIG
Insulin Delivery Service (0x183A). We implement:
  - IDD Features (0x2B23)          READ
  - IDD Status   (0x2B22)          READ + NOTIFY
  - IDD Command Control Point      WRITE  (0x2B25, simplified opcode framing)

Full IDS uses per-command counters + E2E-CRC. We deliberately omit that —
see docs/PROFILE.md. The attack surface is the Command Control Point.

On top of this there are standard services for authenticity (Device
Information, Battery, Heart Rate) and a custom CTF service for player
identity, flag retrieval, submission and scoring.
"""

# ---------------------------------------------------------------------------
# UUID helpers
# ---------------------------------------------------------------------------

import os


def uuid16(short: int) -> str:
    """Expand a 16-bit SIG UUID to its full 128-bit form."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


# ---------------------------------------------------------------------------
# Standard services (READ/NOTIFY — authenticity + recon)
# ---------------------------------------------------------------------------

DEVICE_NAME = "MedSim IP-800"

# Device Information Service
DIS_SERVICE            = uuid16(0x180A)
CHAR_MANUFACTURER      = uuid16(0x2A29)   # Manufacturer Name String
CHAR_MODEL_NUMBER      = uuid16(0x2A24)   # Model Number String
CHAR_SERIAL_NUMBER     = uuid16(0x2A25)   # Serial Number String
CHAR_FIRMWARE_REV      = uuid16(0x2A26)   # Firmware Revision String (hides the maint key)
CHAR_HARDWARE_REV      = uuid16(0x2A27)   # Hardware Revision String

DIS_MANUFACTURER = "MedSim Labs AB"
DIS_MODEL        = "IP-800"
DIS_SERIAL       = "IP800-2024-000731"
DIS_HARDWARE     = "Rev C"
# Hint: the maintenance key (4 bytes) is hidden in the firmware string. The
# participant reads DIS -> finds DEADBEEF -> uses it in CCP opcode 0x04.
MAINT_KEY = bytes.fromhex("DEADBEEF")
DIS_FIRMWARE = f"FW 2.3.1 (maint-key:{MAINT_KEY.hex().upper()})"

# Battery Service
BATTERY_SERVICE        = uuid16(0x180F)
CHAR_BATTERY_LEVEL     = uuid16(0x2A19)   # uint8 percent

# Heart Rate Service (patient pulse as telemetry)
HR_SERVICE             = uuid16(0x180D)
CHAR_HR_MEASUREMENT    = uuid16(0x2A37)   # notify

# ---------------------------------------------------------------------------
# Insulin Delivery Service (0x183A) — simplified
# ---------------------------------------------------------------------------

IDS_SERVICE            = uuid16(0x183A)
CHAR_IDD_FEATURES      = uuid16(0x2B23)   # read
CHAR_IDD_STATUS        = uuid16(0x2B22)   # read + notify
CHAR_IDD_CCP           = uuid16(0x2B25)   # write  (Command Control Point)

# CCP opcodes (simplified framing: [opcode:1][params...])
OP_SET_BASAL      = 0x01   # + uint16 LE, centi-units/h (U/h * 100)
OP_SET_BOLUS      = 0x02   # + uint16 LE, centi-units    (U   * 100)
OP_SET_MAX_BASAL  = 0x03   # + uint16 LE, centi-units/h  (PROTECTED: needs maint unlock)
OP_MAINT_UNLOCK   = 0x04   # + 4-byte key
OP_SILENCE_ALARM  = 0x05   # + 1 byte (1 = silence)
OP_STOP_THERAPY   = 0x06   # (no params) emergency stop

# ---------------------------------------------------------------------------
# CTF service (custom) — identity, flags, submission, scoring
# ---------------------------------------------------------------------------

def ctf_uuid(n: int) -> str:
    # Stable custom UUID block, reads as "MEDS IM..".
    return f"4d454453-494d-4d00-0000-{n:012x}"

CTF_SERVICE            = ctf_uuid(1)
CHAR_PLAYER_NAME       = ctf_uuid(2)   # write + read : set your callsign/handle
CHAR_FLAG             = ctf_uuid(3)    # read        : returns YOUR earned flags
CHAR_SUBMIT_FLAG       = ctf_uuid(4)   # write       : submit a flag string
CHAR_SCORE             = ctf_uuid(5)   # read        : "Score: n/total" (per player)

# ---------------------------------------------------------------------------
# Flag definitions
# ---------------------------------------------------------------------------
# id, slug (goes into the flag string), title (shown on the scoreboard).
# The order is the intended difficulty ramp.

# The title is the OBJECTIVE (what to do) — stated clearly, but never the method
# (which UUID, which opcode, the unlock code or the lethal dose). These titles
# are shown on the projector and mirror the objectives list in docs/PROFILE.md.
FLAGS = [
    ("F1", "recon-model",      "Read the device's Model Number"),
    ("F2", "read-features",    "Read the pump's IDD Features"),
    ("F3", "basal-legal",      "Set a basal rate within the safe limit"),
    ("F4", "hit-interlock",    "Attempt a dose above the safety limit (trip the interlock)"),
    ("F5", "maint-unlock",     "Unlock maintenance mode"),
    ("F6", "raise-limit",      "Raise or disable the maximum basal limit"),
    ("F7", "overdose-kill",    "Drive the patient into a fatal overdose"),
    ("F8", "stealth-kill",     "Kill the patient with the alarms silenced"),
    ("F9", "bolus-kill",       "Kill the patient with a single bolus"),
]

FLAG_IDS = [f[0] for f in FLAGS]
FLAG_TOTAL = len(FLAGS)

# Salt secret to make flag strings unique per player. Change it if you like.
FLAG_SECRET = "medsim-ip800-workshop-2026"
FLAG_PREFIX = "MEDSIM"

# ---------------------------------------------------------------------------
# Death sound (played locally on the Pi via ALSA when the patient dies)
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUND_FILE = os.path.join(_REPO_ROOT, "assets", "flatline.wav")
# ALSA device. A name-based spec is stable across reboots (card numbers are
# not). The Pi's 3.5mm jack is "Headphones"; for HDMI audio use e.g.
# "plughw:CARD=vc4hdmi0,DEV=0". Overridable with --sound-device.
SOUND_DEVICE_DEFAULT = "plughw:CARD=Headphones,DEV=0"
