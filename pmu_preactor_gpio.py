# pmu_preactor_gpio.py – External precharge & bring-up for Sevcon Gen4
# --------------------------------------------------------------------
import uasyncio as asyncio
import time
from machine import Pin
from adc_manager import ADCManager
from async_can_dual import AsyncCANPort

# ───────────────────────────────────────────────────────────────
# Provide a benign CONFIG so any legacy imports don't explode.
CONFIG = {}

def dbg(msg):
    try:
        print(msg)
    except:
        pass

NODE_ID = 1

# ───────────────────────────────────────────────────────────────
# Relay configuration
# ───────────────────────────────────────────────────────────────
PIN_KEY  = Pin("Y1", Pin.OUT, value=0)
PIN_PCHG = Pin("X1", Pin.OUT, value=0)
PIN_MAIN = Pin("X2", Pin.OUT, value=0)

# ───────────────────────────────────────────────────────────────
# SDO utilities
# ───────────────────────────────────────────────────────────────
async def sdo_write_u16(can, nid, idx, sub, val):
    data = bytes([0x2B, idx & 0xFF, idx >> 8, sub, val & 0xFF, val >> 8, 0, 0])
    await can.send_async(0x600 + nid, data)
    await asyncio.sleep_ms(5)

async def sdo_write_i32(can, nid, idx, sub, val):
    data = bytes([0x23, idx & 0xFF, idx >> 8, sub,
                  val & 0xFF, (val >> 8) & 0xFF,
                  (val >> 16) & 0xFF, (val >> 24) & 0xFF])
    await can.send_async(0x600 + nid, data)
    await asyncio.sleep_ms(5)

async def sdo_write_u8(can, nid, idx, sub, val):
    """Used for mode select (0x6060)."""
    data = bytearray([0x2F, idx & 0xFF, idx >> 8, sub,
                      val & 0xFF, 0x00, 0x00, 0x00])
    await can.sdo_request(nid, data)
    await asyncio.sleep_ms(5)

async def sdo_read_u32(can, nid, idx, sub, timeout_ms=300):
    req = bytes([0x40, idx & 0xFF, idx >> 8, sub, 0, 0, 0, 0])
    await can.send_async(0x600 + nid, req)
    t0 = time.ticks_ms()
    while True:
        msg = await can.recv()
        if msg["id"] == 0x580 + nid:
            b = msg["data"]
            return b[4] | (b[5] << 8) | (b[6] << 16) | (b[7] << 24)
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            raise OSError("SDO read timeout 0x%04X:%02X" % (idx, sub))

# ───────────────────────────────────────────────────────────────
# DS402 helpers
# ───────────────────────────────────────────────────────────────
async def ds402_shutdown(can):  await sdo_write_u16(can, NODE_ID, 0x6040, 0, 0x0006)
async def ds402_switch_on(can): await sdo_write_u16(can, NODE_ID, 0x6040, 0, 0x0007)
async def ds402_enable(can):    await sdo_write_u16(can, NODE_ID, 0x6040, 0, 0x000F)
async def ds402_fault_reset(can):
    """Reset DS402 fault by writing controlword 0x0080, wait a short time."""
    try:
        await sdo_write_u16(can, 1, 0x6040, 0x00, 0x0080)  # Fault Reset command
        await asyncio.sleep_ms(100)
        print("→ DS402 fault reset issued")
    except Exception as e:
        print("⚠️ DS402 fault reset failed:", e)

async def ds402_get_state(can):
    """
    Read DS402 statusword (0x6041) and return a string describing the current state.
    """
    try:
        val = await sdo_read_u16(can, 1, 0x6041, 0x00)
    except Exception as e:
        print("⚠️ DS402 get_state failed:", e)
        return "Unknown"

    # Decode according to CiA-402 bitmask
    if val & 0x004F == 0x0000:
        return "Not ready to switch on"
    elif val & 0x004F == 0x0040:
        return "Switch on disabled"
    elif val & 0x006F == 0x0021:
        return "Ready to switch on"
    elif val & 0x006F == 0x0023:
        return "Switched on"
    elif val & 0x006F == 0x0027:
        return "Operation enabled"
    elif val & 0x004F == 0x0007:
        return "Quick stop active"
    elif val & 0x004F == 0x000F:
        return "Fault reaction active"
    elif val & 0x004F == 0x0008:
        return "Fault"
    else:
        return "Unknown"

async def ensure_nmt_operational(can, node_id=1):
    """
    Ensure that the target node is in NMT Operational state.
    Sends 'Start Remote Node' (0x01) and waits briefly.
    """
    try:
        # NMT frame: COB-ID 0x000, Data = [command, node_id]
        # Command 0x01 = Start Remote Node
        msg = (0x000, bytearray([0x01, node_id]))
        can.send(*msg)
        print(f"→ Sent NMT Start for node {node_id}")
        await asyncio.sleep_ms(100)
    except Exception as e:
        print("⚠️ ensure_nmt_operational failed:", e)

async def write_tpdo_map(can, pdo_index, mappings):
    """
    Configure a TPDO mapping object.
    Example: await write_tpdo_map(can, 1, [(0x606C, 0x00, 32), (0x6077, 0x00, 16)])
    """
    try:
        # Disable PDO mapping before reconfiguring
        await sdo_write_u8(can, 1, 0x1A00 + (pdo_index - 1), 0x00, 0x00)

        # Write each mapping (index, subindex, bitlength)
        for i, (idx, sub, bits) in enumerate(mappings, start=1):
            entry = (idx << 16) | (sub << 8) | bits
            await sdo_write_u32(can, 1, 0x1A00 + (pdo_index - 1), i, entry)

        # Write the number of active mappings
        await sdo_write_u8(can, 1, 0x1A00 + (pdo_index - 1), 0x00, len(mappings))
        print(f"→ TPDO{pdo_index} mapping updated: {len(mappings)} entries")

    except Exception as e:
        print(f"⚠️ write_tpdo_map failed for TPDO{pdo_index}:", e)



# ───────────────────────────────────────────────
# Convenience wrappers for SDO writes
# ───────────────────────────────────────────────

async def write_obj_u8(can, index, subindex, value, node_id=1):
    """Write an 8-bit unsigned value to an SDO object."""
    try:
        await sdo_write_u8(can, node_id, index, subindex, value)
        print(f"→ Wrote U8  {index:04X}:{subindex:02X} = {value}")
    except Exception as e:
        print(f"⚠️ write_obj_u8 failed {index:04X}:{subindex:02X}: {e}")

async def write_obj_u16(can, index, subindex, value, node_id=1):
    """Write a 16-bit unsigned value to an SDO object."""
    try:
        await sdo_write_u16(can, node_id, index, subindex, value)
        print(f"→ Wrote U16 {index:04X}:{subindex:02X} = {value}")
    except Exception as e:
        print(f"⚠️ write_obj_u16 failed {index:04X}:{subindex:02X}: {e}")

async def write_obj_s16(can, index, subindex, value, node_id=1):
    """Write a 16-bit signed value to an SDO object."""
    try:
        await sdo_write_s16(can, node_id, index, subindex, value)
        print(f"→ Wrote S16 {index:04X}:{subindex:02X} = {value}")
    except Exception as e:
        print(f"⚠️ write_obj_s16 failed {index:04X}:{subindex:02X}: {e}")



async def set_mode(can, mode):
    """Set drive mode of operation before DS402 enable."""
    val = 3 if mode == "speed" else 4
    await sdo_write_u8(can, NODE_ID, 0x6060, 0, val)
    dbg(f" → Set Mode 0x6060={val} ({'Speed' if val==3 else 'Torque'})")

async def set_target(can, mode, val):
    if mode == "speed":
        await sdo_write_i32(can, NODE_ID, 0x60FF, 0, int(val))
    else:
        tq_01Nm = int(val * 10)
        await sdo_write_u16(can, NODE_ID, 0x6071, 0, tq_01Nm & 0xFFFF)
        dbg(f" → Torque cmd {val:.1f} Nm")

# ───────────────────────────────────────────────────────────────
# Heartbeat wait
# ───────────────────────────────────────────────────────────────
async def wait_for_heartbeat(can, timeout_ms=3000):
    dbg(" → waiting for bootup heartbeat (0x701)")
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        msg = await can.recv()
        if msg["id"] == 0x701 and msg["data"][0] in (0x00, 0x7F, 0x05):
            dbg(" → heartbeat received")
            return True
    dbg(" ⚠️ heartbeat timeout")
    return False

# ───────────────────────────────────────────────────────────────
# Main bring-up / precharge
# ───────────────────────────────────────────────────────────────
async def run(can, D, lcd=None, keypoll=None, wait_for_user=False):
    dbg("PRECHARGE: starting sequence")

    PIN_KEY.value(1)
    dbg(" → Key relay ON; wait 2.5s for inverter low-voltage rails")
    await asyncio.sleep_ms(2500)

    PIN_PCHG.value(1)
    dbg(" → Precharge relay ON; charging DC-bus")

    adc = D["adc"] if isinstance(D, dict) and "adc" in D else ADCManager()
    t0 = time.ticks_ms()
    vb = 0.0

    # wake-up stage
    while time.ticks_diff(time.ticks_ms(), t0) < 1500:
        vb = adc.batt_v
        vc = adc.cap_v
        dbg(f"wake: Vc={vc:.1f} (tgt 36.0)  Vb={vb:.1f}  t={time.ticks_diff(time.ticks_ms(), t0)}")
        if vc >= 36.0:
            break
        await asyncio.sleep_ms(120)

    dbg(" → Wake OK; issuing NMT Start to node 1")
    await can.send_async(0x000, b"\x01\x01")
    await wait_for_heartbeat(can, 3000)

    dbg(" → Continue charging to close threshold")
    close_tgt = 47.8
    t1 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t1) < 4000:
        vb = adc.batt_v
        vc = adc.cap_v
        dbg(f"close: Vc={vc:.1f} (tgt {close_tgt:.1f})  Vb={vb:.1f}  t={time.ticks_diff(time.ticks_ms(), t1)}")
        if vc >= close_tgt:
            break
        await asyncio.sleep_ms(200)

    dbg("PRECHARGE: threshold OK → closing MAIN")
    PIN_MAIN.value(1)
    await asyncio.sleep_ms(200)

    dbg(" → DS402 enable sequence")
    await ds402_shutdown(can)
    await ds402_switch_on(can)
    await ds402_enable(can)
    dbg(" → DS402 enable complete")

    dbg("PRECHARGE: bring-up complete → returning to caller")
    return "ok"
