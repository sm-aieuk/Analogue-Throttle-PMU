from pyb import Pin
import time

# Initialize pin Y2 (which maps to port C pin 7) as output
p = Pin('Y1', Pin.OUT_PP)

# Toggle the pin
p.high()   # Set pin high
#time.sleep(1)
#p.low()    # Set pin low