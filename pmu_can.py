# ─────────────────────────────────────────────────────────────
# pmu_can.py — Unified CAN setup for PMU
# ─────────────────────────────────────────────────────────────
from pyb import CAN
from async_can_dual import AsyncCANPort

# ─────────────────────────────────────────────────────────────
# Create and initialize hardware CAN peripherals
# ─────────────────────────────────────────────────────────────

# CAN1
_hwcan1 = CAN(1, CAN.NORMAL)
_hwcan1.init(
    CAN.NORMAL,
    prescaler=6,
    bs1=11,
    bs2=2,
    sjw=1,
    auto_restart=True
)

# Accept all standard/extended frames into FIFO0 and FIFO1
_hwcan1.setfilter(0, CAN.MASK32, 0, (0, 0))
_hwcan1.setfilter(1, CAN.MASK32, 1, (0, 0))

# CAN2
_hwcan2 = CAN(2, CAN.NORMAL)
_hwcan2.init(
    CAN.NORMAL,
    prescaler=6,
    bs1=11,
    bs2=2,
    sjw=1,
    auto_restart=True
)

# Accept all standard/extended frames into FIFO0 and FIFO1
_hwcan2.setfilter(0, CAN.MASK32, 0, (0, 0))
_hwcan2.setfilter(1, CAN.MASK32, 1, (0, 0))

# ─────────────────────────────────────────────────────────────
# Wrap both hardware CANs with AsyncCANPort (shared handles)
# ─────────────────────────────────────────────────────────────
can1 = AsyncCANPort(1, debug=False, hwcan=_hwcan1)
can2 = AsyncCANPort(2, debug=False, hwcan=_hwcan2)

print("pmu_can.py loaded successfully — CAN1 and CAN2 initialized.")
print("CAN1 object id:", id(_hwcan1))
print("CAN2 object id:", id(_hwcan2))
