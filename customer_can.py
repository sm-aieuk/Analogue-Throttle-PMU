# customer_can.py — CAN2 interface to customer (RX + TX + command polling)
# -----------------------------------------------------------------------

import uasyncio as asyncio
from pmu_config import DATA

try:
    from async_can_dual import AsyncCANPort
except:
    AsyncCANPort = None


# -------------------------------------------------------------------
# CUSTOMER COMMAND BUFFER
# -------------------------------------------------------------------
_last_cmd = 0


# -------------------------------------------------------------------
# RX HOOK — called from CAN2 decoder
# -------------------------------------------------------------------
def feed(frame_id, data):
    """Receive CAN2 commands from customer node."""
    global _last_cmd
    try:
        if frame_id == 0x120 and len(data) > 0:
            cmd = data[0]
            if cmd in (0x01, 0x02, 0x03):
                _last_cmd = cmd
    except Exception as e:
        print("customer_can feed error:", e)


# -------------------------------------------------------------------
# POLL COMMAND — called by FSM
# -------------------------------------------------------------------
def poll_command():
    global _last_cmd
    cmd = _last_cmd
    _last_cmd = 0
    return cmd


# -------------------------------------------------------------------
# TELEMETRY PUBLISHER — fixed argument order + exception logging
# -------------------------------------------------------------------
ID_TELEM_BASE = 0x500

async def publisher_task(can2):
    """Publish compact telemetry on CAN2 at 1 Hz."""
    if can2 is None:
        print("customer_can: no CAN2, publisher disabled")
        return

    period = 1.0

    while True:
        try:
            s = DATA.snapshot()

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

            # ★★★★★ FINAL FIX HERE ★★★★★
            can2.tx(ID_TELEM_BASE, data)

        except Exception as e:
            print("customer_can publisher error:", e)

        await asyncio.sleep(period)


