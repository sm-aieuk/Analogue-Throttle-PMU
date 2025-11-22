# test_throttle.py — updated for scaled Option-A throttle mapping
# This safely tests the PWM/DC converter output WITHOUT connecting to the Gen4.

import uasyncio as asyncio
from pmu_throttle import (
    Throttle,
    V_REGEN_MAX, V_REGEN_MIN,
    V_NEUTRAL,
    V_FWD_MIN, V_FWD_MAX
)
from pmu_inputs import CRANK_ENABLE

async def show(voltage, label):
    print("→ %-16s expected = %.2f V" % (label, voltage))
    await asyncio.sleep(5)

async def main():
    print("=== THROTTLE OUTPUT TEST (Scaled Option-A Map) ===")

    TH = Throttle()

    # Safety: disable crank-enable
    CRANK_ENABLE.low()

    # Neutral
    await TH.neutral()
    await show(V_NEUTRAL, "Neutral")

    # Forward min torque (0 Nm)
    await TH.forward_nm(0)
    await show(V_FWD_MIN, "Forward min")

    # Forward mid torque (15 Nm)
    await TH.forward_nm(15)
    v_mid = V_FWD_MIN + 0.5 * (V_FWD_MAX - V_FWD_MIN)
    await show(v_mid, "Forward mid")

    # Forward max torque (30 Nm)
    await TH.forward_nm(30)
    await show(V_FWD_MAX, "Forward max")

    # Back to neutral
    await TH.neutral()
    await show(V_NEUTRAL, "Neutral again")

    # Regen min (-0 Nm)
    await TH.regen_nm(0)
    await show(V_REGEN_MIN, "Regen min")

    # Regen mid torque (-25 Nm)
    await TH.regen_nm(-25)
    v_reg_mid = V_REGEN_MIN + 0.5 * (V_REGEN_MAX - V_REGEN_MIN)
    await show(v_reg_mid, "Regen mid")

    # Regen max torque (-50 Nm)
    await TH.regen_nm(-50)
    await show(V_REGEN_MAX, "Regen max")

    # Final neutral
    await TH.neutral()
    await show(V_NEUTRAL, "Neutral END")

    print("=== TEST COMPLETE ===")

asyncio.run(main())
