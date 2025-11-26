# pmu_crank_io.py — fully patched for async_can_dual.py
import uasyncio as asyncio
from time import ticks_ms, ticks_diff
from pmu_config import DATA
from pmu_throttle import set_throttle_voltage
from machine import Pin


# Y2 RUN pin (FS1 + FWD low)
PIN_RUN = Pin("Y2", Pin.OUT)
PIN_RUN.low()

CRANK_CFG = {
    "neutral_v": 4.0,
    "crank_v_start": 5.0,
    "crank_v_max": 7.0,
    "ramp_steps": 20,
    "ramp_delay_ms": 100,
    "rpm_start": 1500,
    "tpdo_wait_ms": 300,
    "tpdo_retries": 3,
}


async def run(DATA, can, lcd=None):

    print("CRANK(IO): sequence starting...")
    print("CRANK(IO): allowing Gen4 to boot (1.5s)...")
    await asyncio.sleep_ms(1500)

    # ------------------------------------------------------------------
    print("CRANK(IO): waiting for GEN4 PDO/heartbeat...")
    timeout = 3000
    start = ticks_ms()

    while True:
        if DATA.gen4_last_hb_ms != 0:
            print("CRANK(IO): GEN4 heartbeat detected.")
            break
        if ticks_diff(ticks_ms(), start) > timeout:
            print("CRANK(IO): WARNING - no GEN4 frames detected before crank!")
            break
        await asyncio.sleep_ms(10)

    # ------------------------------------------------------------------
    print("CRANK(IO): clearing CAN1 RX buffers...")
    try:
        while can.hwcan.any(0):
            can.hwcan.recv(0)
        while can.hwcan.any(1):
            can.hwcan.recv(1)
    except Exception as e:
        print("CRANK(IO): buffer clear skipped:", e)

    await asyncio.sleep_ms(20)

    # ------------------------------------------------------------------
    print("CRANK(IO): waiting for Sevcon to enter OP state...")
    timeout = 3000
    start = ticks_ms()

    while True:
        if DATA.gen4_last_hb_ms != 0:
            print("CRANK(IO): GEN4 OP heartbeat seen.")
            break
        if ticks_diff(ticks_ms(), start) > timeout:
            print("CRANK(IO): WARNING - no heartbeat during OP wait.")
            break
        await asyncio.sleep_ms(10)

    # ------------------------------------------------------------------
    print("CRANK(IO): waiting for PDOs to begin...")
    timeout = 2000
    start = ticks_ms()
    initial = DATA.gen4_last_pdo_ms

    while True:
        if DATA.gen4_last_pdo_ms != initial:
            print("CRANK(IO): first PDO received.")
            break
        if ticks_diff(ticks_ms(), start) > timeout:
            print("⚠ CRANK(IO): No PDOs yet - continuing anyway.")
            break
        await asyncio.sleep_ms(10)

    # ------------------------------------------------------------------
    print("CRANK(IO): TPDO2 optional check...")
    cfg = CRANK_CFG
    got_tpdo2 = False

    for i in range(cfg["tpdo_retries"]):
        print(f"  waiting for TPDO2... ({i+1}/{cfg['tpdo_retries']})")

        start = ticks_ms()
        initial = DATA.gen4_last_pdo_ms

        while True:
            if DATA.gen4_last_pdo_ms != initial:
                got_tpdo2 = True
                print("  TPDO2 detected.")
                break

            if ticks_diff(ticks_ms(), start) > cfg["tpdo_wait_ms"]:
                break

            await asyncio.sleep_ms(5)

        if got_tpdo2:
            break

    if not got_tpdo2:
        print("⚠ CRANK(IO): TPDO2 not received - normal at standstill.")

    # ------------------------------------------------------------------
    print("CRANK(IO): throttle = neutral (4.0 V)")
    await set_throttle_voltage(cfg["neutral_v"])
    await asyncio.sleep_ms(400)

    # ------------------------------------------------------------------
    print("CRANK(IO): RUN ENABLED (Y2 high → Sevcon FS1+FWD low)")
    PIN_RUN.high()
    await asyncio.sleep_ms(150)

    # ------------------------------------------------------------------
    print("CRANK(IO): ramping throttle to crank voltage...")

    v0 = cfg["crank_v_start"]
    v1 = cfg["crank_v_max"]
    steps = cfg["ramp_steps"]
    dv = (v1 - v0) / max(1, steps)

    await set_throttle_voltage(v0)
    await asyncio.sleep_ms(cfg["ramp_delay_ms"])

    for i in range(steps):
        v = v0 + dv * i
        await set_throttle_voltage(v)

        # <-- FIX: consistently use DATA.sevcon_rpm
        rpm = getattr(DATA, "sevcon_rpm", 0)

        print("  throttle = %.2f V   rpm=%d" % (v, rpm))

        if rpm >= cfg["rpm_start"]:
            print("CRANK(IO): engine start detected!")
            break

        await asyncio.sleep_ms(cfg["ramp_delay_ms"])

    # ------------------------------------------------------------------
    print("CRANK(IO): returning throttle to neutral")
    await set_throttle_voltage(cfg["neutral_v"])
    await asyncio.sleep_ms(200)

    PIN_RUN.low()
    print("CRANK(IO): sequence complete.")

