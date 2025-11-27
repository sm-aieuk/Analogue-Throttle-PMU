# main.py — PHASE 2 full PMU state machine rebuild with boot flags
# -------------------------------------------------

import uasyncio as asyncio
import time
import pmu_can


import pmu_ui


import pmu_preactor_standalone
import pmu_crank_io
import pmu_pid_regen
import customer_can
import pmu_config


from pmu_config import (
    DATA,
    STATE_WAITING,
    STATE_PRECHARGE,
    STATE_CRANK,
    STATE_COAST,
    STATE_REGEN
)


from async_can_dual import sync_task
from pmu_supervisor_can import gen4_supervisor

from NHD_Display import NHD_0420D3Z_I2C
from pmu_logger_async import log_1hz_task


# --------------------------------------------------------------------
# MODE SELECTION FLAGS (set these for remote testing)
# --------------------------------------------------------------------
FORCE_PRECHARGE_TEST = False
FORCE_CRANK_AT_BOOT  = False
FORCE_PID_AT_BOOT    = False


# ----------------------------------------------------------------------------
# GLOBAL OBJECTS
# ----------------------------------------------------------------------------

DATA.state = STATE_WAITING
# Start menu/UI


 


async def raw_can_debug(can_hw):
    while True:
        try:
            if can_hw.any(0):
                print("PMU FIFO0:", can_hw.recv(0))
            if can_hw.any(1):
                print("PMU FIFO1:", can_hw.recv(1))
        except Exception as e:
            print("RAW DEBUG ERROR:", e)
        await asyncio.sleep_ms(5)


# ----------------------------------------------------------------------------
# CUSTOMER CAN2 HANDLER
# ----------------------------------------------------------------------------
async def customer_can_handler():
    
    while True:
        try:
            cmd = customer_can.poll_command()
            if cmd == 0x01:
                DATA.state = STATE_CRANK
            elif cmd == 0x02:
                DATA.state = STATE_REGEN
            elif cmd == 0x03:
                DATA.state = STATE_WAITING
        except Exception as e:
            print("Customer CAN handler error:", e)
        await asyncio.sleep_ms(50)



# ----------------------------------------------------------------------------
# PMU FSM
# ----------------------------------------------------------------------------
async def pmu_fsm(CAN1_PORT):

    STATE_NAMES = {
        STATE_WAITING: "WAIT",
        STATE_PRECHARGE: "PCHG",
        STATE_CRANK: "CRNK",
        STATE_COAST: "COST",
        STATE_REGEN: "RGN",
    }

    while True:

        # Update UI text and request status refresh
        DATA.state_txt = STATE_NAMES.get(DATA.state, "UNK")
        DATA.ui_needs_update = True

        # ---------- WAITING ----------
        if DATA.state == STATE_WAITING:
            await asyncio.sleep_ms(100)
            continue

        # ---------- PRECHARGE ----------
        if DATA.state == STATE_PRECHARGE:
            print("FSM: Precharge start")

            if DATA.dc_bus_v < (0.85 * DATA.battery_v):
                await pmu_preactor_standalone.run(DATA, CAN1_PORT, DATA.lcd)

            print("FSM: Precharge done → COAST")
            DATA.state = STATE_COAST
            continue

        # ---------- CRANK ----------
        if DATA.state == STATE_CRANK:
            print("FSM: Starting CRANK sequence")

            # Ensure precharge
            if DATA.dc_bus_v < (0.85 * DATA.battery_v):
                await pmu_preactor_standalone.run(DATA, CAN1_PORT, DATA.lcd)

            await pmu_crank_io.run(DATA, CAN1_PORT, DATA.lcd)

            print("FSM: Crank complete → COAST")
            DATA.state = STATE_COAST
            continue

        # ---------- COAST ----------
        if DATA.state == STATE_COAST:
            print("FSM: COAST mode — letting RPM stabilise")
            await asyncio.sleep_ms(1500)
            continue

        # ---------- REGEN ----------
        if DATA.state == STATE_REGEN:
            print("FSM: ENTER PID REGEN")

            await pmu_pid_regen.run(CAN1_PORT, DATA, DATA.lcd)

            DATA.state = STATE_WAITING
            continue

        # Safety default
        DATA.state = STATE_WAITING
        await asyncio.sleep_ms(100)


async def delayed_ui_start():
    await asyncio.sleep_ms(500)
    try:
        await DATA.lcd.clear_screen()
        await DATA.lcd.set_cursor(0, 0)
        await DATA.lcd.write_string("PMU Ready")
    except Exception as e:
        print("LCD init error:", e)

    DATA.ui_needs_update = True
    print("Starting UI task now…")
    asyncio.create_task(pmu_ui.ui_task(DATA.lcd))
    await asyncio.sleep_ms(5)

    
# ----------------------------------------------------------------------------
# MAIN ENTRY
# ----------------------------------------------------------------------------
async def main():
    print("Initialising LCD early…")
    lcd = NHD_0420D3Z_I2C()
    DATA.lcd = lcd
    
    DATA.ui_button = None
    DATA.ui_needs_update = True





    print("Starting CAN1/CAN2…")
    CAN1_PORT, CAN2_PORT = await pmu_can.start_can()
    print("CAN tasks started.")

    DATA.can1 = CAN1_PORT
    DATA.can2 = CAN2_PORT


    print("Starting Customer Task…")
    asyncio.create_task(customer_can.publisher_task(CAN2_PORT))

#debugging canbus 
    #asyncio.create_task(raw_can_debug(CAN1_PORT.hwcan))


    # Sync generator
    print("Starting SYNC task…")
    asyncio.create_task(sync_task(CAN1_PORT.hwcan, 20))




    # Supervisor
    print("Starting supervisor…")
    asyncio.create_task(gen4_supervisor())


    # ADC
    print("Starting ADC…")
    asyncio.create_task(DATA.adc_mgr.task())

    # Logger
    print("Starting logger…")
    asyncio.create_task(log_1hz_task())

    # Customer CAN
    print("Starting customer CAN…")
    asyncio.create_task(customer_can_handler())
    
    # Boot mode
    if FORCE_PRECHARGE_TEST:
        print("Boot mode: PRECHARGE TEST")
        asyncio.create_task(pmu_preactor_standalone.run(DATA, CAN1_PORT, DATA.lcd))

    elif FORCE_CRANK_AT_BOOT:
        print("Boot mode: CRANK")
        DATA.state = STATE_CRANK

    elif FORCE_PID_AT_BOOT:
        print("Boot mode: PID REGEN")
        DATA.state = STATE_REGEN

    else:
        print("Boot mode: WAITING")
        DATA.state = STATE_WAITING

    # Start FSM
    asyncio.create_task(pmu_fsm(CAN1_PORT))


    print("Scheduling UI…")
    asyncio.create_task(delayed_ui_start())


    print("PMU System Ready.")
 
 
 
    # Idle forever
    while True:
        await asyncio.sleep_ms(200)


# ----------------------------------------------------------------------------
# BOOT
# ----------------------------------------------------------------------------
asyncio.run(main())
