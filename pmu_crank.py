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
    "max_nm": 30.0,
    "ramp_steps": 8,
    "step_ms": 150,
    "start_rpm": 1800,
    "monitor_ms": 200,
    "max_crank_ms": 6000,
    "sync_period_ms": 20,
}

def get_dc_bus(DATA, can):
    # Prefer TPDO2 cap voltage
    if getattr(DATA, "cap_v", 0) > 0:
        return DATA.cap_v
    # fallback: 0x381 decoder if present
    if getattr(DATA, "dc_bus_v", 0) > 0:
        return DATA.dc_bus_v
    # fallback again to can.last_dc_link_v
    return getattr(can, "last_dc_link_v", 0)

async def get_statusword(can, node_id):
    try:
        return await can.sdo_read_u16(node_id, 0x6041, 0x00)
    except:
        return 0



async def sevcon_abort_preop_macro(can, node_id, logger=log):
    logger("SEVCON: aborting PreOp macro...")

    # Abort macro flag
    await can.sdo_write_u32(node_id, 0x5000, 3, 0x00000000)
    await asyncio.sleep_ms(20)

    # Force macro pointer to reset
    await can.sdo_write_u32(node_id, 0x5000, 1, 0x0000FFFF)
    await asyncio.sleep_ms(20)

    # Clear error logs (matching DVT behaviour)
    await can.sdo_write_u16(node_id, 0x10F1, 1, 0)
    await asyncio.sleep_ms(10)
    await can.sdo_write_u16(node_id, 0x10F1, 2, 0)
    await asyncio.sleep_ms(10)

    # Force STOP node (cleanest way to kill macro)
    can._can.send(b"\x80" + bytes([node_id]), 0x000)
    await asyncio.sleep_ms(100)

    logger("SEVCON: PreOp macro aborted")
    return True




async def nmt_start(can, node_id=1):
    """
    Match DVT behaviour:
    1) Send Reset Node (0x81)
    2) Wait 150ms for reboot
    3) Send Start Node (0x01)
    """
    try:
        # Reset Node
        can._can.send(bytes([0x81, node_id]), 0x000)
        log("NMT Reset-Node sent")
        await asyncio.sleep_ms(150)

        # Start Node
        can._can.send(bytes([0x01, node_id]), 0x000)
        log("NMT Start-Node sent")
        await asyncio.sleep_ms(50)

        log("NMT sequence OK")
        return True
    except Exception as e:
        log(f"NMT sequence FAILED: {e}")
        return False


async def send_pdo_torque(can, node_id, torque_nm):
    units = int(torque_nm * 10) & 0xFFFF
    lo = units & 0xFF
    hi = (units >> 8) & 0xFF
    frame = bytes([lo, hi, lo, hi])
    can._can.send(frame, 0x200 + node_id)
    can._can.send(b'', 0x80)     # SYNC


# ---------------------------------------------------------------------------
# Configure torque-mode exactly matching DVT behaviour
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Configure torque-mode exactly matching DVT behaviour + correct DS402 state wait
# ---------------------------------------------------------------------------

async def configure_torque_mode(can, node_id, logger=log):

    logger("CONFIG: torque-mode setup (DVT exact behaviour)")

    # 1) Fault reset  (0x80)
    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0080)
    await asyncio.sleep_ms(40)

    # 2) Shutdown     (0x06)
    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0006)
    await asyncio.sleep_ms(40)

    logger("CONFIG: skipping 6060 write (mode locked via DVT)")


    # ---------------------------------------------------------
    # CRITICAL FIX — SET DIRECTION BEFORE SWITCH-ON
    # 0x3003:00 = 0 → Forward
    # ---------------------------------------------------------
    logger("CONFIG: setting Direction = Forward (0x3003)")
    await can.sdo_write_u8(node_id, 0x3003, 0, 0)   # Forward
    await asyncio.sleep_ms(20)

    # CRITICAL: force torque = 0 before Switch-On
    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    await asyncio.sleep_ms(20)


    # 3) Switch On    (0x07)
    await can.sdo_write_u16(node_id, 0x6040, 0, 0x0007)
    await asyncio.sleep_ms(40)

    # 4) Enable Op    (0x0F)
    await can.sdo_write_u16(node_id, 0x6040, 0, 0x000F)
    await asyncio.sleep_ms(40)

    # ------------------------------------------------------------------
    # CRITICAL FIX:
    # Wait for Statusword bit pattern 0x004F ("Operation Enabled")
    # ------------------------------------------------------------------
    async def wait_op_enabled(timeout_ms=2000):
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            try:
                sw = await can.sdo_read_u16(node_id, 0x6041, 0)
                if (sw & 0x004F) == 0x004F:
                    logger(f"CONFIG: Operation Enabled (6041=0x{sw:04X})")
                    return True
            except:
                pass
            await asyncio.sleep_ms(50)
        return False

    ok = await wait_op_enabled()
    if not ok:
        logger("CONFIG: WARNING — drive never reached Operation Enabled")
        # Still proceed exactly as DVT does
        # (user asked to bypass strict checking)

    # 5) REQUIRED — set max motor speed (DVT value was 1000 rpm)
    logger("CONFIG: writing 0x6080 (Max motor speed) = 500 rpm")
    await can.sdo_write_u16(node_id, 0x6080, 0, 500)
    await asyncio.sleep_ms(40)

    logger("CONFIG: DVT sequence completed")
    return True


# ---------------------------------------------------------------------------
# CRANK MAIN
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# CRANK MAIN — with correct Operation Enabled wait before torque ramp
# ---------------------------------------------------------------------------
async def crank_main(can, DATA):
    cfg = CRANK_CFG
    node_id = cfg["node_id"]

    log("CRANK: sequence starting…")
    log("CRANK: calling precharge sequence…")

    await run_precharge(DATA, can)

    DATA.dc_bus_v = get_dc_bus(DATA, can)

    log("CRANK: precharge complete")
    log(f"CRANK: Vdc after precharge = {DATA.cap_v} V (from TPDO2)")

    # NMT reset + start
    await nmt_start(can, node_id)
    await asyncio.sleep_ms(1500)

    # Configure torque mode
    ok = await configure_torque_mode(can, node_id, log)
    if not ok:
        log("CRANK: torque-mode config FAILED — aborting")
        return

    # ---------------------------------------------------------
    # SECOND SAFETY CHECK — CONFIRM OPERATION ENABLED
    # ---------------------------------------------------------
    async def wait_op_enabled(timeout_ms=2000):
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            try:
                sw = await can.sdo_read_u16(node_id, 0x6041, 0)
                if (sw & 0x004F) == 0x004F:
                    return True
            except:
                pass
            await asyncio.sleep_ms(50)
        return False

    if not await wait_op_enabled():
        log("CRANK: ERROR — Drive never reached Operation Enabled after config.")
        return

    # ---------------------------------------------------------
    # TORQUE RAMP
    # ---------------------------------------------------------
    target = min(cfg["target_nm"], cfg["max_nm"])
    step_nm = target / cfg["ramp_steps"]

    log(f"CRANK: ramping torque to {target:.1f} Nm")

    # Set 0 Nm first
    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    DATA.torque_cmd = 0.0
    await asyncio.sleep_ms(cfg["step_ms"])

    # Ramp
    for i in range(1, cfg["ramp_steps"] + 1):
        nm = i * step_nm
        if nm > target:
            nm = target
        await can.sdo_write_u16(node_id, 0x6071, 0, int(nm * 10))
        DATA.torque_cmd = nm
        await asyncio.sleep_ms(cfg["step_ms"])

    log("CRANK: holding torque, watching rpm…")
    start = time.ticks_ms()

    # Hold torque
    while True:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, start)

        await can.sdo_write_u16(node_id, 0x6071, 0, int(target * 10))
        DATA.torque_cmd = target

        if elapsed >= cfg["max_crank_ms"]:
            log(f"CRANK: timeout after {elapsed} ms")
            break

        if DATA.velocity >= cfg["start_rpm"]:
            log(f"CRANK: start detected at rpm={DATA.velocity}")
            break

        await asyncio.sleep_ms(cfg["sync_period_ms"])

    # Torque off
    await can.sdo_write_u16(node_id, 0x6071, 0, 0)
    DATA.torque_cmd = 0.0
    log("CRANK: torque returned to 0")
    log("CRANK: sequence finished.")


async def run(can, DATA):
    return await crank_main(can, DATA)
