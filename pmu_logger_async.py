
# pmu_logger_async.py — minimal 1 Hz CSV logger to SD
import uasyncio as asyncio
import time
import os
from pmu_config import DATA, LOG_TO_SD, LOG_DIR, LOG_PERIOD_HZ

_can_hooks = []  # optional (bus_name, callable(can_id:int, data:bytes))

def register_can_hook(bus_name, hook):
    _can_hooks.append((bus_name, hook))

def _ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass

def _open_daily():
    _ensure_dir(LOG_DIR)
    t = time.localtime()
    fname = "%s/pmu_%04d%02d%02d_1hz.csv" % (LOG_DIR, t[0], t[1], t[2])
    new = not _file_exists(fname)
    f = open(fname, "a")
    if new:
        f.write("ts,state,uptime,eng_rpm,eng_temp,map,iat,dc_bus,batt_v,batt_i,gen_torque,gen_power,fault,last_emcy\n")
    return f

def _file_exists(p):
    try:
        s = os.stat(p)
        return True
    except OSError:
        return False

async def log_1hz_task():
    if not LOG_TO_SD:
        return
    f = _open_daily()
    try:
        period = 1 / LOG_PERIOD_HZ if LOG_PERIOD_HZ > 0 else 1
        while True:
            ts = time.time()
            s = DATA.snapshot()
            line = ",".join(str(x) for x in (ts,) + s) + "\n"

            try:
                f.write(line)
                f.flush()
            except Exception as e:
                # If SD disappears, try re-open next loop
                try:
                    f.close()
                except: pass
                await asyncio.sleep_ms(500)
                f = _open_daily()
            await asyncio.sleep(period)
    finally:
        try:
            f.close()
        except: pass
