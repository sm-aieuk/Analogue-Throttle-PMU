# main.py — PMU orchestrator & state machine (patched for PMUData)

import sys, os

import uasyncio as asyncio
# ─────────────────────────────────────────────
# Force SD as working directory
# ─────────────────────────────────────────────

try:
    os.chdir('/sd')
    print("Changed working directory to /sd")
except Exception as e:
    print("⚠ Could not change dir:", e)

if '/sd' not in sys.path:
    sys.path.insert(0, '/sd')

# ─────────────────────────────────────────────
# Import CAN hardware once and make globals
# ─────────────────────────────────────────────
import pmu_can

# Anchor global references to prevent re-import resets




from pmu_config import DATA

from async_can_dual import (
    sdo_write_u8, sdo_write_u16, sdo_write_u32, sdo_write_s16,
    sdo_read_u8, sdo_read_u16,can_decode_task
)



# ─────────────────────────────────────────────────────────────
# CONFIG / DEBUG SWITCHES
# ─────────────────────────────────────────────────────────────
DEBUG_AUTO_MODE         = False
AUTO_MAX_CRANK_ATTEMPTS = 5
AUTO_INTER_ATTEMPT_S    = 4
AUTO_COAST_RPM_FOR_PID  = 6000
PID_TICK_MS             = 100
DEBUG_MANUAL_CRANK = True  # ← set True for remote testing
DEBUG_MANUAL_PID   = False
# ─────────────────────────────────────────────────────────────
# INTERNAL HELPERS — work with PMUData instead of dict
# ─────────────────────────────────────────────────────────────
def set_state(v:int):          DATA.state = v
def get_state():               return getattr(DATA, "state", 0)
def set_error(msg:str):        DATA.error_msg = msg
def rpm_read():                return int(getattr(DATA, "engine_rpm", 0))
def set_rpm(val:int):          DATA.engine_rpm = val
def get_auto_flag():           return getattr(DATA, "debug_flags", {}).get("auto_mode", DEBUG_AUTO_MODE)
def set_auto_flag(v:bool):
    if not hasattr(DATA, "debug_flags"):
        DATA.debug_flags = {}
    DATA.debug_flags["auto_mode"] = v

# ─────────────────────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────────────────────
_evt_start_crank = asyncio.Event()
_evt_start_pid   = asyncio.Event()
_evt_stop        = asyncio.Event()
_evt_estop       = asyncio.Event()

def clear_all_events():
    _evt_start_crank.clear()
    _evt_start_pid.clear()
    _evt_stop.clear()
    _evt_estop.clear()

def request(what: str):
    w = (what or "").lower()
    if w == "crank": _evt_start_crank.set()
    elif w == "pid": _evt_start_pid.set()
    elif w == "stop": _evt_stop.set()
    elif w == "estop": _evt_estop.set()
    elif w == "auto_on": set_auto_flag(True)
    elif w == "auto_off": set_auto_flag(False)

REQUEST = request

# ─────────────────────────────────────────────────────────────
# CAN2 LISTENER PLACEHOLDER
# ─────────────────────────────────────────────────────────────
async def can2_listener_task():
    while True:
        try:
            cmd = getattr(DATA, "can2_cmd", "").strip().upper()
            if cmd:
                request(cmd)
                DATA.can2_cmd = ""
        except Exception as e:
            set_error(f"CAN2 RX err: {e!r}")
        await asyncio.sleep_ms(50)

# ─────────────────────────────────────────────────────────────
# COAST MODE
# ─────────────────────────────────────────────────────────────
async def coast_mode(can):
    set_state(2)
    DATA.torque_cmd = 0.0
    try:
        from pmu_crank import set_target_torque
        await set_target_torque(can, 0.0)
    except Exception:
        pass
    while True:
        if _evt_estop.is_set() or _evt_stop.is_set():
            return "abort"
        set_rpm(rpm_read())  # keep updated
        await asyncio.sleep_ms(100)

# ─────────────────────────────────────────────────────────────
# PID LOOP PLACEHOLDER
# ─────────────────────────────────────────────────────────────
async def run_pid(can):
    set_state(3)
    try:
        from pmu_pid import run_pid_loop
        async for _ in run_pid_loop(can, tick_ms=PID_TICK_MS):
            if _evt_estop.is_set() or _evt_stop.is_set():
                return "abort"
    except ImportError:
        while True:
            if _evt_estop.is_set() or _evt_stop.is_set():
                return "abort"
            await asyncio.sleep_ms(PID_TICK_MS)

# ─────────────────────────────────────────────────────────────
# AUTO SUPERVISOR
# ─────────────────────────────────────────────────────────────
async def auto_supervisor():
    from pmu_can import can1 as CAN1
    print("→ Auto supervisor started")
    if not hasattr(DATA, "debug_flags"): DATA.debug_flags = {}
    if "auto_mode" not in DATA.debug_flags:
        DATA.debug_flags["auto_mode"] = DEBUG_AUTO_MODE

    while True:
        if _evt_estop.is_set():
            set_error("E-STOP")
            clear_all_events()
            set_state(0)
            await asyncio.sleep_ms(100)
            continue

        auto_on = get_auto_flag()
        set_state(0)

        if _evt_start_crank.is_set():
            await _do_crank(can)
            _evt_start_crank.clear()

        if _evt_start_pid.is_set():
            await _do_pid_from_coast(can)
            _evt_start_pid.clear()

        if not auto_on:
            await asyncio.sleep_ms(100)
            continue

        ok = await _auto_try_crank(CAN1, AUTO_MAX_CRANK_ATTEMPTS, AUTO_INTER_ATTEMPT_S)
        if not ok:
            set_error("Auto crank failed")
            await asyncio.sleep_ms(500)
            continue

        co_task = asyncio.create_task(coast_mode(CAN1))
        try:
            while True:
                if _evt_estop.is_set() or _evt_stop.is_set():
                    co_task.cancel()
                    await asyncio.sleep_ms(10)
                    break
                if rpm_read() >= AUTO_COAST_RPM_FOR_PID:
                    co_task.cancel()
                    await asyncio.sleep_ms(10)
                    await _do_pid(can)
                    break
                await asyncio.sleep_ms(100)
        finally:
            if not co_task.done():
                co_task.cancel()

        clear_all_events()
        set_state(0)
        await asyncio.sleep_ms(250)

# ─────────────────────────────────────────────────────────────
# INTERNAL ACTIONS
# ─────────────────────────────────────────────────────────────
async def _auto_try_crank(can, max_attempts, gap_s):
    for attempt in range(1, max_attempts + 1):
        if _evt_estop.is_set() or _evt_stop.is_set():
            return False
        ok = await _do_crank(can, tag=f"AUTO {attempt}/{max_attempts}")
        if ok: return True
        set_error(f"Crank attempt {attempt} failed")
        for _ in range(int(gap_s * 10)):
            if _evt_estop.is_set() or _evt_stop.is_set():
                return False
            await asyncio.sleep_ms(100)
    return False

async def _do_crank(can, tag="MANUAL"):
    try:
        from pmu_crank import crank_once
        set_state(1)
        clear_all_events()
        result = await crank_once(can=can, rpm_read=rpm_read, lcd=None, keypoll=None)
        return bool(result)
    except Exception as e:
        set_error(f"crank err: {e!r}")
        return False

async def _do_pid_from_coast(can):
    await coast_mode(can)
    await _do_pid(can)

async def _do_pid(can):
    try:
        r = await run_pid(can)
        if r == "abort": set_error("PID aborted")
    except Exception as e:
        set_error(f"pid err: {e!r}")

# ─────────────────────────────────────────────────────────────
# UI AND CAN TASKS
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# UI AND CAN TASKS
# ─────────────────────────────────────────────────────────────
# async def _start_ui_task():
#     try:
#         from pmu_ui import ui_task
#         from pmu_lcd import NHD_0420D3Z_I2C
# 
#         lcd = NHD_0420D3Z_I2C()
#         print("Display routine started OK")
# 
#         await asyncio.sleep_ms(50)  # allow LCD I2C ready
#         asyncio.create_task(ui_task(lcd))
#         print("UI task started OK")
#     except ImportError as e:
#         print("⚠ Could not import UI:", e)
#     except Exception as e:
#         print("⚠ UI task failed to start:", e)

async def _start_ui_task():
    # UI disabled — prevents constant import failures
    print("UI disabled (pmu_lcd missing).")
    while True:
        await asyncio.sleep_ms(1000)


async def _start_can1_reader_task():
    try:
        from sevcon_can1_reader import run as can1_loop
        asyncio.create_task(can1_loop())
    except ImportError:
        while True:
            await asyncio.sleep_ms(200)

async def sync_task(can, period_ms=20):
    """Send CANopen SYNC frame (ID 0x80, DLC 0) every 20 ms."""
    print("→ SYNC task started")
    empty = b""

    while True:
        try:
            can._can.send(empty, 0x80)
        except Exception as e:
            print("SYNC send error:", e)
        await asyncio.sleep_ms(period_ms)



# ─────────────────────────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────────────────────────
async def main():
    print("Main Starting (DATA type:", type(DATA).__name__, ")")

    CAN1 = pmu_can.can1
    CAN2 = pmu_can.can2
    await CAN1.start()
    await CAN2.start()
    print("AsyncCANPort tasks started.")

    asyncio.create_task(sync_task(CAN1, 20))

    
    
    # Initialise dynamic attributes on PMUData
    try:
        if not hasattr(DATA, "can2_cmd"): DATA.can2_cmd = ""
        if not hasattr(DATA, "debug_flags"): DATA.debug_flags = {}
        if not hasattr(DATA, "torque_cmd"): DATA.torque_cmd = 0.0
        if not hasattr(DATA, "engine_rpm"): DATA.engine_rpm = 0
        if not hasattr(DATA, "error_msg"): DATA.error_msg = ""
    except Exception as e:
        print("⚠️ DATA init failed:", e)

 
    tasks = [
#       asyncio.create_task(_start_ui_task()),
       asyncio.create_task(can2_listener_task()),
       asyncio.create_task(_start_can1_reader_task()),
       asyncio.create_task(auto_supervisor()),  # ← fixed
    ]

    print("CAN1 object id:", id(CAN1._can))
    if CAN1 is not None:
       asyncio.create_task(can_decode_task(CAN1, DATA))  # ← fixed
    else:
       print("⚠️ CAN1 not initialized — skipping can_decode_task")

    await asyncio.sleep_ms(200)
    print("✅ Background CAN decode task started, waiting for 0x381 frames…")
    print("CAN1 object id from pmu_can (before manual crank):", id(CAN1._can))

    if DEBUG_MANUAL_CRANK:
        from pmu_crank import run as crank_run
        print("→ Manual crank test mode active")
        crank_task = asyncio.create_task(crank_run(CAN1,DATA))  # ← fixed
        await crank_task
        print("✅ Manual crank sequence complete")

    elif DEBUG_MANUAL_PID:
        from pmu_pid import run as pid_run
        print("→ Manual PID test mode active")
        await pid_run(CAN1)  # ← fixed
        print("✅ Manual PID sequence complete")

    else:
        print("→ Manual crank test mode active")
        import pmu_crank
        await pmu_crank.run(CAN1, lcd=None, keypoll=None, rpm_read=None, DATA=DATA)  # ← fixed

# ─────────────────────────────────────────────
# Supervisor loop
# ─────────────────────────────────────────────
    while True:
        for i, t in enumerate(list(tasks)):
            if t.done():
                try:
                    t.result()
                except Exception as e:
                    set_error(f"Task crash: {e!r}")

                # DO NOT restart the UI task (index 0)
                if i == 0:
                    continue

                # Restart other tasks
                restart_map = [
                    lambda: None,                # UI (disabled / do not restart)
                    can2_listener_task,          # index 1
                    _start_can1_reader_task,     # index 2
                    lambda: auto_supervisor(can1)  # index 3
                ]

                tasks[i] = asyncio.create_task(restart_map[i]())

        await asyncio.sleep_ms(200)



# ─────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────
try:
    asyncio.run(main())
except Exception as e:
    print("❌ MAIN crash:", e)
    sys.print_exception(e)
    set_error(f"BOOT err: {e!r}")
