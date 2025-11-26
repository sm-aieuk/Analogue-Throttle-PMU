# pmu_ui.py — Async LCD UI with working buttons + menus
import uasyncio as asyncio
from machine import Pin
import pmu_config
from pmu_config import DATA


from pmu_config import (
    DATA,
    STATE_WAITING,
    STATE_PRECHARGE,
    STATE_CRANK,
    STATE_COAST,
    STATE_REGEN
)


# --------------------------------------------------------------------
# SimpleQueue (because MicroPython has no asyncio.Queue)
# --------------------------------------------------------------------
class SimpleQueue:
    def __init__(self):
        self.buf = []

    async def put(self, item):
        self.buf.append(item)

    async def get(self):
        if self.buf:
            return self.buf.pop(0)
        return None

    def empty(self):
        return len(self.buf) == 0


# --------------------------------------------------------------------
# Button pins
# --------------------------------------------------------------------
BTN_MENU  = Pin('X20', Pin.IN, Pin.PULL_UP)
BTN_UP    = Pin('X21', Pin.IN, Pin.PULL_UP)
BTN_DOWN  = Pin('X19', Pin.IN, Pin.PULL_UP)
BTN_ENTER = Pin('X18', Pin.IN, Pin.PULL_UP)


# --------------------------------------------------------------------
# Button polling → queue
# --------------------------------------------------------------------
async def button_task(q):
    last = {"m":1, "u":1, "d":1, "e":1}

    while True:
        m = BTN_MENU.value()
        u = BTN_UP.value()
        d = BTN_DOWN.value()
        e = BTN_ENTER.value()

        if m == 0 and last["m"] == 1:
            await q.put("m")
        if u == 0 and last["u"] == 1:
            await q.put("u")
        if d == 0 and last["d"] == 1:
            await q.put("d")
        if e == 0 and last["e"] == 1:
            await q.put("e")

        last["m"] = m
        last["u"] = u
        last["d"] = d
        last["e"] = e

        await asyncio.sleep_ms(40)


# --------------------------------------------------------------------
# Local formatting helpers
# --------------------------------------------------------------------
def pad(s, width=20):
    s = str(s)
    if len(s) < width:
        return s + (" " * (width - len(s)))
    return s[:width]


def fmt(label, value, unit=""):
    return f"{label}{value}{unit}"


# --------------------------------------------------------------------
# Status Screen
# --------------------------------------------------------------------
async def show_status(lcd):

    await lcd.clear_screen()

    await lcd.set_cursor(0, 0)
    await lcd.write_string(pad("PMU:" + DATA.state_txt))

    await lcd.set_cursor(1, 0)
    await lcd.write_string(pad("Batt:" + f"{DATA.battery_v:.1f}V"))

    await lcd.set_cursor(2, 0)
    await lcd.write_string(pad("Load:" + f"{DATA.load_i:.1f}A"))

    await lcd.set_cursor(3, 0)
    await lcd.write_string(pad("Chg:" + f"{DATA.battery_i:.1f}A"))

# async def show_status(lcd):
#     s = DATA.snapshot()
#     (state, uptime_s, rpm, temp, map_kpa, iat,
#      dc_v, batt_v, batt_i, torque, power,
#      fault, last_emcy) = s
# 
#     names = ["WAIT", "CRANK", "COAST", "REGEN"]
#     state_txt = names[state] if state < len(names) else "UNK"
# 
#     await lcd_line(0, f"PMU:{state_txt:<5} Tq:{torque:>4.0f}Nm")
#     await lcd_line(1, f"RPM:{rpm:>5d}  PWR:{power/1000:>4.1f}kW")
#     await lcd_line(2, f"Vb:{batt_v:>5.1f}V Ib:{batt_i:>4.0f}A")
#     await lcd_line(3, f"FLT:{fault:<5} EMCY:{last_emcy:02X}")
# --------------------------------------------------------------------
# Menu
# --------------------------------------------------------------------
MENU = [
    "Precharge",
    "Crank Engine",
    "PID Regen",
]

async def show_menu(lcd, index):
    print("Showing Menu")
    await lcd.clear_screen()
    await lcd.set_cursor(0, 0)
    await lcd.write_string("Select Mode:")

    for i, name in enumerate(MENU):
        prefix = "> " if i == index else "  "
        await lcd.set_cursor(i+1, 0)
        await lcd.write_string(pad(prefix + name))


# --------------------------------------------------------------------
# UI Task
# --------------------------------------------------------------------
async def ui_task(lcd):
    print("UI task started — lcd =", lcd)

    # UI local state
    menu_active = False
    menu_index = 0

    # Queue for keypresses
    q = SimpleQueue()
    asyncio.create_task(button_task(q))

    DATA.ui_mode = STATE_WAITING

    # Draw initial status screen
    await show_status(lcd)
    DATA.ui_needs_update = False

    while True:

        # FSM requests status-screen update
        if DATA.ui_needs_update and not menu_active:
            await show_status(lcd)
            DATA.ui_needs_update = False

        # Get next button event
        evt = await q.get()
        if evt is None:
            await asyncio.sleep_ms(20)
            continue

        # ---------- MENU BUTTON ----------
        if evt == "m":
            menu_active = not menu_active

            if menu_active:
                DATA.ui_mode = STATE_PRECHARGE  # not used, but stored
                await show_menu(lcd, menu_index)
            else:
                DATA.ui_mode = STATE_WAITING
                await show_status(lcd)
                DATA.ui_needs_update = False
            continue

        # ---------- MENU NAVIGATION ----------
        if menu_active:

            if evt == "u":
                menu_index = (menu_index - 1) % len(MENU)
                await show_menu(lcd, menu_index)

            elif evt == "d":
                menu_index = (menu_index + 1) % len(MENU)
                await show_menu(lcd, menu_index)

            elif evt == "e":
                # Send command to FSM
                if menu_index == 0:
                    DATA.state = STATE_PRECHARGE
                elif menu_index == 1:
                    DATA.state = STATE_CRANK
                elif menu_index == 2:
                    DATA.state = STATE_REGEN

                # Exit menu
                menu_active = False
                DATA.ui_mode = STATE_WAITING
                DATA.ui_needs_update = True
                continue

        await asyncio.sleep_ms(20)
