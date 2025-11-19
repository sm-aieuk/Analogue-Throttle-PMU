## ─────────────────────────────────────────────────────────────
# PMU PRECHARGE STANDALONE MODULE (FIXED FOR UNIFIED API)
# Provides run(DATA, can, lcd=None) as the official entry point
# Provides run_precharge() as backwards-compatible alias
# Internal implementation preserved exactly as before.
## ─────────────────────────────────────────────────────────────

import uasyncio as asyncio
import time
from machine import I2C
from ads1x15 import ADS1115

from async_can_dual import (
    sdo_write_u8,
    sdo_read_u8,
    sdo_read_u16,
    sdo_read_u32,
)



# ─────────────────────────────────────────────
# ADC setup
# ─────────────────────────────────────────────

_ads49 = None
_ads48 = None
_VDIV_BATT = 53.5     # true divider ratio (~62 V battery ≈ 1.17 V ADC)
_LSB_V = 0.000125     # ADS1115 gain = 1 → 125 µV/bit
_A_PER_V = 125.0      # LEM LF205-S/SP3 + 16 Ω + AMC1311 ≈ 8 mV/A → 125 A/V

def _init_ads_if_needed():
    global _ads49, _ads48
    if not _ads49 or not _ads48:
        try:
            i2c = I2C(1, freq=400000)
            _ads49 = ADS1115(i2c, address=0x49, gain=1)
            _ads48 = ADS1115(i2c, address=0x48, gain=1)
        except Exception as e:
            print("⚠️ ADS init failed:", e)
            _ads49 = _ads48 = None

def _read_vbat_fallback():
    """Battery voltage via ADS1115 @ 0x49 (AIN2–AIN3 diff)."""
    _init_ads_if_needed()
    if not _ads49:
        return None
    try:
        raw = _ads49.read(2, 3)
        v_adc = raw * _LSB_V
        return v_adc * _VDIV_BATT
    except Exception as e:
        print("⚠️ ADS battery read failed:", e)
        return None

def _read_currents_fallback():
    """Return (I_load, I_inv) currents via LF205-S/SP3 sensors."""
    _init_ads_if_needed()
    if not _ads48:
        return (None, None)
    try:
        v_load = _ads48.read(0) * _LSB_V
        v_chg  = _ads48.read(2) * _LSB_V
        return v_load * _A_PER_V, v_chg * _A_PER_V
    except Exception as e:
        print("⚠️ ADS current read failed:", e)
        return (None, None)

def _read_vdc_fallback(can):
    """Return last known DC-link voltage if available, else 0."""
    try:
        if hasattr(can, "last_dc_link_v"):
            return can.last_dc_link_v
        if hasattr(can, "DATA") and getattr(can.DATA, "dc_bus_v", 0) > 0:
            return can.DATA.dc_bus_v
        return 0.0
    except Exception as e:
        print("⚠️ _read_vdc_fallback failed:", e)
        return 0.0

def _get_measurements(DATA=None, can=None):
    """
    Unified measurement access for precharge sequence.
    Returns (Vbatt, Vdc_link, Iload, Ichg)
    NOTE: NO SDO HERE. TPDO only.
    """
    # 1️⃣ Battery voltage (Pyboard ADC)
    try:
        vb = (DATA and getattr(DATA, "battery_v", 0) > 1.0 and DATA.battery_v) \
             or _read_vbat_fallback()
    except:
        vb = None

    # 2️⃣ DC-link voltage
    # Only TPDO2 allowed here
    try:
        vc = DATA.cap_v if (DATA and hasattr(DATA, "cap_v") and DATA.cap_v > 0) else 0
    except:
        vc = 0

    # 3️⃣ Currents
    try:
        if DATA and hasattr(DATA, "load_i") and hasattr(DATA, "charge_i"):
            I_load = DATA.load_i
            I_chg  = DATA.charge_i
        else:
            I_load, I_chg = _read_currents_fallback()
    except:
        I_load, I_chg = (None, None)

    return vb, vc, I_load, I_chg

# ─────────────────────────────────────────────
# Pyboard pins
# ─────────────────────────────────────────────
try:
    from pyb import Pin
except ImportError:
    from machine import Pin

PIN_KEY  = Pin('Y1', Pin.OUT_PP)
PIN_PRE  = Pin('X1', Pin.OUT_PP)
PIN_MAIN = Pin('X2', Pin.OUT_PP)

for p in (PIN_KEY, PIN_PRE, PIN_MAIN):
    try:
        p.low()
    except Exception:
        pass

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
CFG = {
    "startup_delay_ms": 2500,
    "wake_sample_ms": 180,
    "close_sample_ms": 190,
    "max_wake_ms": 2000,
    "max_close_ms": 8000,
    "wake_abs_min_v": 10.0,
    "wake_frac_of_vb": 0.60,
    "ratio_floor_v": 12.0,
    "ratio_frac_of_vb": 0.92,
    "vbat_scale": 100.0,
}
try:
    from pmu_config import CONFIG
    CFG.update(CONFIG.get("PRECHARGE", {}))
except Exception:
    pass

# ─────────────────────────────────────────────
#  LCD helper
# ─────────────────────────────────────────────
async def _lcd20(lcd, row, text):
    if not lcd:
        return
    try:
        lcd.set_cursor(row, 0)
        lcd.write_string((text + " " * 20)[:20])
    except Exception:
        pass

# ─────────────────────────────────────────────
# INTERNAL IMPLEMENTATION
# (kept exactly as your original – signature preserved internally)
# ─────────────────────────────────────────────
async def _run_standalone(can, lcd=None, DATA=None):
    # ------------------------------------------------------------
    # FIXED-TIME PRECHARGE (External precharge using 47Ω resistor)
    # ------------------------------------------------------------
    print("PRECHARGE: starting external timed precharge")

    # Turn KEY relay ON (power up Sevcon low-voltage electronics)
    try:
        PIN_KEY.high()
    except Exception:
        pass

    delay_s = CFG.get("startup_delay_ms", 2500) / 1000.0
    print(f" → Key relay ON; wait {delay_s:.1f}s for inverter rails")
    await asyncio.sleep_ms(int(delay_s * 1000))

    # Enable precharge relay
    print(" → Precharge relay ON; charging DC-bus through 47Ω resistor")
    try:
        PIN_PRE.high()
    except Exception:
        pass

    # SAFE FIXED PRECHARGE INTERVAL
    PRECHARGE_TIME_MS = CFG.get("fixed_precharge_ms", 3000)
    print(f" → Charging capacitors for {PRECHARGE_TIME_MS} ms")
    await asyncio.sleep_ms(PRECHARGE_TIME_MS)

    # Close MAIN contactor
    print(" → Closing MAIN contactor")
    try:
        PIN_MAIN.high()
    except Exception:
        pass
    await asyncio.sleep_ms(150)

    # Disable precharge relay
    try:
        PIN_PRE.low()
    except Exception:
        pass

    DATA.precharge_done = True
    print("PRECHARGE: complete → returning to caller\n")




# ─────────────────────────────────────────────
# PUBLIC API — OFFICIAL ENTRY POINT
# ─────────────────────────────────────────────
async def run(DATA, can, lcd=None):
    """
    Unified precharge signature expected by:
    - main.py
    - pmu_crank.py
    - pmu_ui.py
    - pmu_controller
    """
    return await _run_standalone(can, lcd=lcd, DATA=DATA)

# Backwards-compatible alias
async def run_precharge(DATA, can, lcd=None):
    return await run(DATA, can, lcd=lcd)

