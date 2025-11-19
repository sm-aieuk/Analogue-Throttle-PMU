# pmu_pid_regen.py  –  regenerative charging control
import uasyncio as asyncio
from pmu_preactor_standalone import run as precharge_run
from pmu_preactor_gpio import set_mode, set_target
from pid import PID   # your existing simple PID class

CONFIG_PID = {
    "target_voltage": 52.0,
    "kp": 1.0,
    "ki": 0.02,
    "kd": 0.0,
    "interval_ms": 100,
    "min_torque": -5.0,
    "max_torque": -50.0,
}

async def run(can, D, lcd=None, keypoll=None):
    await precharge_run(can, D, lcd, keypoll, wait_for_user=False)


    await set_mode(can, "torque")
    await lcd.set_cursor(0, 0)
    await lcd.write_string("PID REGEN MODE   ")

    pid = PID(CONFIG_PID["kp"], CONFIG_PID["ki"], CONFIG_PID["kd"],
              setpoint=CONFIG_PID["target_voltage"])
    pid.output_limits = (CONFIG_PID["min_torque"], CONFIG_PID["max_torque"])

    while True:
        vb = getattr(D, "battery_v", 0.0)
        tq = pid(vb)
        await set_target(can, "torque", tq)
        await lcd.set_cursor(1, 0)
        await lcd.write_string("Vb:%5.1f Tq:%5.1f" % (vb, tq))
        if keypoll and keypoll().get("MENU"):
            break
        await asyncio.sleep_ms(CONFIG_PID["interval_ms"])

    await set_target(can, "torque", 0)
    await lcd.set_cursor(3, 0)
    await lcd.write_string("PID STOP MENU=EXIT")
