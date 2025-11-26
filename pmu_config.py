# pmu_config.py — global config + shared data for PMU
# ------------------------------------------------------
# Keep this tiny: constants + a single shared data object.

from micropython import const
from adc_manager import ADCManager

# ---- CAN / device addresses
CAN1_BAUD = const(500_000)   # Inverter & ECU bus
CAN2_BAUD = const(500_000)   # Customer bus (telemetry)
NODE_ID_INVERTER = const(0x01)
NODE_ID_ECU      = const(0x02)
NODE_ID_BMS      = const(0x03)

# ---- Logging
LOG_TO_SD = True
LOG_DIR = "/sd"
LOG_PERIOD_HZ = const(1)  # 1Hz CSV logging

# ---- Display
LCD_COLS = const(20)
LCD_ROWS = const(4)

# ---- Startup behaviour
RUN_SPEEDTEST_AT_BOOT = False

# ---- PMU state machine
STATE_WAITING = const(0)
STATE_CRANK   = const(1)
STATE_COAST   = const(2)
STATE_REGEN   = const(3)
STATE_PRECHARGE = const(4)


# ======================================================
# Shared data structure (used across whole PMU system)
# ======================================================
class PMUData:
    __slots__ = (
        # Common
        "state", "uptime_s",

        # Engine
        "engine_rpm", "engine_temp_c",
        "map_kpa", "iat_c",

        # Power
        "dc_bus_v", "battery_v", "battery_i",
        "gen_torque_nm", "gen_power_w",

        # Inverter TPDO data
        "id_target", "iq_target",
        "id_actual", "iq_actual",

        "ud", "uq", "mod", "cap_v",

        "motor_temp", "batt_current", "load_i", "charge_i", "spare_i",
        "torque_cmd", "torque_act",
        "sevcon_rpm", "regen_pct",

        "vel_max", "velocity",

        # Inverter status flags
        "fault_active", "last_emcy_code",

        # ---- NEW FIELDS REQUIRED BY CAN DECODER ----
        "sync_seen",         # Sync frame seen?
        "gen4_online",       # Heartbeat present?
        "gen4_last_emcy_ms", # Timestamp of EMCY
        "gen4_emcy",         # Last EMCY code

        # Subsystems
        "adc_mgr",           # ADS1115 manager
        "lcd",               # LCD object
        "logger",            # SD logger

        # Timestamps
        "gen4_last_hb_ms",
        "gen4_last_pdo_ms",
        
        #Locks
        "ui_needs_update",
        "ui_selected",
        "ui_mode",
        "ui_button",
        "state_txt",
    )

    # ---------------------------------------------------
    def __init__(self):
        self.state = STATE_WAITING
        self.uptime_s = 0

        # Engine
        self.engine_rpm = 0
        self.engine_temp_c = 0
        self.map_kpa = 0
        self.iat_c = 0

        # Power
        self.dc_bus_v = 0
        self.battery_v = 0
        self.battery_i = 0
        self.load_i = 0
        self.charge_i =0
        self.spare_i = 0
        self.gen_torque_nm = 0
        self.gen_power_w = 0
        self.regen_pct = 0

        # TPDO fields
        self.id_target = 0
        self.iq_target = 0
        self.id_actual = 0
        self.iq_actual = 0

        self.ud = 0
        self.uq = 0
        self.mod = 0
        self.cap_v = 0

        self.motor_temp = 0
        self.batt_current = 0
        self.torque_cmd = 0
        self.torque_act = 0

        self.vel_max = 0
        self.velocity = 0
        self.sevcon_rpm = 0

        # Errors
        self.fault_active = 0
        self.last_emcy_code = 0

        # ---- NEW ----
        self.sync_seen = False
        self.gen4_online = False
        self.gen4_last_emcy_ms = 0
        self.gen4_emcy = None

        # Subsystems
        self.adc_mgr = ADCManager(self)
        self.lcd = None
        self.logger = None

        # Timestamps
        self.gen4_last_hb_ms = 0
        self.gen4_last_pdo_ms = 0
        
        #Locks
        self.ui_needs_update = False   # LCD should refresh next loop
        self.ui_selected = 0           # Menu selected row
        self.ui_mode = STATE_WAITING   # Current UI mode / screen
        self.ui_button = 0
        self.state_txt = "WAIT"

    def snapshot(self):
        return (
            self.state, self.uptime_s,
            self.engine_rpm, self.engine_temp_c,
            self.map_kpa, self.iat_c,
            self.dc_bus_v, self.battery_v,
            self.battery_i, self.gen_torque_nm,
            self.gen_power_w,
            self.fault_active, self.last_emcy_code
        )


# Global instance
DATA = PMUData()
