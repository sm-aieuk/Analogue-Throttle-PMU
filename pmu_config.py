
# pmu_config.py — global config + shared data for PMU
# Keep this tiny: constants + a single shared data object.

from micropython import const

# ---- CAN / device addresses (placeholders; adjust as needed)
CAN1_BAUD = const(500_000)   # Inverter & ECU bus
CAN2_BAUD = const(500_000)   # Customer bus (telemetry)
NODE_ID_INVERTER = const(0x01)
NODE_ID_ECU      = const(0x02)
NODE_ID_BMS      = const(0x03)

# ---- Logging
LOG_TO_SD = True
LOG_DIR = "/sd"
LOG_PERIOD_HZ = const(1)  # keep small for now

# ---- Display
LCD_COLS = const(20)
LCD_ROWS = const(4)

# ---- Startup behaviour
RUN_SPEEDTEST_AT_BOOT = False  # set True to run the known scratchpad test at boot

# ---- PMU state machine states
STATE_WAITING = const(0)
STATE_CRANK   = const(1)
STATE_COAST   = const(2)
STATE_REGEN   = const(3)

# ---- Shared data hub (customer-oriented subset only for now)
class PMUData:
    __slots__ = (
        # common
        "state", "uptime_s",

        # engine
        "engine_rpm", "engine_temp_c",
        "map_kpa", "iat_c",

        # power
        "dc_bus_v", "battery_v", "battery_i",
        "gen_torque_nm", "gen_power_w",

        # inverter TPDO fields
        "id_target", "iq_target",
        "id_actual", "iq_actual",

        "ud", "uq", "mod", "cap_v",

        "motor_temp", "batt_current",
        "torque_cmd", "torque_act",

        "vel_max", "velocity",

        # flags
        "fault_active", "last_emcy_code",
    )

    def __init__(self):
        self.state = STATE_WAITING
        self.uptime_s = 0

        self.engine_rpm = 0
        self.engine_temp_c = 0
        self.map_kpa = 0
        self.iat_c = 0

        self.dc_bus_v = 0
        self.battery_v = 0
        self.battery_i = 0
        self.gen_torque_nm = 0
        self.gen_power_w = 0
        
        # inverter TPDO data
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

        self.fault_active = 0
        self.last_emcy_code = 0

    def snapshot(self):
        # return a tuple of the minimal public telemetry
        return (
            self.state, self.uptime_s,
            self.engine_rpm, self.engine_temp_c, self.map_kpa, self.iat_c,
            self.dc_bus_v, self.battery_v, self.battery_i, self.gen_torque_nm, self.gen_power_w,
            self.fault_active, self.last_emcy_code,
        )

# Single shared instance that all modules import
DATA = PMUData()
