# pmu_can_decode.py — safe CAN frame decoder for Sevcon Gen4
# -----------------------------------------------------------
# This version is hardened for:
#  - Pyboard v1.1 CAN driver
#  - async ringbuffer reader
#  - missing PDOs during crank
#  - missing fields in DATA (all are now optional)
#
# All decode failures are caught and suppressed safely.

from pmu_config import DATA
import micropython
micropython.const

# ------------------------------------------------------------
# Utility: safe byte extraction
# ------------------------------------------------------------
def u16(b, i):
    return b[i] | (b[i+1] << 8)

def s16(b, i):
    v = b[i] | (b[i+1] << 8)
    if v & 0x8000:
        v = v - 0x10000
    return v

# ------------------------------------------------------------
# Frame handler
# (incoming frames are tuples: (can_id, data_bytes, timestamp_ms))
# ------------------------------------------------------------
def decode_frame(can_id, data, t_ms):

    # --------------------------------------------------------
    # Heartbeat — 0x701 + nodeid
    # --------------------------------------------------------
    if can_id == 0x701:
        DATA.gen4_online = True
        DATA.gen4_last_hb_ms = t_ms
        # state byte is data[0], but not needed here
        return

    # --------------------------------------------------------
    # EMCY — 0x081
    # --------------------------------------------------------
    if can_id == 0x081:
        if len(data) >= 2:
            code = data[0] | (data[1] << 8)
            DATA.last_emcy_code = code
            DATA.gen4_emcy = code
            DATA.gen4_last_emcy_ms = t_ms
            DATA.fault_active = 1
        return

    # --------------------------------------------------------
    # TPDO1 — 0x181
    # typically: velocity, torque, ID/IQ targets
    # --------------------------------------------------------
    if can_id == 0x181 and len(data) >= 8:
        # Known Sevcon mapping (common config)
        # 0–1 : velocity (rpm)
        # 2–3 : torque actual (0.1 Nm)
        # 4–5 : iq_actual (0.1 A)
        # 6–7 : iq_target (0.1 A)

        DATA.velocity = u16(data, 0)
        DATA.torque_act = s16(data, 2) / 10.0
        DATA.iq_actual = s16(data, 4) / 10.0
        DATA.iq_target = s16(data, 6) / 10.0

        DATA.gen4_last_pdo_ms = t_ms
        return

    # --------------------------------------------------------
    # TPDO2 — 0x281
    # typically: ud, uq, modulation index, DC-bus volts
    # --------------------------------------------------------
    if can_id == 0x281 and len(data) >= 8:
        DATA.ud = s16(data, 0) / 10.0
        DATA.uq = s16(data, 2) / 10.0
        DATA.mod = u16(data, 4) / 10.0
        DATA.dc_bus_v = u16(data, 6) / 10.0

        DATA.gen4_last_pdo_ms = t_ms
        return

    # --------------------------------------------------------
    # TPDO3 — 0x381
    # typically: motor temperature, capacitor voltage, etc.
    # --------------------------------------------------------
    if can_id == 0x381 and len(data) >= 8:
        # common Gen4 mapping:
        # 0–1 : motor temp * 0.1°C
        # 2–3 : batt current * 0.1A
        # 4–5 : capacitor voltage * 0.1V
        # 6–7 : unused or diag
        DATA.motor_temp = s16(data, 0) / 10.0
        DATA.batt_current = s16(data, 2) / 10.0
        DATA.cap_v = u16(data, 4) / 10.0

        DATA.gen4_last_pdo_ms = t_ms
        return

    # -------------------------------------------------------------------------
    # TPDO5 – Actual Velocity (COB-ID 0x154)
    # -------------------------------------------------------------------------
    if can_id == 0x154:
        # Expect 8 bytes:
        #  [0..3] = Max velocity  (unused)
        #  [4..7] = Actual velocity (int32 signed)
        if len(data) >= 8:
            try:
                # MicroPython requires positional args only
                vel_raw = int.from_bytes(data[4:8], "little", True)
                DATA.sevcon_rpm = vel_raw
                #print(DATA.sevcon_rpm)

            except Exception as e:
                print("TPDO5 decode error:", e)
        return



    # --------------------------------------------------------
    # Sync — 0x000
    # (not always used)
    # --------------------------------------------------------
    if can_id == 0x000:
        DATA.sync_seen = True
        return

    # ignore all other IDs safely
    return
