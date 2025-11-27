# pmu_ui.py — Async LCD UI with working buttons + menus
import uasyncio as asyncio
from machine import Pin
import pmu_config
from pmu_config import DATA
import utime as time


from pmu_config import (
    DATA,
    STATE_WAITING,
    STATE_PRECHARGE,
    STATE_CRANK,
    STATE_COAST,
    STATE_REGEN,
    UI_MODE_LCD
)

last_update_ms = 0
UPDATE_INTERVAL_MS = 250   # 4Hz refresh

# UI mode constants
UI_MODE_STATUS     = 0
UI_MODE_MENU       = 1
UI_MODE_LCD        = 2
UI_MODE_PRECHARGE  = 3
UI_MODE_CRANK      = 4
UI_MODE_PID        = 5


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
# Precharge Screen
# --------------------------------------------------------------------
async def show_precharge_screen(lcd):
    await lcd.clear_screen()

    # Line 0: title + current FSM state text
    await lcd.set_cursor(0, 0)
    await lcd.write_string(pad("MODE: PRECHG - " + DATA.state_txt))

    # Line 1: DC-link voltage
    await lcd.set_cursor(1, 0)
    await lcd.write_string(pad("Vdc: %.1fV" % DATA.dc_bus_v))

    # Line 2: inverter online + fault flag
    inv_txt = "ON" if getattr(DATA, "gen4_online", False) else "OFF"
    flt_txt = "FLT" if getattr(DATA, "fault_active", False) else "OK"
    await lcd.set_cursor(2, 0)
    await lcd.write_string(pad("Inv:%s  %s" % (inv_txt, flt_txt)))

    # Line 3: last EMCY code
    code = getattr(DATA, "last_emcy_code", 0) & 0xFFFF
    await lcd.set_cursor(3, 0)
    await lcd.write_string(pad("EMCY:%04X" % code))


# --------------------------------------------------------------------
# Crank Screen
# --------------------------------------------------------------------
async def show_crank_screen(lcd):
    await lcd.clear_screen()

    # Line 0: title + current FSM state text
    await lcd.set_cursor(0, 0)
    await lcd.write_string(pad("MODE: CRANK - " + DATA.state_txt))

    # Line 1: RPM and torque
    rpm = int(getattr(DATA, "velocity", 0))
    tq  = int(getattr(DATA, "torque_act", 0))
    await lcd.set_cursor(1, 0)
    await lcd.write_string(pad("RPM:%5d Tq:%3d" % (rpm, tq)))

    # Line 2: "crank current" from id_target
    icrk = float(getattr(DATA, "id_target", 0.0))
    await lcd.set_cursor(2, 0)
    await lcd.write_string(pad("Icrk: %.1fA" % icrk))

    # Line 3: fault + EMCY
    flt_txt = "FLT" if getattr(DATA, "fault_active", False) else "OK"
    code = getattr(DATA, "last_emcy_code", 0) & 0xFFFF
    await lcd.set_cursor(3, 0)
    await lcd.write_string(pad("%s EMCY:%04X" % (flt_txt, code)))



async def show_pid_screen(lcd):
    await lcd.clear_screen()
    await lcd.set_cursor(0, 0)
    await lcd.write_string("MODE: PID REGEN")

    await lcd.set_cursor(1, 0)
    await lcd.write_string(f"DC: {DATA.dc_bus_v:5.1f}V")

    await lcd.set_cursor(2, 0)
    await lcd.write_string(f"Ibatt: {DATA.battery_i:5.1f}A")

    await lcd.set_cursor(3, 0)
    await lcd.write_string(f"Set:{DATA.pid_setpoint:4.1f}V")



async def show_lcd_settings(lcd, contrast, backlight):
    await lcd.clear_screen()
    await lcd.set_cursor(0, 0)
    await lcd.write_string("LCD Settings")

    await lcd.set_cursor(1, 0)
    await lcd.write_string(pad(f"Contrast: {contrast:3d}"))

    await lcd.set_cursor(2, 0)
    await lcd.write_string(pad(f"Backlight: {backlight:2d}"))

    await lcd.set_cursor(3, 0)
    await lcd.write_string("Up/Down: Adjust  Enter:Exit")

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
    "LCD Settings",
    "Back",
]

async def show_menu(lcd, menu, index, top):
    await lcd.clear_screen()

    # Line 0: title
    await lcd.set_cursor(0, 0)
    await lcd.write_string("Menu:")

    # Lines 1–3: window of 3 items
    for i in range(top, min(top + 3, len(menu))):
        y = (i - top) + 1   # shift down by 1 row for title
        await lcd.set_cursor(y, 0)

        prefix = ">" if i == index else " "
        await lcd.write_string(prefix + menu[i][:19])

async def show_lcd_contrast(lcd, contrast):
    await lcd.clear_screen()
    await lcd.set_cursor(0, 0)
    await lcd.write_string("LCD: Contrast")

    await lcd.set_cursor(1, 0)
    await lcd.write_string(f"Level: {contrast:3d}")

    await lcd.set_cursor(3, 0)
    await lcd.write_string("UP/DN=Adj  ENT=Next")

async def show_lcd_backlight(lcd, backlight):
    await lcd.clear_screen()
    await lcd.set_cursor(0, 0)
    await lcd.write_string("LCD: Backlight")

    await lcd.set_cursor(1, 0)
    await lcd.write_string(f"Level: {backlight:2d}")

    await lcd.set_cursor(3, 0)
    await lcd.write_string("UP/DN=Adj  ENT=Exit")




# --------------------------------------------------------------------
# UI Task
# --------------------------------------------------------------------
async def ui_task(lcd):
    print("UI task started — lcd =", lcd)

    # UI local state
    menu_active = False
    menu_index = 0
    # UI refresh throttle
    last_update_ms = time.ticks_ms()
    LCD_MENU_INDEX = 4  # (4th item)
    menu_top = 0        # top visible index in the 4-line window
    MENU_LINES = 3
    lcd_page = 0     # 0: contrast, 1: backlight

    # Queue for keypresses
    q = SimpleQueue()
    asyncio.create_task(button_task(q))

    DATA.ui_mode = STATE_WAITING

    # Draw initial status screen
    await show_status(lcd)
    DATA.ui_needs_update = False

    while True:

        # FSM requests screen update (rate-limited)
        # FSM/UI-triggered repaint (rate-limited)
        now = time.ticks_ms()
        if (
            DATA.ui_needs_update
            and not menu_active
            and time.ticks_diff(now, last_update_ms) >= UPDATE_INTERVAL_MS
        ):
            #print("Repaint")

            if DATA.ui_mode == UI_MODE_PRECHARGE:
                await show_precharge_screen(lcd)

            elif DATA.ui_mode == UI_MODE_CRANK:
                await show_crank_screen(lcd)

            elif DATA.ui_mode == UI_MODE_PID:
                await show_pid_screen(lcd)

            elif DATA.ui_mode == UI_MODE_LCD:
                await show_lcd_settings(lcd, DATA.lcd_contrast, DATA.lcd_backlight)

            else:
                # UI_MODE_STATUS
                await show_status(lcd)

            DATA.ui_needs_update = False
            last_update_ms = now




        # Get next button event
        evt = await q.get()
        if evt is None:
            await asyncio.sleep_ms(20)
            continue

        # ---------- MENU BUTTON (GLOBAL) ----------
        # Ignore menu toggle while in task-specific screens
        if evt == "m" and DATA.ui_mode in (UI_MODE_STATUS, UI_MODE_MENU, UI_MODE_LCD):

            menu_active = not menu_active

            if menu_active:
                # entering menu
                menu_index = 0
                menu_top = 0
                DATA.ui_mode = UI_MODE_MENU
                await show_menu(lcd, MENU, menu_index, menu_top)
            else:
                # exiting menu
                DATA.ui_mode = UI_MODE_STATUS
                await lcd.clear_screen()
                await show_status(lcd)
                DATA.ui_needs_update = False

            continue



        # ---------- MENU NAVIGATION ----------
        if menu_active:

            # UP
            if evt == "u":
                if menu_index > 0:
                    menu_index -= 1

                    # scroll window up if needed
                    if menu_index < menu_top:
                        menu_top -= 1

                await show_menu(lcd, MENU, menu_index, menu_top)

            # DOWN
            elif evt == "d":
                if menu_index < len(MENU) - 1:
                    menu_index += 1

                    # scroll window down if needed
                    if menu_index >= menu_top + MENU_LINES:
                        menu_top += 1

                await show_menu(lcd, MENU, menu_index, menu_top)

            # ENTER
                        # ENTER
            elif evt == "e":
                selection = MENU[menu_index]

                if selection == "Back":
                    # exit menu entirely
                    menu_active = False
                    await lcd.clear_screen()
                    await show_status(lcd)
                    DATA.ui_needs_update = False
                    continue

                elif selection == "LCD Settings":
                    menu_active = False
                    DATA.ui_mode = UI_MODE_LCD
                    await lcd.clear_screen()
                    await show_lcd_settings(lcd, DATA.lcd_contrast, DATA.lcd_backlight)
                    continue

                elif selection == "Precharge":
                    #DATA.state = STATE_PRECHARGE
                    DATA.ui_mode = UI_MODE_PRECHARGE
                    menu_active = False
                    await show_precharge_screen(lcd)
                    DATA.ui_needs_update = True
                    continue

                elif selection == "Crank Engine":
                    #DATA.state = STATE_CRANK
                    DATA.ui_mode = UI_MODE_CRANK
                    menu_active = False
                    await show_crank_screen(lcd)
                    DATA.ui_needs_update = True
                    continue

                elif selection == "PID Regen":
                    menu_active = False
                    DATA.ui_mode = UI_MODE_PID
                    await lcd.clear_screen()
                    await show_pid_screen(lcd)
                    DATA.ui_needs_update = False
                    continue


# LCD Mode
        if DATA.ui_mode == UI_MODE_LCD:       

            # UP = increase
            if evt == "u":
                if lcd_page == 0:
                    DATA.lcd_contrast = min(255, DATA.lcd_contrast + 5)
                    await lcd.set_contrast(DATA.lcd_contrast)
                    await show_lcd_contrast(lcd, DATA.lcd_contrast)

                elif lcd_page == 1:
                    DATA.lcd_backlight = min(8, DATA.lcd_backlight + 1)
                    await lcd.set_backlight(DATA.lcd_backlight)
                    await show_lcd_backlight(lcd, DATA.lcd_backlight)

            # DOWN = decrease
            elif evt == "d":
                if lcd_page == 0:
                    DATA.lcd_contrast = max(0, DATA.lcd_contrast - 5)
                    await lcd.set_contrast(DATA.lcd_contrast)
                    await show_lcd_contrast(lcd, DATA.lcd_contrast)

                elif lcd_page == 1:
                    DATA.lcd_backlight = max(0, DATA.lcd_backlight - 1)
                    await lcd.set_backlight(DATA.lcd_backlight)
                    await show_lcd_backlight(lcd, DATA.lcd_backlight)

            # ENTER = next page
            elif evt == "e":
                if lcd_page == 0:
                    # Go to backlight page
                    lcd_page = 1
                    await show_lcd_backlight(lcd, DATA.lcd_backlight)

                elif lcd_page == 1:
                    # EXIT + SAVE
                    DATA.save_settings()
                    DATA.ui_mode = UI_MODE_STATUS
                    await lcd.clear_screen()
                    await show_status(lcd)
                continue

            # MENU always exits
            if evt == "m":
                DATA.ui_mode = UI_MODE_STATUS
                await lcd.clear_screen()
                await show_status(lcd)

# ===== PRECHARGE MODE =====
        if DATA.ui_mode == UI_MODE_PRECHARGE:

            # Refresh screen every 250ms
            now = time.ticks_ms()
            if time.ticks_diff(now, last_update_ms) > 250:
                await show_precharge_screen(lcd)
                last_update_ms = now

            # ENTER = start precharge
            if evt == "e":
                DATA.state = STATE_PRECHARGE
                # Let FSM run independently
                continue

            # MENU = exit screen
            if evt == "m":
                DATA.state = STATE_WAITING
                DATA.ui_mode = UI_MODE_STATUS
                await lcd.clear_screen()
                await show_status(lcd)
                continue

# ===== CRANK MODE =====
        if DATA.ui_mode == UI_MODE_CRANK:

            now = time.ticks_ms()
            if time.ticks_diff(now, last_update_ms) > 250:
                await show_crank_screen(lcd)
                last_update_ms = now

            if evt == "e":
                DATA.state = STATE_CRANK
                continue

            if evt == "m":
                DATA.state = STATE_WAITING
                DATA.ui_mode = UI_MODE_STATUS
                await lcd.clear_screen()
                await show_status(lcd)
                continue


# ===== PID MODE =====
        if DATA.ui_mode == UI_MODE_PID:

            now = time.ticks_ms()
            if time.ticks_diff(now, last_update_ms) > 250:
                await show_pid_screen(lcd)
                last_update_ms = now

            # Adjust setpoint with UP/DOWN
            if evt == "u":
                DATA.pid_setpoint = min(100.0, DATA.pid_setpoint + 0.5)
                await show_pid_screen(lcd)

            if evt == "d":
                DATA.pid_setpoint = max(0.0, DATA.pid_setpoint - 0.5)
                await show_pid_screen(lcd)

            # ENTER = start PID loop
            if evt == "e":
                DATA.regen_abort = False
                DATA.state = STATE_REGEN
                continue

            # MENU = exit + save
            elif evt == "m":
                DATA.regen_abort = True       # <-- signal abort
                DATA.state = STATE_WAITING    # force FSM back to WAIT
                DATA.save_settings()
                DATA.ui_mode = UI_MODE_STATUS
                await lcd.clear_screen()
                await show_status(lcd)
                DATA.ui_needs_update = True
                continue





        await asyncio.sleep_ms(20)
