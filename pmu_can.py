# pmu_can.py — PMU CAN manager (corrected)
# -----------------------------------------

from async_can_dual import DualCAN
from pmu_can_filters import configure_can1_filters, configure_can2_filters
from pmu_config import CAN1_BAUD, CAN2_BAUD

dual = None
CAN1 = None
CAN2 = None

async def start_can():
    """
    Properly start both CAN buses using DualCAN, then apply filters in the
    correct order: CAN1 → CAN2 → CAN1.
    """
    global dual, CAN1, CAN2

    # 1. Create DualCAN (creates both AsyncCANPorts)
    dual = DualCAN(CAN1_BAUD, CAN2_BAUD)


    # 2. Start hardware CAN & IRQ decode tasks
    await dual.start()

    # 3. Expose raw pyb.CAN hardware objects
    CAN1 = dual.can1.hwcan
    CAN2 = dual.can2.hwcan

    print("pmu_can: CAN hardware initialised")

    # 4. Apply filters in the correct order
    configure_can1_filters(CAN1)
    configure_can2_filters(CAN2)
    configure_can1_filters(CAN1)

    print("pmu_can: CAN1 & CAN2 filters applied (1 → 2 → 1)")
    print("pmu_can: decode tasks running")

    # 5. Return the AsyncCANPort objects (not raw pyb.CAN)
    return dual.can1, dual.can2
