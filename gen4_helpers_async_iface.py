
# gen4_helpers_async_iface.py — thin async interface wrapper around your existing helpers
# This avoids importing details here. It expects gen4_helpers_async.py to exist.
import uasyncio as asyncio
from pmu_config import DATA

try:
    import gen4_helpers_async as g4
except ImportError:
    g4 = None

class SevconInterface:
    """Async facade the crank routine can call. Uses your existing helper module."""
    def __init__(self, can):
        self.can = can

    async def enable_drive(self):
        if g4 and hasattr(g4, "enable_drive"):
            return await g4.enable_drive(self.can)
        return False

    async def set_torque_nm(self, value):
        if g4 and hasattr(g4, "set_torque_nm"):
            return await g4.set_torque_nm(self.can, value)
        return False

    async def read_rpm(self):
        if g4 and hasattr(g4, "read_rpm"):
            rpm = await g4.read_rpm(self.can)
            return rpm
        return 0
