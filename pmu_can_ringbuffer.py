# pmu_can_ringbuffer.py
# -----------------------------------------------------------
# Lightweight ring buffer for CAN frames
# Designed for ISR safety and zero allocation
# -----------------------------------------------------------

import micropython

class CANFrame:
    __slots__ = ("id", "dlc", "data", "timestamp")
    def __init__(self):
        self.id = 0
        self.dlc = 0
        self.data = b""
        self.timestamp = 0


class CANRingBuffer:
    def __init__(self, size=128):
        self.size = size
        self.buf = [CANFrame() for _ in range(size)]
        self.head = 0
        self.tail = 0
        self.count = 0

    @micropython.native
    def put(self, frame):
        if self.count >= self.size:
            # DROP frame if full (overflow counter added later in supervisor)
            return False
        slot = self.buf[self.head]
        slot.id = frame[0]
        slot.dlc = frame[1]
        slot.data = frame[2]
        slot.timestamp = frame[3]
        self.head = (self.head + 1) % self.size
        self.count += 1
        return True

    @micropython.native
    def get(self):
        if self.count == 0:
            return None
        slot = self.buf[self.tail]
        self.tail = (self.tail + 1) % self.size
        self.count -= 1
        return slot

    @micropython.native
    def empty(self):
        return self.count == 0

    @micropython.native
    def __len__(self):
        return self.count
