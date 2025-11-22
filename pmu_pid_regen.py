# pmu_pid_regen.py — IO throttle PID version, patched
import uasyncio as asyncio
from pmu_throttle import set_throttle_voltage
from pmu_config import DATA
from time import ticks_ms, ticks_diff

KP = 0.012
KI = 0.0
KD = 0.0

TARGET_RPM = 2500

async def run(can, DATA, lcd=None):

    print("PID-REGEN: starting IO throttle PID loop")

    integral = 0
    last_err = 0
    last_ms = ticks_ms()

    while True:

        rpm = getattr(DATA, "velocity", 0)
        err = TARGET_RPM - rpm

        now = ticks_ms()
        dt = max(1, ticks_diff(now, last_ms))
        last_ms = now

        integral += err * dt
        deriv = (err - last_err) / dt
        last_err = err

        u = KP * err + KI * integral + KD * deriv

        volts = 4.0 + u
        volts = max(4.0, min(9.0, volts))

        await set_throttle_voltage(volts)
        print("PID: rpm=%d  V=%.2f" % (rpm, volts))

        await asyncio.sleep_ms(50)
