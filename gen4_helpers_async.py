# gen4_helpers_async.py
# Async SDO + DS402 helpers compatible with the original AsyncCANPort
# (must provide send_async(can_id, data) and recv() -> dict with "id", "data")
#
# - Expedited SDO read/write (u8/u16/u32/i8/i16/i32)
# - DS402 control helpers (6040/6060/6041)
# - Sevcon speed/torque demand writers (60FF/6071)
# - NMT helper (ensure_nmt_operational)
#
# All functions used by pmu_crank.py are defined here.

import uasyncio as asyncio
import utime

# ──────────────────────────────────────────────────────────────
# Time helpers

def _now():
    return utime.ticks_ms()

def _elapsed(t0):
    return utime.ticks_diff(_now(), t0)

# ──────────────────────────────────────────────────────────────
# Packing / unpacking

def _le16(x):  # little-endian 16-bit
    return bytes((x & 0xFF, (x >> 8) & 0xFF))

def _pack_u32(x):
    return bytes((
        x        & 0xFF,
        (x >> 8) & 0xFF,
        (x >> 16) & 0xFF,
        (x >> 24) & 0xFF,
    ))

def _unpack_u32(b0, b1, b2, b3):
    return (b3 << 24) | (b2 << 16) | (b1 << 8) | b0

def _sign32(u):
    return u - 0x100000000 if u & 0x80000000 else u

def _sign16(u):
    return u - 0x10000 if u & 0x8000 else u

def _sign8(u):
    return u - 0x100 if u & 0x80 else u

# ──────────────────────────────────────────────────────────────
# CANopen COB-IDs

def _sdo_tx_cobid(node_id):  # client->server
    return 0x600 + (node_id & 0x7F)

def _sdo_rx_cobid(node_id):  # server->client
    return 0x580 + (node_id & 0x7F)

# ──────────────────────────────────────────────────────────────
# SDO command specifiers

SDO_CCS_DOWNLOAD_EXP = 0x23  # write 4 bytes
SDO_CCS_DOWNLOAD_2B  = 0x2B  # write 2 bytes
SDO_CCS_DOWNLOAD_1B  = 0x2F  # write 1 byte
SDO_CCS_UPLOAD_REQ   = 0x40  # read request
SDO_SCS_DOWNLOAD_OK  = 0x60  # write ack

def _is_upload_ok(cmd):
    # Match 0x43 / 0x4B / 0x4F / 0x41 -> coarse pattern
    return (cmd & 0xE3) == 0x41

# Abort decoder (0x80 in byte 0; code in bytes 4..7)

def _maybe_abort(frame_data):
    if not frame_data or len(frame_data) < 8:
        return None
    if frame_data[0] != 0x80:
        return None
    code = _unpack_u32(frame_data[4], frame_data[5], frame_data[6], frame_data[7])
    return code

_ABRT = {
    0x05040001: "Toggle bit not alternated",
    0x05040005: "SDO protocol timed out",
    0x06010000: "Unsupported access to an object",
    0x06010001: "Attempt to read a write-only object",
    0x06010002: "Attempt to write a read-only object",
    0x06020000: "Object does not exist",
    0x06040041: "Object cannot be mapped to PDO",
    0x06070010: "Data type does not match, length too short",
    0x06070012: "Data type does not match, length too high",
    0x06090011: "Sub-index does not exist",
    0x06090030: "Value range exceeded",
    0x06090031: "Value too high",
    0x06090032: "Value too low",
    0x060A0023: "Resource not available",
    0x08000020: "Data cannot be transferred or stored",
    0x08000021: "Data cannot be transferred or stored (local control)",
    0x08000022: "Data cannot be transferred or stored (device state)",
    0x08000023: "Object dictionary not present",
}

def _abort_str(code):
    s = _ABRT.get(code, "Unknown abort")
    return "0x%08X — %s" % (code, s)

# ──────────────────────────────────────────────────────────────
# Core SDO transactions (expedited)

async def _sdo_write_exp(can_port, node_id, index, sub, payload_bytes, timeout_ms=500):
    """
    Expedited SDO write (1–4 bytes).
    Raises OSError on timeout/abort, returns True on success.
    """
    n = len(payload_bytes)
    if n == 4:
        cmd = SDO_CCS_DOWNLOAD_EXP
        p = payload_bytes
    elif n == 2:
        cmd = SDO_CCS_DOWNLOAD_2B
        p = payload_bytes + b"\x00\x00"
    elif n == 1:
        cmd = SDO_CCS_DOWNLOAD_1B
        p = payload_bytes + b"\x00\x00\x00"
    else:
        raise ValueError("Expedited write supports 1–4 bytes only")

    # Try to clear any stale SDO replies from queue, if the port exposes _rx_q
    if hasattr(can_port, "_rx_q"):
        while True:
            try:
                _ = can_port._rx_q.get_nowait()
            except Exception:
                break

    frame = bytes((
        cmd,
        index & 0xFF, (index >> 8) & 0xFF,
        sub & 0xFF,
    )) + p

    tx_id = _sdo_tx_cobid(node_id)
    rx_id = _sdo_rx_cobid(node_id)

    await can_port.send_async(tx_id, frame)

    t0 = _now()
    while _elapsed(t0) < timeout_ms:
        msg = await can_port.recv()
        if not isinstance(msg, dict):
            continue
        if msg.get("id") != rx_id:
            continue
        data = msg.get("data", b"")
        if len(data) < 4:
            continue

        ab = _maybe_abort(data)
        if ab is not None:
            raise OSError("SDO abort on %04X:%02X — %s" %
                          (index, sub, _abort_str(ab)))

        if (data[0] == SDO_SCS_DOWNLOAD_OK and
            data[1] == (index & 0xFF) and
            data[2] == ((index >> 8) & 0xFF) and
            data[3] == (sub & 0xFF)):
            return True

    raise OSError("SDO write timeout for %04X:%02X" % (index, sub))


async def _sdo_read_exp(can_port, node_id, index, sub, timeout_ms=200):
    """
    Expedited SDO read.
    Returns raw payload bytes (1–4) or raises OSError on timeout/abort.
    """
    req = bytes((
        SDO_CCS_UPLOAD_REQ,
        index & 0xFF, (index >> 8) & 0xFF,
        sub & 0xFF,
        0, 0, 0, 0,
    ))
    await can_port.send_async(_sdo_tx_cobid(node_id), req)

    cob_expect = _sdo_rx_cobid(node_id)
    t0 = _now()
    while _elapsed(t0) < timeout_ms:
        msg = await can_port.recv()
        if not isinstance(msg, dict):
            continue
        if msg.get("id") != cob_expect:
            continue
        data = msg.get("data", b"")
        if len(data) < 4:
            continue

        ab = _maybe_abort(data)
        if ab is not None:
            raise OSError("SDO abort on %04X:%02X — %s" %
                          (index, sub, _abort_str(ab)))

        if _is_upload_ok(data[0]) and \
           data[1] == (index & 0xFF) and \
           data[2] == ((index >> 8) & 0xFF) and \
           data[3] == (sub & 0xFF):
            # n-bits indicate unused bytes
            n_unused = (data[0] >> 2) & 0x3
            size = 4 - n_unused
            if size < 0 or size > 4:
                size = 4
            return bytes(data[4:4+size])

    raise OSError("SDO read timeout for %04X:%02X" % (index, sub))

# ──────────────────────────────────────────────────────────────
# Typed SDO API

async def sdo_write_u8(can_port, node_id, index, sub, value, timeout_ms=200):
    await _sdo_write_exp(can_port, node_id, index, sub,
                         bytes((value & 0xFF,)), timeout_ms)

async def sdo_write_u16(can_port, node_id, index, sub, value, timeout_ms=200):
    await _sdo_write_exp(can_port, node_id, index, sub,
                         _le16(value & 0xFFFF), timeout_ms)

async def sdo_write_u32(can_port, node_id, index, sub, value, timeout_ms=200):
    await _sdo_write_exp(can_port, node_id, index, sub,
                         _pack_u32(value & 0xFFFFFFFF), timeout_ms)

async def sdo_write_i8(can_port, node_id, index, sub, value, timeout_ms=200):
    v = value & 0xFF
    await _sdo_write_exp(can_port, node_id, index, sub,
                         bytes((v,)), timeout_ms)

async def sdo_write_i16(can_port, node_id, index, sub, value, timeout_ms=200):
    v = value & 0xFFFF
    await _sdo_write_exp(can_port, node_id, index, sub,
                         _le16(v), timeout_ms)

async def sdo_write_i32(can_port, node_id, index, sub, value, timeout_ms=200):
    v = value & 0xFFFFFFFF
    await _sdo_write_exp(can_port, node_id, index, sub,
                         _pack_u32(v), timeout_ms)

async def sdo_read_u8(can_port, node_id, index, sub, timeout_ms=200):
    b = await _sdo_read_exp(can_port, node_id, index, sub, timeout_ms)
    return b[0] if len(b) else 0

async def sdo_read_u16(can_port, node_id, index, sub, timeout_ms=200):
    b = await _sdo_read_exp(can_port, node_id, index, sub, timeout_ms)
    if len(b) < 2:
        return b[0]
    return (b[1] << 8) | b[0]

async def sdo_read_u32(can_port, node_id, index, sub, timeout_ms=200):
    b = await _sdo_read_exp(can_port, node_id, index, sub, timeout_ms)
    b = (b + b"\x00\x00\x00\x00")[:4]
    return _unpack_u32(b[0], b[1], b[2], b[3])

async def sdo_read_i8(can_port, node_id, index, sub, timeout_ms=200):
    return _sign8(await sdo_read_u8(can_port, node_id, index, sub, timeout_ms))

async def sdo_read_i16(can_port, node_id, index, sub, timeout_ms=200):
    return _sign16(await sdo_read_u16(can_port, node_id, index, sub, timeout_ms))

async def sdo_read_i32(can_port, node_id, index, sub, timeout_ms=200):
    return _sign32(await sdo_read_u32(can_port, node_id, index, sub, timeout_ms))

# ──────────────────────────────────────────────────────────────
# DS402 / Sevcon constants

OD_CONTROLWORD   = 0x6040  # u16
OD_STATUSWORD    = 0x6041  # u16
OD_MODES_OF_OP   = 0x6060  # i8
OD_MODES_DISPLAY = 0x6061  # i8
OD_SPEED_DEMAND  = 0x60FF  # i32
OD_TORQUE_DEMAND = 0x6071  # i16

# Modes of operation (typical Sevcon values)
OPMODE_PROFILED_TORQUE = 0x01
OPMODE_VELOCITY        = 0x03
OPMODE_TORQUE          = 0x04
OPMODE_HOMING          = 0x06
OPMODE_INTERP_POS      = 0x07
OPMODE_CYCLIC_SYNC_POS = 0x08
OPMODE_CYCLIC_SYNC_VEL = 0x09
OPMODE_CYCLIC_SYNC_TOR = 0x0A

# Alias used by pmu_crank
MOD_TORQUE = OPMODE_TORQUE

# Controlword bits
CW_SWITCH_ON        = 1 << 0
CW_ENABLE_VOLTAGE   = 1 << 1
CW_QUICK_STOP       = 1 << 2
CW_ENABLE_OPERATION = 1 << 3
CW_RESET_FAULT      = 1 << 7

# ──────────────────────────────────────────────────────────────
# DS402 helpers

async def ds402_set_mode(can_port, node_id, mode_i8):
    await sdo_write_i8(can_port, node_id, OD_MODES_OF_OP, 0x00, mode_i8)

async def ds402_controlword(can_port, node_id, value_u16):
    await sdo_write_u16(can_port, node_id, OD_CONTROLWORD, 0x00, value_u16)

async def ds402_shutdown(can_port, node_id):
    # 0x0006: Switch On Disabled -> Ready to Switch On
    val = CW_ENABLE_VOLTAGE | CW_QUICK_STOP
    await ds402_controlword(can_port, node_id, val)

async def ds402_switch_on(can_port, node_id):
    # 0x0007: Ready to Switch On -> Switched On
    val = CW_SWITCH_ON | CW_ENABLE_VOLTAGE | CW_QUICK_STOP
    await ds402_controlword(can_port, node_id, val)

async def ds402_enable_operation(can_port, node_id):
    # 0x000F: Switched On -> Operation Enabled
    val = CW_SWITCH_ON | CW_ENABLE_VOLTAGE | CW_QUICK_STOP | CW_ENABLE_OPERATION
    await ds402_controlword(can_port, node_id, val)

# Alias for pmu_crank imports
async def ds402_enable(can_port, node_id):
    await ds402_enable_operation(can_port, node_id)

async def ds402_quick_stop(can_port, node_id):
    # Clear ENABLE_OPERATION bit (keep quick stop)
    val = CW_SWITCH_ON | CW_ENABLE_VOLTAGE | CW_QUICK_STOP
    await ds402_controlword(can_port, node_id, val)

async def ds402_reset_fault(can_port, node_id):
    # Pulse reset fault bit, then we'll follow with 0x0006 in ds402_enable_in_mode
    await ds402_controlword(can_port, node_id, CW_RESET_FAULT)
    await asyncio.sleep_ms(30)

# ──────────────────────────────────────────────────────────────
# NMT / statusword helpers

async def ensure_nmt_operational(can_port, node_id):
    """
    Send NMT 'Start Remote Node' (Operational) to the given node.
    Node_id 0 => broadcast (all nodes).
    """
    nid = node_id & 0x7F
    frame = bytes((0x01, nid))
    await can_port.send_async(0x000, frame)
    await asyncio.sleep_ms(30)

async def sevcon_read_statusword(can_port, node_id):
    """
    Read 0x6041:00 (statusword, u16).
    Returns (ok: bool, value_u16: int, abort_or_msg: str or None).
    """
    try:
        val = await sdo_read_u16(can_port, node_id, OD_STATUSWORD, 0x00)
        return True, val, None
    except OSError as e:
        return False, 0, str(e)

async def ds402_enable_in_mode(can_port, node_id, mode_i8):
    """
    Bring node to Operation Enabled in a given mode with 30 ms delays:
      1) NMT Operational
      2) Reset fault
      3) Shutdown (0x0006)
      4) Switch On (0x0007)
      5) Enable Operation (0x000F)
      6) Set Mode of Operation
      7) Verify statusword
    """
    print("DS402: enabling node {} in mode {}".format(node_id, mode_i8))

    # 1) NMT operational
    await ensure_nmt_operational(can_port, node_id)

    # 2) Reset fault (already sleeps 30 ms inside)
    await ds402_reset_fault(can_port, node_id)

    # 3) Shutdown (0x0006)
    await ds402_shutdown(can_port, node_id)
    await asyncio.sleep_ms(30)

    # 4) Switch on (0x0007)
    await ds402_switch_on(can_port, node_id)
    await asyncio.sleep_ms(30)

    # 5) Enable operation (0x000F)
    await ds402_enable_operation(can_port, node_id)
    await asyncio.sleep_ms(30)

    # 6) Set mode of operation
    await ds402_set_mode(can_port, node_id, mode_i8)
    await asyncio.sleep_ms(30)

    # 7) Read and check statusword
    ok, sw, abort = await sevcon_read_statusword(can_port, node_id)
    if not ok:
        print("DS402: ⚠ failed to read statusword:", abort)
        return False

    print("DS402: statusword=0x{:04X}".format(sw))

    # Check typical Operation Enabled pattern: mask 0x006F -> 0x0027
    if (sw & 0x006F) == 0x0027:
        print("DS402: node {} is OPERATION ENABLED".format(node_id))
        return True

    print("DS402: ⚠ node {} NOT enabled, statusword=0x{:04X}".format(node_id, sw))
    return False

# ──────────────────────────────────────────────────────────────
# Sevcon demand writers

async def sevcon_write_speed_rpm(can_port, node_id, rpm_i32):
    """Write 0x60FF:00 as signed i32 RPM."""
    await sdo_write_i32(can_port, node_id, OD_SPEED_DEMAND, 0x00, rpm_i32)

async def sevcon_write_torque_raw(can_port, node_id, val_i16):
    """Write 0x6071:00 as signed i16 (device-specific scaling)."""
    await sdo_write_i16(can_port, node_id, OD_TORQUE_DEMAND, 0x00, val_i16)


async def sdo_write_torque_nm(can, node_id, torque_nm):
    """
    Write torque demand using SDO object 0x6071:00.
    Sevcon expects torque in 0.1 Nm units (signed 16-bit).
    """
    units = int(torque_nm * 10)
    if units > 32767: units = 32767
    if units < -32768: units = -32768

    ok = await can.sdo_write_u16(node_id, 0x6071, 0x00, units & 0xFFFF)
    return ok
