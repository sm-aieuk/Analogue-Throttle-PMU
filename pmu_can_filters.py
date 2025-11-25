# pmu_can_filters.py
# -----------------------------------------------------------
# Hardware filter setup for CAN1 (Gen4/BMS/ECU) and CAN2 (customer)
# -----------------------------------------------------------

try:
    from pyb import CAN          # Pyboard / STM32 port
except ImportError:
    from machine import CAN      # Fallback for other ports

# GEN4 TPDOs + SDO + HB
GEN4_IDS = [
    0x181,  # TPDO1
    0x281,  # TPDO2
    0x381,  # TPDO3
    0x481,  # TPDO4
]
GEN4_SDO_REPLY = 0x581
GEN4_HEARTBEAT = 0x701
SYNC_ID = 0x80  # Optional RX

def configure_can1_filters(can1):
    print("DEBUG: Wide-open CAN1 filter")
    can1.setfilter(0, CAN.MASK16, 0, (0, 0, 0, 0))

def configure_can2_filters(can2, customer_ids=None):
    """
    Customer CAN2 filters.
    """
    if not customer_ids:
        customer_ids = []

    bank = 0
    for cid in customer_ids:
        can2.setfilter(bank, CAN.LIST16, 0, (cid, 0, 0, 0))
        bank += 1
