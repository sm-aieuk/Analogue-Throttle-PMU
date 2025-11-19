# pmu_ui.py — PMU status + menu UI (for async LCD + keypad)
# --------------------------------------------------------------------
import uasyncio as asyncio
from machine import Pin
import sys
from pmu_config import DATA
from pmu_can import can1, can2   # ← shared CAN objects, no pmu_main import

# ─── Buttons ──────────────────────────────────────────────────────────
BTN_MENU  = Pin('X20', Pin.IN, Pin.PULL_UP)
BTN_UP    = Pin('X21', Pin.IN, Pin.PULL_UP)
BTN_DOWN  = Pin('X19', Pin.IN, Pin.PULL_UP)
BTN_ENTER = Pin('X18', Pin.IN, Pin.PULL_UP)

# ─── Helpers ──────────────────────────────────────────────────────────
def pad20(s):
    s = str(s)
    return (s + ' ' * 20)[:20]

async def lcd_line(lcd, row, text):
    await lcd.set_cursor(row, 0)
    await lcd.write_string(pad20(text))

# ─── Key read helper ─────────────────────────────────────────────────
def keypoll():
    return {
        "MENU": BTN_MENU.value() == 0,
        "ENT":  BTN_ENTER.value() == 0,
        "UP":   BTN_UP.value() == 0,
        "DOWN": BTN_DOWN.value() == 0,
    }

# ─── Menu items ───────────────────────────────────────────────────────
MENU_ITEMS = [
    "Precharge Test",
    "Crank Engine",
    "PID Regen",
    "BMS Data",
    "ECU Data",
    "Inverter Data",
    "Diagnostics",
]

# ─── Display routines ─────────────────────────────────────────────────
async def show_status(lcd):
    s = DATA.snapshot()
    (state, uptime_s, rpm, temp, map_kpa, iat,
     dc_v, batt_v, batt_i, torque, power,
     fault, last_emcy) = s

    names = ["WAIT", "CRANK", "COAST", "REGEN"]
    state_txt = names[state] if state < len(names) else "UNK"

    await lcd_line(lcd, 0, f"PMU:{state_txt:<5} Tq:{torque:>4.0f}Nm")
    await lcd_line(lcd, 1, f"RPM:{rpm:>5d}  PWR:{power/1000:>4.1f}kW")
    await lcd_line(lcd, 2, f"Vb:{batt_v:>5.1f}V Ib:{batt_i:>4.0f}A")
    await lcd_line(lcd, 3, f"FLT:{fault:<5} EMCY:{last_emcy:02X}")

async def show_menu(lcd, index):
    await lcd_line(lcd, 0, "   PMU MENU")
    for i in range(3):
        line = index + i
        if line < len(MENU_ITEMS):
            prefix = ">" if i == 0 else " "
            await lcd_line(lcd, i + 1, f"{prefix} {MENU_ITEMS[line]}")
        else:
            await lcd_line(lcd, i + 1, "")

# ─── Small helper to force clean imports ──────────────────────────────
def _reload_modules(*names):
    for n in names:
        try:
            sys.modules.pop(n, None)
        except Exception:
            pass

# ─── Test wrappers (now using shared CAN1) ────────────────────────────
async def run_precharge(lcd):
    _reload_modules("pmu_preactor_gpio", "pmu_preactor_standalone")
    from pmu_preactor_standalone import run as pre_only
    await pre_only(can1, DATA, lcd=lcd, keypoll=keypoll)

async def run_crank(lcd):
    _reload_modules("pmu_preactor_gpio", "pmu_preactor_standalone", "pmu_crank")
    from pmu_crank import run as crank_run
    await crank_run(can1, lcd=lcd, keypoll=keypoll)

async def run_pid_regen(lcd):
    _reload_modules("pmu_preactor_gpio", "pmu_preactor_standalone", "pmu_pid_regen")
    from pmu_pid_regen import run as pid_run
    await pid_run(can1, DATA, lcd=lcd, keypoll=keypoll)



# ─── Main UI coroutine ────────────────────────────────────────────────
async def ui_task(lcd):
    print("ui_task entered, lcd=", lcd)
    btn_q = SimpleQueue()
    asyncio.create_task(button_task(btn_q))

    in_menu = False
    menu_index = 0
    refresh_ms = 250

    while True:
        if in_menu:
            await show_menu(lcd, menu_index)
        else:
            await show_status(lcd)

        while not btn_q.empty():
            b = await btn_q.get()
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
                    await lcd_line(lcd, 0, f"Running: {sel}")
                    print(f"UI: selected {sel}")

                    in_menu = False
                    try:
                        if sel == "Precharge Test":
                            await run_precharge(lcd)
                        elif sel == "Crank Engine":
                            print("UI: launching crank routine")
                            await run_crank(lcd)
                        elif sel == "PID Regen":
                            print("UI: launching PID regen routine")
                            await run_pid_regen(lcd)
                    except Exception as e:
                        print("UI: error in mode", sel, "→", e)

                    await lcd.clear_screen()
                    await lcd_line(lcd, 0, "PMU System Ready")
                    menu_index = 0
                    in_menu = False

        await asyncio.sleep_ms(refresh_ms)
