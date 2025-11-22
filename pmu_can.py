# pmu_can.py — PMU CAN manager (patched for async_can_dual)
# ----------------------------------------------------------

from async_can_dual import DualCAN
from pmu_config import CAN1_BAUD, CAN2_BAUD

# Public handles
can1 = None
can2 = None
dual = None


def init_can():
    """
    Initialise both CAN buses using the new DualCAN driver.
    Creates:
        pmu_can.can1
        pmu_can.can2
    """
    global can1, can2, dual

    # Create the dual CAN wrapper (this creates both AsyncCANPort instances)
    dual = DualCAN(CAN1_BAUD, CAN2_BAUD)

    # Expose can1/can2 as public module attributes
    can1 = dual.can1
    can2 = dual.can2

    return can1, can2


async def start_can():
    """
    Starts the async decode tasks for CAN1 and CAN2.
    Must be awaited once during system startup (in main.py).
    """
    global dual
    await dual.start()
