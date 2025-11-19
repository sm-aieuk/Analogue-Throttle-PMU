import asyncio
from gen4_helpers_async import sdo_write_u16, sdo_read_u16

# Developer passwords for Gen4 Size 6
PASSWORD_STAGE_A = 0xEBC8   # Write to 0x2F00:02
PASSWORD_STAGE_B = 0x4BDF   # Write to 0x2F00:03

async def sevcon_login(can, node_id=1, silent=False):
    """
    Perform Sevcon Gen4 developer login (Level 2 / Level 4 compatible).
    This matches the sequence performed by DVT.

    Returns True if login succeeded, False otherwise.
    """

    try:
        if not silent:
            print("SEVCON: login stage A (0x%04X)..." % PASSWORD_STAGE_A)

        ok1 = await sdo_write_u16(can, node_id, 0x2F00, 2, PASSWORD_STAGE_A)
        if not ok1:
            print("SEVCON: stage A write failed")
            return False

        await asyncio.sleep_ms(20)

        if not silent:
            print("SEVCON: login stage B (0x%04X)..." % PASSWORD_STAGE_B)

        ok2 = await sdo_write_u16(can, node_id, 0x2F00, 3, PASSWORD_STAGE_B)
        if not ok2:
            print("SEVCON: stage B write failed")
            return False

        await asyncio.sleep_ms(20)

        # Optional: read back access level from 0x2F00:01
        try:
            ok3, acc, abort = await sdo_read_u16(can, node_id, 0x2F00, 1)
            if ok3:
                print("SEVCON: access level now:", acc)
            else:
                print("SEVCON: unable to read access level (abort %s)" % abort)
        except:
            pass

        if not silent:
            print("SEVCON: developer login OK")

        return True

    except Exception as e:
        print("SEVCON: login exception:", e)
        return False
