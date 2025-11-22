from pyb import CAN
import time

print("\n=== PYBOARD CAN1 SNIFFER ===")

# --- Init CAN1 @ 500 kbps, everything default ---
can = CAN(1, CAN.NORMAL)
can.init(
    CAN.NORMAL,
    prescaler=6,     # 500k for 168 MHz APB1
    bs1=11,
    bs2=2,
    sjw=1,
    auto_restart=True
)

# --- Accept ALL frames (STD and EXT) ---
can.setfilter(0, CAN.MASK16, 0, (0,0, 0, 0))   # FIFO0 catch-all
can.setfilter(1, CAN.MASK16, 1, (0,0, 0, 0))   # FIFO1 catch-all

print("CAN1 initialised. Listening...\n")

last_id = None

while True:
    if can.any(0):
        msg = can.recv(0)
    elif can.any(1):
        msg = can.recv(1)
    else:
        time.sleep_ms(1)
        continue

    can_id, is_ext, is_rtr, fmi, data = msg

    # Print frame nicely
    ds = ""
    if data:
        ds = " ".join("%02X" % b for b in data)
    else:
        ds = "(no data)"

    print("ID=%03X  EXT=%s  RTR=%s  DATA=%s" %
          (can_id, is_ext, is_rtr, ds))
