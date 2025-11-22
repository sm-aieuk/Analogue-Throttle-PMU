# pmu_throttle.py — Pyboard PWM/I2C throttle helper

import uasyncio as asyncio
from pyb import Pin, Timer

# CONFIG
USE_PWM_THROTTLE = True
USE_I2C_THROTTLE = False

PWM_PIN = 'Y7'
PWM_FREQ = 1000

# Voltage limits
V_MIN_HW = 0.5
V_NEUTRAL_HW = 4.0
V_MAX_HW = 7.5

DUTY_MIN = 5
DUTY_MAX = 95

# RUN/FS1 pins
FWD_PIN = Pin('Y2', Pin.OUT_PP)
FS1_PIN = Pin('Y3', Pin.OUT_PP)

# Calculate duty cycle from voltage
def volts_to_duty(v):
    v = max(V_MIN_HW, min(V_MAX_HW, v))
    span = V_MAX_HW - V_MIN_HW
    pct = (v - V_MIN_HW) / span
    return int(DUTY_MIN + pct * (DUTY_MAX - DUTY_MIN))

def calibrate_voltage(v):
    return v

class Throttle:
    def __init__(self):
        self._init_pwm()

    def _init_pwm(self):
        # Y7 / PB14 uses Timer 12, Channel 1 for PWM
        self.tim = Timer(12, freq=PWM_FREQ)
        self.ch  = self.tim.channel(1, Timer.PWM, pin=Pin(PWM_PIN))

    async def _set_pwm_output(self, duty):
        # Pyboard PWM: duty percentage
        self.ch.pulse_width_percent(100 - duty)  # inverted
        await asyncio.sleep_ms(1)

    async def neutral(self):
        v = V_NEUTRAL_HW
        await self._apply_voltage(v)

    async def forward_nm(self, nm):
        span = V_MAX_HW - V_NEUTRAL_HW
        v = V_NEUTRAL_HW + (nm / 50.0) * span
        await self._apply_voltage(v)

    async def regen_nm(self, nm):
        span = V_NEUTRAL_HW - V_MIN_HW
        v = V_NEUTRAL_HW - (nm / 50.0) * span
        await self._apply_voltage(v)

    async def _apply_voltage(self, volts):
        v = calibrate_voltage(volts)
        duty = volts_to_duty(v)
        await self._set_pwm_output(duty)
        await asyncio.sleep_ms(1)

# Global instance
_throttle = Throttle()

async def set_throttle_voltage(volts):
    v = calibrate_voltage(volts)
    duty = volts_to_duty(v)
    await _throttle._set_pwm_output(duty)
    await asyncio.sleep_ms(2)
