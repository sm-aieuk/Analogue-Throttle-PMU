from gen4_helpers_async import *
import uasyncio as asyncio
import time
from pmu_preactor_standalone import run_precharge
from gen4_helpers_async import sdo_read_u8, sdo_read_u16

LOG_T0 = time.ticks_ms()
def log(msg):
    t = time.ticks_diff(time.ticks_ms(), LOG_T0)
    print(f"[{t:08d} ms] {msg}")

CRANK_CFG = {
    "node_id": 1,
    "target_nm": 25.0,
    "max_nm":    30.0,
    "ramp_steps": 8,
    "step_ms":    150,
    "start_rpm":  1800,
    "monitor_ms": 200,
    "max_crank_ms": 6000,
    "sync_period_ms": 20,
}

def get_dc_bus(DATA, can):
    if getattr(DATA, "cap_v", 0) > 0:
        return DATA.cap_v
    if getattr(DATA, "dc_bus_v", 0) > 0:
        return DATA.dc_bus_v
    return getattr(can, "last_dc_link_v", 0)

async def nmt_start(can, node_id=1):
    try:
        can._can.send(bytes([0x81, node_id]), 0x000)
        log("NMT Reset-Node sent")
        await asyncio.sleep_ms(150)

        can._can.send(bytes([0x01, node_id]), 0x000)
        log("NMT Start-Node sent")
        await asyncio.sleep_ms(50)

        log("NMT OK")
        return True
    except Exception as e:
        log(f"NMT FAIL: {e}")
        return False

async def configure_torque_mode(can, node_id, logger=log):
    logger("CONFIG: torque mode")

    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0080)
    await asyncio.sleep_ms(40)

    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0006)
    await asyncio.sleep_ms(40)

    await can.sdo_write_u8(node_id, 0x3003, 0, 0)
    await asyncio.sleep_ms(20)

    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    await asyncio.sleep_ms(20)

    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0007)
    await asyncio.sleep_ms(40)

    await can.sdo_write_u16(node_id, 0x6040, 0, 0x000F)
    await asyncio.sleep_ms(40)

    # Wait op-enabled
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 2000:
        try:
            sw = await can.sdo_read_u16(node_id, 0x6041, 0)
            if (sw & 0x004F) == 0x004F:
                logger("CONFIG: OpEnabled")
                break
        except:
            pass
        await asyncio.sleep_ms(50)

    await can.sdo_write_u16(node_id, 0x6080, 0, 500)
    await asyncio.sleep_ms(40)
    logger("CONFIG DONE")

    return True

# ─────────────────────────────────────────────
# CRANK MAIN
# ─────────────────────────────────────────────
async def crank_main(can, DATA):
    cfg = CRANK_CFG
    node_id = cfg["node_id"]

    log("CRANK: sequence starting…")
    log("CRANK: calling precharge…")

    # PRECHARGE EXACTLY ONCE
    await run_precharge(DATA, can)

    DATA.dc_bus_v = get_dc_bus(DATA, can)

    log("CRANK: precharge complete")
    log(f"CRANK: Vdc post-precharge = {DATA.dc_bus_v}")

    # NMT RESET/START
    await nmt_start(can, node_id)
    await asyncio.sleep_ms(1500)

    ok = await configure_torque_mode(can, node_id, log)
    if not ok:
        log("CRANK: torque-mode config FAILED")
        return

    # Final op-enabled check
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 2000:
        try:
            sw = await can.sdo_read_u16(node_id, 0x6041, 0)
            if (sw & 0x004F) == 0x004F:
                break
        except: pass
        await asyncio.sleep_ms(50)

    log(f"CRANK: ramping to {cfg['target_nm']} Nm")

    target = cfg["target_nm"]
    step_nm = target / cfg["ramp_steps"]

    # Zero torque
    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    DATA.torque_cmd = 0.0
    await asyncio.sleep_ms(cfg["step_ms"])

    # Ramp
    for i in range(1, cfg["ramp_steps"]+1):
        nm = min(i * step_nm, target)
        await can.sdo_write_u16(node_id, 0x6071, 0, int(nm * 10))
        DATA.torque_cmd = nm
        await asyncio.sleep_ms(cfg["step_ms"])

    log("CRANK: holding torque…")
    start = time.ticks_ms()

    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)

        await can.sdo_write_u16(node_id, 0x6071, 0, int(target * 10))
        DATA.torque_cmd = target

        if elapsed >= cfg["max_crank_ms"]:
            log("CRANK: timeout")
            break

        if DATA.velocity >= cfg["start_rpm"]:
            log(f"CRANK: start detected at {DATA.velocity} rpm")
            break

        await asyncio.sleep_ms(cfg["sync_period_ms"])

    # Torque off
    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    DATA.torque_cmd = 0
    log("CRANK: torque zero; sequence done.")

async def run(can, DATA):
    return await crank_main(can, DATA)
