import uasyncio as asyncio
import time
from machine import I2C

class NHD_0420D3Z_I2C:
    """Robust, async-safe Newhaven NHD-0420D3Z LCD driver with retry & lock."""

    DEFAULT_ADDRESS = 0x28
    CMD_PREFIX = 0xFE
    ROW_START = [0x00, 0x40, 0x14, 0x54]

    def __init__(self, i2c=None, addr=DEFAULT_ADDRESS, lock=None):
        self.i2c = i2c or I2C(1, freq=50000)
        self.address = addr
        self.lock = lock or asyncio.Lock()

        # Datasheet: min 100ms startup. We give 150ms.
        time.sleep_ms(150)

        # Extra async-ready pause (I2C bus stabilisation)
        self._ready = False
        # Mark ready after short async delay
        asyncio.create_task(self._mark_ready())

    async def _mark_ready(self):
        await asyncio.sleep_ms(150)
        self._ready = True

    # --------------------------------------------------------------
    async def _send(self, buf):
        """Safe I2C send with retry and async lock."""
        # Wait for LCD to be marked ready
        while not self._ready:
            await asyncio.sleep_ms(5)

        async with self.lock:
            for attempt in range(3):
                try:
                    self.i2c.writeto(self.address, buf)
                    return True
                except OSError:
                    await asyncio.sleep_ms(3)
            # If all attempts fail → give up silently (UI will continue)
            return False

    async def _cmd(self, cmd, param=None):
        if param is None:
            buf = bytearray([self.CMD_PREFIX, cmd])
        else:
            buf = bytearray([self.CMD_PREFIX, cmd, param])
        await self._send(buf)
        await asyncio.sleep_ms(2)

    # --------------------------------------------------------------
    async def clear_screen(self):
        await self._cmd(0x51)
        await asyncio.sleep_ms(2)

    async def set_cursor(self, row, col):
        row = min(max(row, 0), 3)
        col = min(max(col, 0), 19)
        pos = self.ROW_START[row] + col
        await self._cmd(0x45, pos)
        await asyncio.sleep_ms(1)

    async def write_string(self, text):
        if not text:
            return

        data = text.encode('ascii', 'replace')
        block = 8

        for i in range(0, len(data), block):
            chunk = data[i:i+block]
            ok = await self._send(chunk)
            # If I2C is still reinitialising, don't crash UI
            if not ok:
                return
            await asyncio.sleep_ms(1)

    async def set_backlight_brightness(self, level):
        if 1 <= level <= 8:
            await self._cmd(0x53, level)
