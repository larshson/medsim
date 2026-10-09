"""
DeviceController — the glue between the BLE layer and the model/flags.

All GATT handlers (read_cb/write_cb in ble_server) land here. The controller
owns opcode parsing for the Command Control Point, encodes telemetry (IDD
Status, Heart Rate), and handles death attribution: who gets credited when the
patient dies, plus the bonus conditions for stealth/bolus kills.
"""

import struct
from . import config
from . import model as M


def _u16(data, off=0):
    return struct.unpack_from("<H", data, off)[0]


class DeviceController:
    def __init__(self, model, flags):
        self.model = model
        self.flags = flags
        self._submit_result = {}     # addr -> last submission result (bytes)
        self._last_actor = None      # addr that last raised the dose
        self._last_mode = None       # 'basal' | 'bolus'

    # ---- helpers --------------------------------------------------
    def _name(self, addr):
        return self.flags.name_for(addr)

    def _event(self, addr, kind, text):
        self.flags.add_event(self._name(addr), kind, text)

    # =============================================================
    # Standard reads (attributed)
    # =============================================================
    def read_model_number(self, addr):
        self.flags.award(addr, "F1")          # recon flag
        return config.DIS_MODEL.encode()

    def read_features(self, addr):
        self.flags.award(addr, "F2")          # read IDD Features
        # [flags:1][factory_max_centi:2][hard_ceiling_centi:2]
        feat = 0b00000111                     # basal|bolus|temp-basal supported
        return struct.pack("<BHH", feat,
                           int(M.FACTORY_MAX_BASAL * 100),
                           int(M.HARD_CEILING_BASAL * 100))

    # =============================================================
    # Telemetry encoding
    # =============================================================
    def status_payload(self) -> bytes:
        m = self.model
        flags = (
            (1 if m.therapy_active else 0)
            | (2 if m.maintenance_unlocked else 0)
            | (4 if m.alarms_silenced else 0)
            | (8 if m.occlusion else 0)
            | (16 if m.deceased else 0)
        )
        return struct.pack(
            "<BHHHH",
            flags,
            int(m.basal_rate * 100),
            int(m.max_basal_limit * 100),
            int(m.reservoir),
            int(m.glucose_display * 100),
        )

    def hr_measurement(self) -> bytes:
        # Heart Rate Measurement (0x2A37): flags=0x00 => uint8 BPM
        hr = max(0, min(255, int(round(self.model.heart_rate))))
        return bytes([0x00, hr])

    # =============================================================
    # Command Control Point (the attack surface)
    # =============================================================
    def handle_ccp(self, addr, data: bytes):
        if not data:
            return
        op = data[0]
        params = data[1:]
        m = self.model
        try:
            if op == config.OP_SET_BASAL:
                rate = _u16(params) / 100.0
                ok, req, clamped = m.set_basal(rate)
                if ok:
                    self._mark_actor(addr, "basal")
                    self.flags.award(addr, "F3")
                    self._event(addr, "cmd", f"set basal {clamped:.2f} U/h")
                else:
                    self.flags.award(addr, "F4")   # hit the interlock
                    self._event(addr, "block",
                                f"TRIED basal {req:.2f} -> CLAMPED to "
                                f"{clamped:.2f} U/h (interlock)")

            elif op == config.OP_SET_BOLUS:
                units = _u16(params) / 100.0
                ok, req, clamped = m.set_bolus(units)
                self._mark_actor(addr, "bolus")
                if ok:
                    self._event(addr, "cmd", f"gave bolus {clamped:.2f} U")
                else:
                    self._event(addr, "block",
                                f"TRIED bolus {req:.2f} -> CLAMPED to "
                                f"{clamped:.2f} U")

            elif op == config.OP_SET_MAX_BASAL:
                rate = _u16(params) / 100.0
                ok, newlim = m.set_max_basal(rate)
                if ok:
                    self.flags.award(addr, "F6")
                    self._event(addr, "danger",
                                f"CHANGED max basal limit -> {newlim:.2f} U/h")
                else:
                    self._event(addr, "block",
                                "denied: max basal limit requires maintenance mode")

            elif op == config.OP_MAINT_UNLOCK:
                if m.unlock_maintenance(bytes(params), config.MAINT_KEY):
                    self.flags.award(addr, "F5")
                    self._event(addr, "danger", "UNLOCKED maintenance mode")
                else:
                    self._event(addr, "block", "wrong maintenance key")

            elif op == config.OP_SILENCE_ALARM:
                on = bool(params and params[0])
                m.silence_alarms(on)
                self._event(addr, "danger" if on else "cmd",
                            "SILENCED the alarms" if on else "re-enabled the alarms")

            elif op == config.OP_STOP_THERAPY:
                m.stop_therapy()
                self._event(addr, "cmd", "stopped therapy")

            else:
                self._event(addr, "block", f"unknown opcode 0x{op:02x}")
        except (struct.error, IndexError):
            self._event(addr, "block", f"malformed command (op 0x{op:02x})")

    def _mark_actor(self, addr, mode):
        # only whoever RAISES the dose should be credited with the death
        self._last_actor = addr
        self._last_mode = mode

    # =============================================================
    # Death attribution (called by the main loop when the patient just died)
    # =============================================================
    def on_death(self):
        addr = self._last_actor
        m = self.model
        if addr is None:
            self.flags.add_event("unknown", "death",
                                 f"THE PATIENT DIED - {m.last_death_reason}")
            return
        self.flags.award(addr, "F7")
        if m.alarms_silenced:
            self.flags.award(addr, "F8")   # stealth kill
        if self._last_mode == "bolus":
            self.flags.award(addr, "F9")   # bolus kill
        self.flags.add_event(self._name(addr), "death",
                             f"KILLED THE PATIENT - {m.last_death_reason}")

    # =============================================================
    # CTF service
    # =============================================================
    def write_player_name(self, addr, data: bytes):
        try:
            name = data.decode("utf-8", "replace")
        except Exception:
            name = ""
        self.flags.set_name(addr, name)

    def read_player_name(self, addr):
        return self._name(addr).encode()

    def read_flags(self, addr):
        return self.flags.flags_text(addr)

    def submit_flag(self, addr, data: bytes):
        text = data.decode("utf-8", "replace")
        result = self.flags.submit(addr, text)
        self._submit_result[addr] = result
        return None   # WriteValue returns nothing

    def read_submit_result(self, addr):
        return self._submit_result.get(
            addr, b"Write a flag string here, then read for the result.")

    def read_score(self, addr):
        return self.flags.score_text(addr)
