## -------------------------------------------------------------------------
# PMU External Precharge (ADS1115 HV measurement only)
# - Uses ADS1115 @ 0x49, differential AIN2–AIN3
# - Ratio threshold against configured nominal battery voltage
# - No CANopen dependencies
# - No DS402
## -------------------------------------------------------------------------

import uasyncio as asyncio
import time

from pmu_throttle import set_throttle_voltage

# ADS scaling
_LSB_V      = 0.000125   # ADS1115 gain=1
_VDIV_HV    = 54       # Calibrated HV divider ratio
_A_PER_V    = 125.0      # LF205 / AMC1311 current scaling



# Precharge control pins
try:
    from pyb import Pin
except ImportError:
    from machine import Pin

PIN_KEY  = Pin('Y1', Pin.OUT_PP)
PIN_PRE  = Pin('X1', Pin.OUT_PP)
PIN_MAIN = Pin('X2', Pin.OUT_PP)

for p in (PIN_KEY, PIN_PRE, PIN_MAIN):
    try: p.low()
    except: pass


# Config
CFG = {
    "startup_delay_ms": 2500,
    "close_sample_ms": 200,
    "max_close_ms":    8000,
    "ratio_floor_v":   12.0,
    "ratio_frac":      0.8,
    
}

try:
    from pmu_config import CONFIG
    CFG.update(CONFIG.get("PRECHARGE", {}))
except:
    pass


async def run(DATA, can, lcd=None):
    print("PRECHARGE: begin")


        # Set throttle to neutral
    try:
        await set_throttle_voltage(1.0)   # Set to keep Sevcon happy at startup
        print("Setting throttle to 4V at start")
    except Exception as e:
        print("PRECHARGE: couldn't set neutral throttle:", e)

    await asyncio.sleep_ms(1500)

    # Key on (LV enable to Sevcon)
    PIN_KEY.high()
    await asyncio.sleep_ms(CFG["startup_delay_ms"])

    # Precharge path
    PIN_PRE.high()
    print(" → precharge relay ON")

    vbatt_nom = DATA.batt_nominal_v
    floor_v   = CFG["ratio_floor_v"]
    ratio_req = CFG["ratio_frac"]
    t0        = time.ticks_ms()

    while time.ticks_diff(time.ticks_ms(), t0) < CFG["max_close_ms"]:
        # Use async ADCManager values
        vdc = DATA.battery_v     # from adc_manager.task()
        ratio = vdc / vbatt_nom if vbatt_nom > 1 else 0.0

        print("   Vdc=%.2f  ratio=%.3f" % (vdc, ratio))

        if vdc >= floor_v and ratio >= ratio_req:
            print(" → precharge OK, closing MAIN")
            PIN_MAIN.high()
            await asyncio.sleep_ms(150)
            PIN_PRE.low()
            DATA.precharge_done = True
            print("PRECHARGE COMPLETE\n")
            return

# Yield to allow UI, LCD, CAN tasks to run
        await asyncio.sleep_ms(CFG["close_sample_ms"])


    # Timeout
    print("⚠ PRECHARGE TIMEOUT")
    PIN_PRE.low()
    DATA.precharge_done = False
    print("PRECHARGE FAIL\n")


# Backwards compatibility wrapper
async def run_precharge(DATA, can, lcd=None):
    return await run(DATA, can, lcd)
