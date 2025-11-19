import uasyncio as asyncio
import time
from machine import I2C


class NHD_0420D3Z_I2C:
    """Asynchronous-safe driver for Newhaven NHD-0420D3Z LCD."""
    DEFAULT_ADDRESS = 0x28
    CMD_PREFIX = 0xFE
    ROW_START = [0x00, 0x40, 0x14, 0x54]

    def __init__(self, i2c=None, addr=DEFAULT_ADDRESS, lock=None):
        # Re-use shared bus if given
        self.i2c = i2c or I2C(1, freq=50000)
        self.address = addr
        self.lock = lock or asyncio.Lock()
        time.sleep_us(120000)  # power-up delay per datasheet

    # ───────────────────────────────────────────────
    async def _send(self, buf):
        async with self.lock:
            self.i2c.writeto(self.address, buf)

    async def _cmd(self, cmd, param=None):
        buf = bytearray([self.CMD_PREFIX, cmd]) if param is None \
              else bytearray([self.CMD_PREFIX, cmd, param])
        await self._send(buf)
        await asyncio.sleep_ms(2)

    # ───────────────────────────────────────────────
    async def clear_screen(self):
        await self._cmd(0x51)
        await asyncio.sleep_ms(2)

    async def set_cursor(self, row, col):
        row = min(row, 3)
        col = min(col, 19)
        pos = self.ROW_START[row] + col
        await self._cmd(0x45, pos)
        await asyncio.sleep_ms(1)


    async def write_string(self, text):
        if not text:
            return
        data = text.encode('ascii', 'replace')
        block = 8
        for i in range(0, len(data), block):
            chunk = data[i:i + block]
            async with self.lock:
                self.i2c.writeto(self.address, chunk)
            await asyncio.sleep_ms(1)


    async def set_backlight_brightness(self, level):
        if 1 <= level <= 8:
            await self._cmd(0x53, level)
