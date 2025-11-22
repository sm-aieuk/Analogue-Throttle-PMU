# pmu_supervisor_can.py
# -----------------------------------------------------------
# CAN supervision: GEN4 online/offline logic
# -----------------------------------------------------------
import pyb

from pmu_config import DATA
import uasyncio as asyncio

HEARTBEAT_TIMEOUT = 300     # ms
PDO_TIMEOUT       = 250     # ms

async def gen4_supervisor():
    """Monitor GEN4 online state."""
    while True:
        now = pyb.millis()

        # Heartbeat check
        if now - DATA.gen4_last_hb_ms > HEARTBEAT_TIMEOUT:
            DATA.gen4_online = False

        # PDO flow check
        if now - DATA.gen4_last_pdo_ms > PDO_TIMEOUT:
            DATA.gen4_online = False

        await asyncio.sleep_ms(50)
