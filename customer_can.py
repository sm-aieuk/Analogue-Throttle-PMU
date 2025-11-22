# customer_can.py — CAN2 interface to customer (RX + TX + command polling)

import uasyncio as asyncio
from pmu_config import DATA

try:
    from async_can_dual import AsyncCANPort
except:
    AsyncCANPort = None


# -------------------------------------------------------------------
# CUSTOMER COMMAND BUFFER
# -------------------------------------------------------------------
# 0 = no command pending
# 0x01 = CRANK
# 0x02 = PID REGEN
# 0x03 = STOP
_last_cmd = 0


# -------------------------------------------------------------------
# RX HOOK — called from CAN2 decoder
# -------------------------------------------------------------------
def feed(frame_id, data):
    """
    This function is called from the CAN2 decoder whenever a frame arrives.

    Expected customer control frame:
        ID 0x120
        data[0] = command byte

    But this can be changed later when the customer supplies a real DBC.
    """
    global _last_cmd

    try:
        if frame_id == 0x120 and len(data) > 0:
            cmd = data[0]
            if cmd in (0x01, 0x02, 0x03):
                _last_cmd = cmd

    except Exception:
        pass


# -------------------------------------------------------------------
# POLL COMMAND — called by main FSM
# -------------------------------------------------------------------
def poll_command():
    """
    Returns most recent customer command and clears it.

    0   = no command
    0x01 = start crank
    0x02 = start PID regen
    0x03 = stop → WAITING
    """
    global _last_cmd
    cmd = _last_cmd
    _last_cmd = 0
    return cmd


# -------------------------------------------------------------------
# TELEMETRY PUBLISHER — still sends your 1 Hz compact frame
# -------------------------------------------------------------------
ID_TELEM_BASE = 0x500

async def publisher_task(can2):
    """Publish compact telemetry on CAN2 at 1 Hz."""
    if can2 is None:
        return

    period = 1.0
    while True:
        s = DATA.snapshot()

        # Minimal customer-friendly telemetry:
        state = s[0] & 0x0F
        rpm   = s[2] & 0xFFFF
        bv10  = int(s[7] * 10) & 0xFFFF
        bi10  = int(s[8] * 10) & 0xFFFF

        data = bytes([
            state,
            (rpm >> 8) & 0xFF, rpm & 0xFF,
            (bv10 >> 8) & 0xFF, bv10 & 0xFF,
            (bi10 >> 8) & 0xFF, bi10 & 0xFF,
            0x00,
        ])

        try:
            can2.send(data, ID_TELEM_BASE)
        except:
            pass

        await asyncio.sleep(period)
