# pmu_supervisor_can.py — patched to prevent silent crashes
# ---------------------------------------------------------

import pyb
import uasyncio as asyncio
from pmu_config import DATA

HEARTBEAT_TIMEOUT = 300     # ms
PDO_TIMEOUT       = 250     # ms


# Initialise missing fields if necessary
if not hasattr(DATA, "gen4_last_hb_ms"):
    DATA.gen4_last_hb_ms = 0

if not hasattr(DATA, "gen4_last_pdo_ms"):
    DATA.gen4_last_pdo_ms = 0

if not hasattr(DATA, "gen4_online"):
    DATA.gen4_online = False


async def gen4_supervisor():
    """Monitor GEN4 online/offline state."""
    while True:
        try:
            now = pyb.millis()

            # Heartbeat check
            if now - DATA.gen4_last_hb_ms > HEARTBEAT_TIMEOUT:
                DATA.gen4_online = False

            # PDO flow check
            if now - DATA.gen4_last_pdo_ms > PDO_TIMEOUT:
                DATA.gen4_online = False

        except Exception as e:
            print("Supervisor error:", e)

        await asyncio.sleep_ms(50)
