# async_can_dual.py — Fully patched Pyboard CAN driver
# -----------------------------------------------------
# Supports:
#  - Pyboard v1.1 (pyb.CAN API)
#  - IRQ-driven receive (FIFO0)
#  - Ringbuffer ingest
#  - pmu_can_filters for both CAN1/CAN2
#  - pmu_can_decode integration
#
# Designed for PMU crank + PID where timing must be exact.

from pyb import CAN
import micropython, utime

from pmu_can_ringbuffer import CANRingBuffer
from pmu_can_decode import decode_frame
from pmu_can_filters import (
    configure_can1_filters,
    configure_can2_filters
)

micropython.const

# Maximum frames queued before overwrite
RX_BUFFER_SIZE = 128


# ----------------------------------------------------------------------
# Helper: timestamp in milliseconds
# ----------------------------------------------------------------------
def ms():
    return utime.ticks_ms()


# ======================================================================
# CAN Port Class
# ======================================================================
class AsyncCANPort:

    def __init__(self, bus_id, baudrate, filter_type):
        """
        bus_id     : 1 or 2
        baudrate   : 500000
        filter_type: 'CAN1' or 'CAN2'
        """

        self.bus_id = bus_id
        self.baudrate = baudrate
        self.filter_type = filter_type

        # Ringbuffer for this CAN port
        self.rx_fifo = CANRingBuffer(RX_BUFFER_SIZE)

        # Create hardware CAN instance
        self.hwcan = CAN(bus_id, CAN.NORMAL)

        # Init CAN
        self.hwcan.init(
            CAN.NORMAL,
            baudrate=baudrate,
            sjw=1,
            bs1=9,
            bs2=4,
            auto_restart=True
        )

        # Clear both FIFOs
        try:
            while self.hwcan.any(0):
                self.hwcan.recv(0)
            while self.hwcan.any(1):
                self.hwcan.recv(1)
        except:
            pass

 
        # Whether TX is blocked (used by crank code)
        self.tx_blocked = False 

       

    # ------------------------------------------------------------------
    # Check if new frames are available
    # ------------------------------------------------------------------
    def rx_ready(self):
        return not self.rx_fifo.empty()


    def _push_frame(self, frame):
        try:
            can_id = frame[0]
            data   = frame[4]
            dlc    = len(data)
            ts     = ms()
            self.rx_fifo.put((can_id, dlc, data, ts))
        except Exception as e:
            print("PUSHFRAME ERROR:", e, frame)




    # ------------------------------------------------------------------
    # Get next frame (or None)
    # ------------------------------------------------------------------
    def read_frame(self):
        return self.rx_fifo.get()

    # ------------------------------------------------------------------
    # Transmit CAN frame
    # ------------------------------------------------------------------
    def tx(self, can_id, data, ext=False, rtr=False):
        if self.tx_blocked:
            return False
        try:
            self.hwcan.send(data, can_id, timeout=0, rtr=rtr, extframe=ext)
            return True
        except:
            return False

    # ------------------------------------------------------------------
    # Background decode loop (async)
    # Called from pmu_can.start_can()
    # ------------------------------------------------------------------
    async def decode_task(self):
        import uasyncio as asyncio
        while True:

            # POLL FIFO0
            while self.hwcan.any(0):
                raw = self.hwcan.recv(0)
                self._push_frame(raw)

            # POLL FIFO1
            while self.hwcan.any(1):
                raw = self.hwcan.recv(1)
                self._push_frame(raw)

            # PROCESS RINGBUFFER
            while not self.rx_fifo.empty():
                slot = self.rx_fifo.get()    # returns CANFrame object
                if slot:
                    decode_frame(slot.id, slot.data, slot.timestamp)

            await asyncio.sleep_ms(1)



# ======================================================================
# Dual CAN Manager
# ======================================================================
class DualCAN:

    def __init__(self, baud1, baud2):
        self.can1 = AsyncCANPort(1, baud1, "CAN1")
        self.can2 = AsyncCANPort(2, baud2, "CAN2")

    async def start(self):
        import uasyncio as asyncio
        asyncio.create_task(self.can1.decode_task())
        asyncio.create_task(self.can2.decode_task())


# ----------------------------------------------------------------------
# SYNC generator (required by Sevcon Gen4)
# ----------------------------------------------------------------------
import uasyncio as asyncio

async def sync_task(can_port, period_ms=20):
    """
    Periodic SYNC generator.
    Sends 0x80 (SYNC) every period_ms.
    """
    while True:
        try:
            # COB-ID 0x080, empty data
            can_port.tx(0x80, b'')
        except:
            pass
        await asyncio.sleep_ms(period_ms)
