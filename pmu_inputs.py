# pmu_inputs.py — digital outputs for Sevcon control + throttle PWM
from machine import Pin

# ────────────────────────────────────────────────────────────
# Pin assignments (Pyboard)
# ────────────────────────────────────────────────────────────
CRANK_ENABLE_PIN = 'Y2'     # Drives FS1 + Forward together
PWM_THROTTLE_PIN = 'Y7'     # PWM throttle output (0–10 V converter)
REGEN_SELECT_PIN = None     # Disabled in PWM mode

# ────────────────────────────────────────────────────────────
# Outputs
# ────────────────────────────────────────────────────────────
CRANK_ENABLE = Pin(CRANK_ENABLE_PIN, Pin.OUT_PP)
CRANK_ENABLE.low()

# PWM pin is initialised by pmu_throttle.py
PWM_THROTTLE = None

# Regen select (optional, disabled now)
if REGEN_SELECT_PIN:
    REGEN_SELECT = Pin(REGEN_SELECT_PIN, Pin.OUT_PP)
    REGEN_SELECT.low()
else:
    REGEN_SELECT = None
