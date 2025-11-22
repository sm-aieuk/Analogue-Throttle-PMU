import uasyncio as asyncio
from machine import Pin
import sys

from pmu_config import DATA
from pmu_can import CAN1, CAN2

# -------------------------------------------------------------------
# BUTTON QUEUE (SYNC → not awaited)
# -------------------------------------------------------------------
class SimpleFIFO:
    def __init__(self):
        self._buf = []

    def put(self, item):
        self._buf.append(item)

    def get(self):
        if self._buf:
            return self._buf.pop(0)
        return None

    def empty(self):
        return len(self._buf) == 0

# ─── Buttons ──────────────────────────────────────────────────────
BTN_MENU  = Pin('X20', Pin.IN, Pin.PULL_UP)
BTN_UP    = Pin('X21', Pin.IN, Pin.PULL_UP)
BTN_DOWN  = Pin('X19', Pin.IN, Pin.PULL_UP)
BTN_ENTER = Pin('X18', Pin.IN, Pin.PULL_UP)

def keypoll():
    return {
        "MENU": BTN_MENU.value() == 0,
        "ENT":  BTN_ENTER.value() == 0,
        "UP":   BTN_UP.value() == 0,
        "DOWN": BTN_DOWN.value() == 0,
    }

# ─── Safe LCD line helper ─────────────────────────────────────────
async def lcd_line(lcd, row, text):
    try:
        await lcd.set_cursor(row, 0)
        await lcd.write_string((str(text) + " " * 20)[:20])
    except Exception as e:
        # LCD not ready / transient I2C glitch (ignore)
        # print("LCD glitch:", e)
        return

# ─── Menu items ───────────────────────────────────────────────────
MENU_ITEMS = [
    "Precharge Test",
    "Crank Engine",
    "PID Regen",
    "BMS Data",
    "ECU Data",
    "Inverter Data",
    "Diagnostics",
]

# ─── Display routines ─────────────────────────────────────────────
async def show_status(lcd):
    try:
        s = DATA.snapshot()
        (state, uptime_s, rpm, temp, map_kpa, iat,
         dc_v, batt_v, batt_i, torque, power,
         fault, last_emcy) = s

        names = ["WAIT", "CRANK", "COAST", "REGEN"]
        state_txt = names[state] if state < len(names) else "UNK"

        await lcd_line(lcd, 0, f"PMU:{state_txt:<5} Tq:{torque:>4.0f}")
        await lcd_line(lcd, 1, f"RPM:{rpm:>5d}  PWR:{power/1000:>4.1f}kW")
        await lcd_line(lcd, 2, f"Vb:{batt_v:>5.1f}V Ib:{batt_i:>4.0f}A")
        await lcd_line(lcd, 3, f"FLT:{fault:<3} EMCY:{last_emcy:02X}")

    except Exception as e:
        # never crash UI
        # print("UI status error:", e)
        pass

async def show_menu(lcd, index):
    await lcd_line(lcd, 0, "   PMU MENU")
    for i in range(3):
        line = index + i
        prefix = ">" if i == 0 else " "
        text = f"{prefix} {MENU_ITEMS[line]}" if line < len(MENU_ITEMS) else ""
        await lcd_line(lcd, i + 1, text)

# ─── Button scanning task ─────────────────────────────────────────
async def button_task(btn_q):
    last = {"MENU":0, "UP":0, "DOWN":0, "ENT":0}

    while True:
        k = keypoll()
        if k["MENU"] and not last["MENU"]:
            btn_q.put("m")
        if k["UP"] and not last["UP"]:
            btn_q.put("u")
        if k["DOWN"] and not last["DOWN"]:
            btn_q.put("d")
        if k["ENT"] and not last["ENT"]:
            btn_q.put("e")
        last = k
        await asyncio.sleep_ms(40)

# ─── Main UI Coroutine ────────────────────────────────────────────
async def ui_task(lcd):
    print("ui_task entered, lcd=", lcd)

    # Allow LCD driver to become ready
    await asyncio.sleep_ms(300)

    btn_q = SimpleFIFO()
    asyncio.create_task(button_task(btn_q))

    in_menu = False
    menu_index = 0

    while True:
        # Refresh screen
        if in_menu:
            await show_menu(lcd, menu_index)
        else:
            await show_status(lcd)

        # Handle button events
        while not btn_q.empty():
            b = btn_q.get()

            if b == "m":
                in_menu = not in_menu
                await lcd.clear_screen()

            elif in_menu:
                if b == "u" and menu_index > 0:
                    menu_index -= 1
                elif b == "d" and menu_index < len(MENU_ITEMS)-1:
                    menu_index += 1
                elif b == "e":
                    sel = MENU_ITEMS[menu_index]
                    await lcd.clear_screen()
                    await lcd_line(lcd, 0, f"Run: {sel}")
                    in_menu = False
                    menu_index = 0
                    # UI won't crash even if routine errors
                    asyncio.create_task(_run_mode(sel, lcd))

        await asyncio.sleep_ms(200)

# separate routine runner
async def _run_mode(sel, lcd):
    try:
        if sel == "Precharge Test":
            from pmu_preactor_standalone import run as pre
            await pre(DATA, CAN1, lcd)
        elif sel == "Crank Engine":
            from pmu_crank_io import run as crank
            await crank(DATA, CAN1, lcd)
        elif sel == "PID Regen":
            from pmu_pid_regen import run as pid
            await pid(CAN1, DATA, lcd(lcd))
    except Exception as e:
        print("UI mode error:", sel, e)
