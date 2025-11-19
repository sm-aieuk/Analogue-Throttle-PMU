# async_can_dual.py  (adds heartbeat tracking)
from pyb import CAN
import uasyncio as asyncio

GEN4_VBUS_SCALE = 0.04  # 0.04 V/LSB for 150 V systems


def _u16(b, o):
        return b[o] | (b[o+1] << 8)

def _s16(b, o):
        v = b[o] | (b[o+1] << 8)
        return v - 65536 if (v & 0x8000) else v

def _s32(b, o):
        v = (b[o] | (b[o+1] << 8) |
             (b[o+2] << 16) | (b[o+3] << 24))
        return v if v < 0x80000000 else v - 0x100000000

class SimpleQueue:
    def __init__(self):
        self._buf = []
    async def put(self, item):
        self._buf.append(item)
    async def get(self):
        while not self._buf:
            await asyncio.sleep_ms(5)
        return self._buf.pop(0)
    def empty(self):
        return not self._buf

class AsyncCANPort:
    def __init__(self, bus_id, debug=False, hwcan=None, **kwargs):
        self.bus_id = int(bus_id)
        self._debug = bool(debug)

        # ✅ Use provided hardware CAN instance if given, otherwise create one
        # ✅ Allow external hardware handle binding (from pmu_can)
        self._can = None
        if hwcan is not None:
            self._can = hwcan
        else:
            self._can = CAN(self.bus_id, CAN.NORMAL)
            self._can.init(
                CAN.NORMAL,
                prescaler=6,
                bs1=11,
                bs2=2,
                sjw=1,
                auto_restart=True
            )


        # Explicit catch-all filter → FIFO 0
        self._can.setfilter(0, CAN.MASK16, 0, (0, 0, 0, 0))

        # Async receive queue and heartbeat cache
        self.queue = SimpleQueue()
        self._last_hb = {}

        # Start RX task
        asyncio.create_task(self._rx_task())

    async def nmt_start(self, node_id=1):
        """
        Send CANopen NMT 'Start Remote Node'.
        NMT frames always use CAN-ID 0x000 and are 2 bytes long:
        byte0 = command (0x01 = start)
        byte1 = node-id
        """
        frame = bytes([0x01, node_id])
        try:
            # Pyboard CAN API: send(data, id)
            self._can.send(frame, 0x000)
            if self._debug:
                print(f"[CAN{self.bus_id}] NMT Start sent to node {node_id}")
        except Exception as e:
            print("⚠️ NMT start failed:", e)

        # allow time for node to transition
        await asyncio.sleep_ms(10)


    async def start(self):
        return

    def _handle_pdo(self, can_id, data):


        #print("PDO HIT:", hex(can_id))


        # TPDO1 – Id / Iq target + actual
        if can_id == 0x181:
            DATA.id_target  = _s16(data, 0)
            DATA.iq_target  = _s16(data, 2)
            DATA.id_actual  = _s16(data, 4)
            DATA.iq_actual  = _s16(data, 6)
            return

        # TPDO2 – Ud / Uq / ModIndex / Cap Voltage
        if can_id == 0x281:
            DATA.ud    = _s16(data, 0)
            DATA.uq    = _s16(data, 2)
            DATA.mod   = _s16(data, 4)

            cap = _u16(data, 6)
            DATA.cap_v = cap
            DATA.dc_bus_v = cap     # <- needed by precharge & crank
            return

        # TPDO3 – Torque + Current feedback (your async decoder handles this too)
        if can_id == 0x381:
            DATA.torque_cmd   = _s16(data, 0)
            DATA.torque_act   = _s16(data, 2)
            DATA.batt_current = _s16(data, 6)
            return

        # TPDO4 – Motor Temp / Battery Current / Torque Cmd-Act
        if can_id == 0x481:
            DATA.motor_temp   = _s16(data, 0)
            DATA.batt_current = _s16(data, 2)
            DATA.torque_cmd   = _s16(data, 4)
            DATA.torque_act   = _s16(data, 6)
            return

        # TPDO5 – Velocity + Velocity Limit (default Gen4 mapping)
        if can_id == 0x541:
            DATA.vel_max  = _s32(data, 0)
            DATA.velocity = _s32(data, 4)
            return



    async def _rx_task(self):
        print(f"[CAN{self.bus_id}] RX task started")
        while True:
            try:
                if self._can.any(0):
                    rx = self._can.recv(0)
                elif self._can.any(1):
                    rx = self._can.recv(1)
                else:
                    await asyncio.sleep_ms(2)
                    continue

                # --- Unpack safely ---
                can_id, is_ext, is_rtr, fmi, data = rx

                # Some firmwares sometimes return None or empty list for data
                if not data:
                    if self._debug:
                        print(f"[CAN{self.bus_id}] Empty data for ID {hex(can_id)}")
                    await asyncio.sleep_ms(1)
                    continue

                # Convert to bytes (handles bytearray, list, memoryview)
                if not isinstance(data, (bytes, bytearray)):
                    data_b = bytes(data)
                else:
                    data_b = data

                # Debug print
                if self._debug:
                    print(f"RX = {hex(can_id)} len={len(data_b)} data={data_b}")

                # --- PDO hook (ONLY CAN1) ---
                # Route PDO frames ONLY on CAN1
                if self.bus_id == 1:
                    self._handle_pdo(can_id, data_b)

                # Heartbeat tracking
                if 0x700 <= can_id <= 0x77F and data_b:
                    self._last_hb[can_id - 0x700] = data_b[0]

                # Push into async queue
                await self.queue.put({"id": int(can_id), "data": data_b})

            except Exception as e:
                if self._debug:
                    print(f"[CAN{self.bus_id} RX] error:", e)

            await asyncio.sleep_ms(2)


    async def recv(self):
        return await self.queue.get()

    def get_last_heartbeat(self, node_id=1):
        """★ NEW: return last heartbeat byte seen for node (or None)."""
        return self._last_hb.get(int(node_id))

    def send(self, data, can_id, timeout=0):
        if isinstance(can_id, (bytes, bytearray, list, tuple)) and isinstance(data, int):
            data, can_id = can_id, data
        try:
            if isinstance(data, (list, tuple)):
                if len(data) == 1 and isinstance(data[0], (bytes, bytearray, list, tuple)):
                    data = data[0]
                data = bytes(int(b) & 0xFF for b in data)
            elif isinstance(data, bytearray):
                data = bytes(data)
            elif isinstance(data, memoryview):
                data = bytes(data)
            elif not isinstance(data, (bytes,)):
                raise TypeError(f"data must be bytes/bytearray/list/tuple, not {type(data)}")
            if not isinstance(can_id, int):
                can_id = int(can_id)
            if len(data) > 8:
                raise ValueError("CAN frame > 8 bytes")
            self._can.send(data, can_id, timeout=timeout)
            if self._debug:
                print(f"[CAN{self.bus_id} TX] {hex(can_id)} → "
                      f"{' '.join('%02X' % x for x in data)}")
        except OSError as e:
            if e.args and e.args[0] == 16:
                if self._debug:
                    print(f"[CAN{self.bus_id}] Bus-off, frame skipped")
                return
            print(f"⚠️  CAN{self.bus_id} send failed:", e)
        except Exception as e:
            print(f"⚠️  CAN{self.bus_id} send failed:", e)

    async def send_async(self, data, can_id, timeout=0):
        self.send(data, can_id, timeout)
        await asyncio.sleep_ms(2)

    async def sdo_write_u8(self, node_id, index, subindex, value):
        data = bytearray([0x2F, index & 0xFF, (index >> 8) & 0xFF, subindex,
                          value & 0xFF, 0, 0, 0])
        self.send(data, 0x600 + int(node_id))
        await asyncio.sleep_ms(10)

    async def sdo_write_u16(self, node_id, index, subindex, value):
        data = bytearray([0x2B, index & 0xFF, (index >> 8) & 0xFF, subindex,
                          value & 0xFF, (value >> 8) & 0xFF, 0, 0])
        self.send(data, 0x600 + int(node_id))
        await asyncio.sleep_ms(10)

    async def sdo_write_u32(self, node_id, index, subindex, value):
        data = bytearray([0x23, index & 0xFF, (index >> 8) & 0xFF, subindex,
                          value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, (value >> 24) & 0xFF])
        self.send(data, 0x600 + int(node_id))
        await asyncio.sleep_ms(10)

    async def sdo_request(self, node_id, data):
        if isinstance(data, (list, tuple)):
            data = bytes(int(b) & 0xFF for b in data)
        elif isinstance(data, bytearray):
            data = bytes(data)
        if not isinstance(data, (bytes,)) or len(data) != 8:
            raise ValueError("SDO request must be exactly 8 bytes")
        self.send(data, 0x600 + int(node_id))
        await asyncio.sleep_ms(5)


# async def can_decode_task(can: AsyncCANPort, DATA):
#     """
#     Continuously decode key PDOs and update the shared DATA structure.
#     Needed for precharge and crank logic to see live inverter values.
#     """
#     print("Decoder started for CAN object id:", id(can._can))
# 
#     
#     while True:
#         msg = await can.recv()
#         cob_id = msg["id"]
#         data   = msg["data"]
# 
# #         if cob_id == 0x381:
# #             print("⚠ 0x381 frame received but len(data)=", len(data))
# 
#         # --- Sevcon Gen4 PDO 0x381: DC-link voltage, temps, torque, speed ---
#         if cob_id == 0x381 and len(data) >= 8:
# #            print("DBG CAN1 0x381:", data)
#             # 0–1: DC-link voltage (0.1 V / LSB)
#             # 0–1: DC-link voltage (0.1 V / LSB, unsigned)
#             DATA.dc_bus_v = int.from_bytes(data[0:2], "little", False) * GEN4_VBUS_SCALE
# 
#             # 2–3: temperatures (raw bytes)
#             DATA.inverter_temp = data[2]
#             DATA.motor_temp    = data[3]
#             # 4–5: actual torque (s16)
#             DATA.torque_actual = int.from_bytes(data[4:6], "little", True)
#             # 6–7: motor speed (s16)
#             DATA.speed_rpm     = int.from_bytes(data[6:8], "little", True)
#             # Optional cache for quick access
#             can.last_dc_link_v = DATA.dc_bus_v
# 
#         # --- (Optionally) PDO 0x481: other inverter values ---
#         elif cob_id == 0x481 and len(data) >= 2:
#             DATA.bus_current = int.from_bytes(data[0:2], "little", True) * 0.1
# 
#         # Add other devices’ COB-IDs here (BMS, PMU, etc.)
# 
#         await asyncio.sleep_ms(2)

async def can_decode_task(can: AsyncCANPort, DATA):
    print("Decoder started for CAN object id:", id(can._can))
    while True:
        msg = await can.recv()

        # Optionally track DC bus from 0x381 (keep only if needed)
        if msg["id"] == 0x381 and len(msg["data"]) >= 2:
            DATA.dc_bus_v = int.from_bytes(msg["data"][0:2], "little") * GEN4_VBUS_SCALE

        await asyncio.sleep_ms(2)


async def _await_sdo_response(can: AsyncCANPort, node_id: int, timeout_ms=200):
    cob_id_rsp = 0x580 + int(node_id)
    ticks = 0
    step = 5
    while ticks < timeout_ms:
        msg = await can.recv()
        if msg["id"] == cob_id_rsp:
            return msg["data"]
        await asyncio.sleep_ms(step)
        ticks += step
    return None

async def sdo_request_from(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    frame = bytearray([0x40, index & 0xFF, (index >> 8) & 0xFF, subindex, 0, 0, 0, 0])
    can.send(frame, 0x600 + int(node_id))
    await asyncio.sleep_ms(5)

async def sdo_read_u8(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    await sdo_request_from(can, node_id, index, subindex)
    data = await _await_sdo_response(can, node_id, timeout_ms=200)
    if data is None:
        print(f"⚠️  Timeout waiting for SDO 0x{index:04X}:{subindex}")
        return None
    if data[0] == 0x80:
        abort = data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24)
        print(f"⚠️  SDO abort 0x{abort:08X} at 0x{index:04X}:{subindex}")
        return None
    return data[4] & 0xFF

async def sdo_read_u16(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    await sdo_request_from(can, node_id, index, subindex)
    data = await _await_sdo_response(can, node_id, timeout_ms=200)
    if data is None:
        print(f"⚠️  Timeout waiting for SDO 0x{index:04X}:{subindex}")
        return None
    if data[0] == 0x80:
        abort = data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24)
        print(f"⚠️  SDO abort 0x{abort:08X} at 0x{index:04X}:{subindex}")
        return None
    return (data[4] | (data[5] << 8)) & 0xFFFF

async def sdo_read_s16(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    v = await sdo_read_u16(can, node_id, index, subindex)
    if v is None:
        return None
    return v - 0x10000 if (v & 0x8000) else v

async def sdo_read_u32(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    await sdo_request_from(can, node_id, index, subindex)
    data = await _await_sdo_response(can, node_id, timeout_ms=200)
    if data is None:
        print(f"⚠️  Timeout waiting for SDO 0x{index:04X}:{subindex}")
        return None
    if data[0] == 0x80:
        abort = data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24)
        print(f"⚠️  SDO abort 0x{abort:08X} at 0x{index:04X}:{subindex}")
        return None
    return ((data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24)) & 0xFFFFFFFF)

async def sdo_read_s32(can: AsyncCANPort, node_id: int, index: int, subindex: int):
    v = await sdo_read_u32(can, node_id, index, subindex)
    if v is None:
        return None
    return v - 0x100000000 if (v & 0x80000000) else v

async def send_nmt_start(can: AsyncCANPort, node_id=1):
    try:
        can.send(bytearray([0x01, int(node_id)]), 0x000)
        if getattr(can, "_debug", False):
            print(f"NMT: Start node {node_id}")
    except Exception as e:
        print("⚠️  NMT start failed:", e)
    await asyncio.sleep_ms(5)

# Existing global wrappers (kept)
async def sdo_write_u8(can, node_id, index, subindex, value):
    await can.sdo_write_u8(node_id, index, subindex, value)
async def sdo_write_u16(can, node_id, index, subindex, value):
    await can.sdo_write_u16(node_id, index, subindex, value)
async def sdo_write_i32(can, node_id, index, subindex, value):
    await can.sdo_write_u32(node_id, index, subindex, value)
# --- Add this near the other SDO helpers ---
async def sdo_write_u32(can, node_id, index, subindex, value):
    """Unsigned 32-bit expedited SDO write"""
    data = bytes([
        0x23,
        index & 0xFF, (index >> 8) & 0xFF,
        subindex,
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ])
    await can.tx(0x600 + node_id, data)
    await asyncio.sleep_ms(5)

# --- Signed 16-bit expedited SDO write ---
async def sdo_write_s16(can, node_id, index, subindex, value):
    """Signed 16-bit expedited SDO write (0x2B command specifier)."""
    if value < 0:
        value &= 0xFFFF  # two's complement
    data = bytes([
        0x2B,
        index & 0xFF, (index >> 8) & 0xFF,
        subindex,
        value & 0xFF,
        (value >> 8) & 0xFF,
        0x00, 0x00
    ])
    await can.tx(0x600 + node_id, data)
    await asyncio.sleep_ms(5)



# ─────────────────────────────────────────────────────────────
#  FIX: re-apply CAN1 filter after CAN2 init (Pyboard dual-CAN quirk)
# ─────────────────────────────────────────────────────────────

async def fix_dual_can_filters(can1, can2):
    """Re-apply CAN1 filters after CAN2 init — Pyboard dual-CAN workaround."""

    await asyncio.sleep_ms(100)
    try:
        can1._can.setfilter(0, CAN.MASK16, 0, (0, 0, 0, 0))
        if can1._debug:
            print("✅ CAN1 filters re-applied (accept all STD)")
    except Exception as e:
        print("⚠️ CAN1 re-filter failed:", e)
    await asyncio.sleep_ms(10)
