"""
Physiological model for MedSim IP-800.

Plasma insulin follows the basal rate with a time constant; a bolus gives a
direct impulse. Blood glucose has its own turnover with a stable equilibrium
that insulin drives down:

  plasma insulin I:  dI/dt = (I_target - I)/TAU_I     (+ bolus impulse)
                     I_target = basal rate (U/h) while therapy is active, else 0
  blood glucose  G:  dG/dt = P - (KG + SI*I)*G        => G_eq = P / (KG + SI*I)

Tuned so that:
  * factory basal 1.0 U/h  -> G ~ 5.5 mmol/L (green zone)
  * factory limit 3.0      -> G ~ 3.3 (HYPO WARNING but survivable) => interlock protects
  * ~9-10 U/h (after the limit is raised) -> G < 1.5 => death
  * a large bolus          -> fast insulin spike -> crash
Effects land over ~1-2 min so the gauges have time to swing through amber/red.
The constants are easy to tune live.
"""

import math
import random
import time
from dataclasses import dataclass, field

# --- tunable constants ----------------------------------------------------
TAU_I = 40.0          # insulin time constant toward the basal target (seconds)
BOLUS_GAIN = 0.60     # how much 1 U of bolus raises plasma insulin (impulse)
P_GLU = 0.066         # hepatic glucose production
KG    = 0.008         # insulin-independent glucose clearance
SI    = 0.004         # insulin sensitivity (insulin-dependent clearance)
# => G_eq = P/(KG+SI*I):  I=1 ->5.5,  I=3 ->3.3,  I=9 ->1.5,  I=13 ->1.1

FACTORY_BASAL      = 1.00   # U/h  starting dose
FACTORY_MAX_BASAL  = 3.00   # U/h  factory safety limit
HARD_CEILING_BASAL = 25.0   # U/h  absolute pump maximum (even after unlock)
RESERVOIR_START    = 300.0  # units in the reservoir

# glucose thresholds (mmol/L)
G_NORMAL_LOW   = 4.0
G_HYPER_HIGH   = 8.0
G_WARN_LOW     = 3.0
G_CRIT_LOW     = 2.0
G_DEATH        = 1.5   # <= this => the patient dies (latched)

STATUS_NORMAL   = "NORMAL"
STATUS_HYPER    = "HYPERGLYCEMIA"    # too little insulin / ineffective therapy
STATUS_WARNING  = "HYPO WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_DECEASED = "DECEASED"

# --- idle physiological variability (cosmetic) ----------------------------
# The clean model reaches a dead-still equilibrium in normal mode, which looks
# lifeless on the projector. We overlay a smooth, bounded Ornstein-Uhlenbeck
# wander so the gauges "breathe" within the green zone. This is DISPLAY-ONLY:
# death, zones and flags are computed from the clean state, never the wander.
# Each entry: (tau_seconds, sigma, clamp) — larger tau = slower drift.
NOISE = {
    "hr":   (15.0, 0.47,  3.0),   # slow, gentle ~ +/-2 bpm (resting, not fluttery)
    "spo2": (8.0,  0.35,  2.0),   # ~ +/-0.7 %
    "glu":  (10.0, 0.08,  0.40),  # ~ +/-0.18 mmol/L
    "ins":  (8.0,  0.04,  0.15),  # ~ +/-0.08 U
}
HR_REST = 75.0   # resting heart-rate centre (bpm); wander makes it ~73-77


def _ou_step(x, dt, tau, sigma, clamp):
    """One step of a mean-reverting (toward 0) Ornstein-Uhlenbeck process."""
    x += (-x / tau) * dt + sigma * math.sqrt(dt) * random.gauss(0.0, 1.0)
    return max(-clamp, min(clamp, x))


@dataclass
class PumpModel:
    # --- pump settings (shared, global device) ---
    basal_rate: float = FACTORY_BASAL          # U/h
    max_basal_limit: float = FACTORY_MAX_BASAL # U/h
    maintenance_unlocked: bool = False
    alarms_silenced: bool = False
    therapy_active: bool = True
    reservoir: float = RESERVOIR_START         # units left

    # --- physiological state (clean; drives status/death) ---
    plasma_insulin: float = FACTORY_BASAL      # starts at equilibrium (= basal)
    glucose: float = 5.5                        # mmol/L
    heart_rate: float = HR_REST
    spo2: float = 98.0

    # --- display values (clean + cosmetic wander; reported to gauges/BLE) ---
    glucose_display: float = 5.5
    insulin_display: float = FACTORY_BASAL

    # --- idle variability state (Ornstein-Uhlenbeck, mean 0) ---
    _n_hr: float = 0.0
    _n_spo2: float = 0.0
    _n_glu: float = 0.0
    _n_ins: float = 0.0

    # --- derived ---
    status: str = STATUS_NORMAL
    occlusion: bool = False
    last_death_reason: str = ""

    # internal bookkeeping
    _pending_bolus: float = 0.0     # units to inject on the next step
    _deceased: bool = False
    _last_step: float = field(default_factory=time.monotonic)

    # ---------------------------------------------------------------
    # Commands (called from the BLE layer). Return info tuples.
    # ---------------------------------------------------------------
    def set_basal(self, rate_uph: float):
        """Set the basal rate. Clamped to the current max limit.
        Returns (ok, requested, clamped) where ok=False if clamped."""
        requested = max(0.0, rate_uph)
        clamped = min(requested, self.max_basal_limit)
        self.basal_rate = clamped
        blocked = requested > self.max_basal_limit + 1e-6
        return (not blocked, requested, clamped)

    def set_bolus(self, units: float):
        """Queue a bolus. Clamped to a bolus cap (max limit * 2)."""
        requested = max(0.0, units)
        bolus_cap = self.max_basal_limit * 2.0
        clamped = min(requested, bolus_cap)
        self._pending_bolus += clamped
        blocked = requested > bolus_cap + 1e-6
        return (not blocked, requested, clamped)

    def set_max_basal(self, rate_uph: float):
        """PROTECTED: raise/lower the safety limit. Requires maintenance unlock."""
        if not self.maintenance_unlocked:
            return (False, self.max_basal_limit)
        self.max_basal_limit = max(0.0, min(rate_uph, HARD_CEILING_BASAL))
        return (True, self.max_basal_limit)

    def unlock_maintenance(self, key: bytes, correct_key: bytes):
        if key == correct_key:
            self.maintenance_unlocked = True
            return True
        return False

    def silence_alarms(self, on: bool):
        self.alarms_silenced = bool(on)

    def stop_therapy(self):
        self.therapy_active = False
        self.basal_rate = 0.0

    # ---------------------------------------------------------------
    def revive(self):
        """Reset device + patient to factory state."""
        self.basal_rate = FACTORY_BASAL
        self.max_basal_limit = FACTORY_MAX_BASAL
        self.maintenance_unlocked = False
        self.alarms_silenced = False
        self.therapy_active = True
        self.reservoir = RESERVOIR_START
        self.plasma_insulin = FACTORY_BASAL
        self.glucose = 5.5
        self.glucose_display = 5.5
        self.insulin_display = FACTORY_BASAL
        self.heart_rate = HR_REST
        self.spo2 = 98.0
        self._n_hr = self._n_spo2 = self._n_glu = self._n_ins = 0.0
        self.occlusion = False
        self._pending_bolus = 0.0
        self._deceased = False
        self.last_death_reason = ""
        self.status = STATUS_NORMAL

    # ---------------------------------------------------------------
    def step(self, dt: float):
        """Advance the model by dt seconds. Returns True if the patient
        JUST died in this step (for event/flag triggering)."""
        if self._deceased:
            self.status = STATUS_DECEASED
            return False

        # reservoir draw (basal + bolus, in units)
        drawn = 0.0
        if self.therapy_active:
            drawn += self.basal_rate * dt / 3600.0
        drawn += self._pending_bolus
        if self.reservoir <= 0.0:
            self.occlusion = True
            self._pending_bolus = 0.0
            i_target = 0.0            # empty reservoir => no delivery
        else:
            self.reservoir = max(0.0, self.reservoir - drawn)
            i_target = self.basal_rate if self.therapy_active else 0.0

        # plasma insulin toward the basal target + direct bolus impulse
        self.plasma_insulin += (i_target - self.plasma_insulin) * (dt / TAU_I)
        self.plasma_insulin += self._pending_bolus * BOLUS_GAIN
        self.plasma_insulin = max(0.0, self.plasma_insulin)
        self._pending_bolus = 0.0

        # glucose with a stable equilibrium G_eq = P/(KG+SI*I)
        dG = (P_GLU - (KG + SI * self.plasma_insulin) * self.glucose) * dt
        self.glucose = max(0.0, self.glucose + dG)

        # cosmetic idle wander (mean-zero OU per channel), updated before vitals
        self._n_hr = _ou_step(self._n_hr, dt, *NOISE["hr"])
        self._n_spo2 = _ou_step(self._n_spo2, dt, *NOISE["spo2"])
        self._n_glu = _ou_step(self._n_glu, dt, *NOISE["glu"])
        self._n_ins = _ou_step(self._n_ins, dt, *NOISE["ins"])
        self.glucose_display = max(0.0, self.glucose + self._n_glu)
        self.insulin_display = max(0.0, self.plasma_insulin + self._n_ins)

        self._update_vitals()
        just_died = self._update_status()
        return just_died

    # ---------------------------------------------------------------
    def _update_vitals(self):
        g = self.glucose
        if g >= G_WARN_LOW:
            base_hr = HR_REST + max(0.0, (5.5 - g)) * 4
        elif g >= G_CRIT_LOW:
            base_hr = HR_REST + 20 + (G_WARN_LOW - g) * 25   # tachycardia
        else:
            base_hr = max(20.0, 140 - (G_CRIT_LOW - g) * 60)  # bradycardia -> collapse
        base_spo2 = 98.0 if g >= G_CRIT_LOW else max(60.0, 98 - (G_CRIT_LOW - g) * 30)
        # overlay the cosmetic wander, then low-pass for smoothness
        hr = base_hr + self._n_hr
        spo2 = min(100.0, base_spo2 + self._n_spo2)
        self.heart_rate += (hr - self.heart_rate) * 0.25
        self.spo2 += (spo2 - self.spo2) * 0.25

    def _update_status(self):
        g = self.glucose
        if g <= G_DEATH:
            self._deceased = True
            self.status = STATUS_DECEASED
            self.last_death_reason = (
                "insulin overdose -> severe hypoglycemia" if self.plasma_insulin > 3.0
                else "hypoglycemia"
            )
            return True
        if g < G_CRIT_LOW:
            self.status = STATUS_CRITICAL
        elif g < G_NORMAL_LOW:
            self.status = STATUS_WARNING     # 2.0 - 4.0 mmol/L => hypo warning
        elif g >= G_HYPER_HIGH:
            self.status = STATUS_HYPER
        else:
            self.status = STATUS_NORMAL
        return False

    # ---------------------------------------------------------------
    @property
    def deceased(self) -> bool:
        return self._deceased

    def snapshot(self) -> dict:
        return {
            "basal_rate": round(self.basal_rate, 2),
            "max_basal_limit": round(self.max_basal_limit, 2),
            "maintenance_unlocked": self.maintenance_unlocked,
            "alarms_silenced": self.alarms_silenced,
            "therapy_active": self.therapy_active,
            "reservoir": round(self.reservoir, 1),
            "plasma_insulin": round(self.insulin_display, 2),
            "glucose": round(self.glucose_display, 2),
            "heart_rate": round(self.heart_rate, 0),
            "spo2": round(self.spo2, 0),
            "status": self.status,
            "occlusion": self.occlusion,
            "deceased": self._deceased,
            "death_reason": self.last_death_reason,
            "factory_max": FACTORY_MAX_BASAL,
            "hard_ceiling": HARD_CEILING_BASAL,
            "g_zones": {
                "normal_low": G_NORMAL_LOW, "hyper_high": G_HYPER_HIGH,
                "warn_low": G_WARN_LOW, "crit_low": G_CRIT_LOW, "death": G_DEATH,
            },
        }
