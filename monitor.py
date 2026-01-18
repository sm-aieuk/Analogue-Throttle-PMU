'''
How to use.... example

import uasyncio as asyncio
import monitor

async def can_rx_task():
    monitor.register_task("can_rx")
    while True:
        # ... your CAN RX logic ...
        monitor.beat("can_rx")
        await asyncio.sleep_ms(0)

async def main():
    monitor.start()
    asyncio.create_task(can_rx_task())
    # add other tasks here
    await asyncio.sleep_forever()

asyncio.run(main())

'''







# monitor.py
import uasyncio as asyncio
import time
import gc

try:
    from pyb import IWDG
    _wd = IWDG(2000)   # 2‑second watchdog
except:
    _wd = None         # Running on non‑Pyboard or watchdog disabled


# -----------------------------
# INTERNAL STATE
# -----------------------------
_cpu_idle_counter = 0
_CPU_IDLE_BASELINE = None   # learned at runtime
_task_heartbeats = {}


# -----------------------------
# IDLE PROBE (CPU load)
# -----------------------------
async def _idle_probe():
    global _cpu_idle_counter
    while True:
        _cpu_idle_counter += 1
        await asyncio.sleep_ms(0)


async def _cpu_monitor():
    global _CPU_IDLE_BASELINE, _cpu_idle_counter

    # Learn baseline during first second
    if _CPU_IDLE_BASELINE is None:
        start = _cpu_idle_counter
        await asyncio.sleep(1)
        end = _cpu_idle_counter
        _CPU_IDLE_BASELINE = max(1, end - start)

    while True:
        start = _cpu_idle_counter
        await asyncio.sleep(1)
        end = _cpu_idle_counter

        idle_ticks = end - start
        load = 1 - (idle_ticks / _CPU_IDLE_BASELINE)
        load = max(0, min(1, load))

        print("CPU load:", int(load * 100), "%")


# -----------------------------
# MEMORY MONITOR
# -----------------------------
async def _memory_monitor():
    while True:
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        total = free + alloc
        print("RAM free:", free, "of", total)

        # Optional: auto‑collect if low
        if free < 5000:
            gc.collect()

        await asyncio.sleep(2)


# -----------------------------
# TASK HEARTBEATS + WATCHDOG
# -----------------------------
def register_task(name):
    _task_heartbeats[name] = time.ticks_ms()


def beat(name):
    _task_heartbeats[name] = time.ticks_ms()


async def _watchdog_monitor():
    while True:
        now = time.ticks_ms()

        for name, last in _task_heartbeats.items():
            if time.ticks_diff(now, last) > 1500:
                print("Task stalled:", name)

        if _wd:
            _wd.feed()

        await asyncio.sleep_ms(500)


# -----------------------------
# PUBLIC START FUNCTION
# -----------------------------
def start():
    loop = asyncio.get_event_loop()
    loop.create_task(_idle_probe())
    loop.create_task(_cpu_monitor())
    loop.create_task(_memory_monitor())
    loop.create_task(_watchdog_monitor())
    print("Monitoring subsystem started")