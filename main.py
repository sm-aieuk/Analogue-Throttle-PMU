# main.py — PHASE 2 full PMU state machine rebuild with boot flags
# -------------------------------------------------

import uasyncio as asyncio
import time

import pmu_ui
import pmu_preactor_standalone
import pmu_crank_io
import pmu_pid_regen
import customer_can

from pmu_config import (
    DATA,
    STATE_WAITING,
    STATE_CRANK,
    STATE_COAST,
    STATE_REGEN,
)

from pmu_can import init_can, start_can
from async_can_dual import sync_task
from pmu_supervisor_can import gen4_supervisor

from NHD_Display import NHD_0420D3Z_I2C
from pmu_logger_async import log_1hz_task


# --------------------------------------------------------------------
# MODE SELECTION FLAGS (set these for remote testing)
# --------------------------------------------------------------------
FORCE_PRECHARGE_TEST = False
FORCE_CRANK_AT_BOOT  = True
FORCE_PID_AT_BOOT    = False


# -----------------------------------------------------------------------------------
# Global objects
# -----------------------------------------------------------------------------------
DATA.lcd = NHD_0420D3Z_I2C()     # LCD object for UI and status
pmu_state = STATE_WAITING        # The main PMU state machine state


# -----------------------------------------------------------------------------------
# Customer CAN2 Handler (Mode Select Commands)
# -----------------------------------------------------------------------------------
async def customer_can_handler():
    """
    Listen on CAN2 for customer commands:
        0x01 = START ENGINE (CRANK)
        0x02 = ENTER REGEN MODE
        0x03 = ABORT → Return to WAITING
    """
    global pmu_state

    while True:
        cmd = customer_can.poll_command()

        if cmd == 0x01:
            pmu_state = STATE_CRANK

        elif cmd == 0x02:
            pmu_state = STATE_REGEN

        elif cmd == 0x03:
            pmu_state = STATE_WAITING

        await asyncio.sleep_ms(50)


# -----------------------------------------------------------------------------------
# AUTO PMU STATE MACHINE
# WAITING → CRANK → COAST → PID → WAITING
# -----------------------------------------------------------------------------------
async def pmu_fsm():

    global pmu_state

    while True:

        if pmu_state == STATE_WAITING:
            DATA.state = STATE_WAITING
            await asyncio.sleep_ms(100)
            continue

        # -------------------------------
        # CRANK
        # -------------------------------
        if pmu_state == STATE_CRANK:
            print("FSM: Starting CRANK sequence")
            DATA.state = STATE_CRANK

            if DATA.dc_bus_v < (0.85 * DATA.battery_v):
                print("FSM: Running precharge first")
                await pmu_preactor_standalone.run(DATA, CAN1, DATA.lcd)

            await pmu_crank_io.run(DATA, CAN1, DATA.lcd)

            print("FSM: Crank complete → transition to COAST")
            pmu_state = STATE_COAST
            continue

        # -------------------------------
        # COAST
        # -------------------------------
        if pmu_state == STATE_COAST:
            print("FSM: COAST mode — letting RPM stabilise")
            DATA.state = STATE_COAST
            await asyncio.sleep_ms(1500)
            pmu_state = STATE_REGEN
            continue

        # -------------------------------
        # REGEN PID
        # -------------------------------
        if pmu_state == STATE_REGEN:
            print("FSM: ENTER PID REGEN")
            DATA.state = STATE_REGEN

            await pmu_pid_regen.run(CAN1, DATA, DATA.lcd)

            pmu_state = STATE_WAITING
            continue

        pmu_state = STATE_WAITING
        await asyncio.sleep_ms(100)



# -----------------------------------------------------------------------------------
# MAIN ENTRY POINT
# -----------------------------------------------------------------------------------
async def main():

    global CAN1, CAN2
    global pmu_state

    # ------------------------------------------------------------------
    # 1. Initialize CAN hardware
    # ------------------------------------------------------------------
    CAN1, CAN2 = init_can()

    # ------------------------------------------------------------------
    # 2. Start CAN RX & decode tasks
    # ------------------------------------------------------------------
    await start_can()

    # ------------------------------------------------------------------
    # 3. Start SYNC generator (GEN4 requires this)
    # ------------------------------------------------------------------
    asyncio.create_task(sync_task(CAN1, 20))   # 20ms = 50 Hz sync

    # ------------------------------------------------------------------
    # 4. CAN supervisor (heartbeat + PDO watchdog)
    # ------------------------------------------------------------------
    asyncio.create_task(gen4_supervisor())

    # ------------------------------------------------------------------
    # 5. UI task startup
    # ------------------------------------------------------------------
    await asyncio.sleep_ms(300)
    asyncio.create_task(pmu_ui.ui_task(DATA.lcd))

    # ------------------------------------------------------------------
    # 6. ADC manager
    # ------------------------------------------------------------------
    asyncio.create_task(DATA.adc_mgr.task())

    # ------------------------------------------------------------------
    # 7. Logger
    # ------------------------------------------------------------------
    asyncio.create_task(log_1hz_task())

    # ------------------------------------------------------------------
    # 8. Customer CAN2 handler
    # ------------------------------------------------------------------
    asyncio.create_task(customer_can_handler())

    # ------------------------------------------------------------------
    # 9. MODE SELECTION at boot
    # ------------------------------------------------------------------
    if FORCE_PRECHARGE_TEST:
        print("Boot mode: PRECHARGE TEST")
        asyncio.create_task(pmu_preactor_standalone.run(DATA, CAN1, DATA.lcd))
        pmu_state = STATE_WAITING

    elif FORCE_CRANK_AT_BOOT:
        print("Boot mode: CRANK")
        pmu_state = STATE_CRANK

    elif FORCE_PID_AT_BOOT:
        print("Boot mode: PID REGEN")
        pmu_state = STATE_REGEN

    else:
        print("Boot mode: WAITING")
        pmu_state = STATE_WAITING


    # ------------------------------------------------------------------
    # 10. Start PMU FSM
    # ------------------------------------------------------------------
    asyncio.create_task(pmu_fsm())

    print("PMU System Ready.")

    # ------------------------------------------------------------------
    # 11. Idle forever
    # ------------------------------------------------------------------
    while True:
        await asyncio.sleep_ms(200)


# -----------------------------------------------------------------------------------
# BOOT
# -----------------------------------------------------------------------------------
asyncio.run(main())
