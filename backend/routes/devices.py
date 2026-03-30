from fastapi import APIRouter

router = APIRouter()


def _get_pool():
    from app import db_pool
    return db_pool


@router.get("/devices")
async def list_devices():
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT device_id, MAX(ts) AS last_seen, COUNT(*) AS records
               FROM telemetry
               GROUP BY device_id
               ORDER BY last_seen DESC"""
        )
    return {
        "count": len(rows),
        "devices": [
            {
                "device_id":     r["device_id"],
                "last_seen":     r["last_seen"].isoformat(),
                "total_records": r["records"],
            }
            for r in rows
        ],
    }
