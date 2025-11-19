
# customer_can.py — CAN2 interface to customer (1 Hz minimal publisher)
import uasyncio as asyncio
from pmu_config import DATA
try:
    from async_can_dual import AsyncCANPort
except:
    AsyncCANPort = None

# Placeholder frame IDs (replace with dbc-derived IDs)
ID_TELEM_BASE = 0x500

async def publisher_task(can2):
    """Publish a single compact telemetry frame at 1 Hz."""
    if can2 is None:
        return
    period = 1.0
    while True:
        s = DATA.snapshot()
        # pack a tiny subset into 8 bytes for now (state, rpm, batt_v*10, batt_i*10)
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
            if not isinstance(data, (bytes, bytearray, list, tuple)):
                try:
                    # Try to encode dicts or text cleanly
                    if isinstance(data, dict):
                        data = bytearray(data.values())
                    elif isinstance(data, str):
                        data = bytearray(data.encode('utf-8')[:8])  # trim to 8 bytes
                    elif isinstance(data, (int, float)):
                        data = bytearray([int(data) & 0xFF])
                    else:
                        data = bytearray([0])
                except Exception:
                    data = bytearray([0])

            can2.send(data, ID_TELEM_BASE)

        except Exception as e:
            pass
        await asyncio.sleep(period)
