# adc_manager.py — continuous ADC sampling and scaling for PMU
import uasyncio as asyncio
from machine import I2C
from ads1x15 import ADS1115


class ADCManager:
    """
    Reads both ADS1115s and updates shared DATA fields.
    0x49: battery voltage (AIN2-3 diff) + spare current (AIN0)
    0x48: load current (AIN0), inverter→battery current (AIN2)
    """

    def __init__(self, DATA, i2c=None, lock=None):
        self.DATA = DATA
        self.i2c = i2c or I2C(1, freq=400000)
        self.lock = lock or asyncio.Lock()

        # Gain=1 → ±4.096 V FS → 0.000125 V/bit
        self.adc_bus  = ADS1115(self.i2c, address=0x49, gain=1)
        self.adc_curr = ADS1115(self.i2c, address=0x48, gain=1)

        # ── Scaling constants ─────────────────────────────────────────
        # Adjust this if your meter vs ADC differs (~53.5 gives ~62.7 V true
        # for ~1.17 V ADC reading)
        self.VDIV_BATT = 53.5

        # LEM LF 205-S/SP3 + 16 Ω burden + AMC1311 (~1 V/V)
        # IS = 0.0005 A/A → 8 mV/A at ADC input.
        # ⇒ A_per_V = 1 / 0.008 = 125 A per V
        self.A_PER_V_LOAD   = 125.0
        self.A_PER_V_CHARGE = 125.0
        self.A_PER_V_SPARE  = 125.0

        self._print_debug = False

    async def _read_diff_v(self, adc, chp, chm):
        raw = adc.read(channel1=chp, channel2=chm)
        return adc.raw_to_v(raw), raw

    async def _read_single_v(self, adc, ch):
        raw = adc.read(channel1=ch)
        return adc.raw_to_v(raw), raw

    def read_all_once(self):
        """Synchronous one-shot for startup."""
        try:
            v_batt_adc = self.adc_bus.raw_to_v(self.adc_bus.read(2, 3))
            v_load_adc = self.adc_curr.raw_to_v(self.adc_curr.read(0))
            v_chg_adc  = self.adc_curr.raw_to_v(self.adc_curr.read(2))
            v_spare_adc= self.adc_bus.raw_to_v(self.adc_bus.read(0))

            D = self.DATA
            D.battery_v = v_batt_adc * self.VDIV_BATT
            D.load_i    = v_load_adc * self.A_PER_V_LOAD
            D.charge_i  = v_chg_adc  * self.A_PER_V_CHARGE
            D.spare_i   = v_spare_adc* self.A_PER_V_SPARE
        except Exception as e:
            print("ADC read_once error:", e)

    async def task(self, period_ms=50):
        """Async sampler (~20 Hz)."""
        D = self.DATA
        while True:
            try:
                async with self.lock:
                    v_batt_adc, raw_batt = await self._read_diff_v(self.adc_bus, 2, 3)
                    v_load_adc, raw_load   = await self._read_single_v(self.adc_curr, 0)
                    v_chg_adc,  raw_charge = await self._read_single_v(self.adc_curr, 2)
                    v_spare_adc, raw_spare = await self._read_single_v(self.adc_bus, 0)

                D.battery_v = v_batt_adc * self.VDIV_BATT
                D.load_i    = v_load_adc * self.A_PER_V_LOAD
                D.charge_i  = v_chg_adc  * self.A_PER_V_CHARGE
                D.spare_i   = v_spare_adc* self.A_PER_V_SPARE

                if self._print_debug:
                    print(f"ADC batt raw={raw_batt} → {v_batt_adc:.4f} V "
                          f"→ {D.battery_v:.1f} V | "
                          f"load={D.load_i:.1f} A chg={D.charge_i:.1f} A")

            except Exception as e:
                D.last_emcy_code = 999
                print("ADC task error:", e)

            await asyncio.sleep_ms(period_ms)
