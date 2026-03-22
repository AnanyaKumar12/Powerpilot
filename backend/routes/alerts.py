from fastapi import APIRouter, Query
from models.alert import AlertAcknowledge

router = APIRouter()


def _get_pool():
    from app import db_pool
    return db_pool


def _f(val):
    return round(float(val), 4) if val is not None else None


@router.get("/alerts")
async def get_alerts(
    device_id:    str  = Query(default="ESP32_ENERGY_01"),
    limit:        int  = Query(default=100, ge=1, le=1000),
    unacked_only: bool = Query(default=False),
):
    pool   = _get_pool()
    query  = "SELECT * FROM alerts WHERE device_id=$1"
    params = [device_id]

    if unacked_only:
        query += " AND acknowledged=FALSE"

    query += " ORDER BY ts DESC LIMIT $2"
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return {
        "device_id": device_id,
        "count": len(rows),
        "alerts": [
            {
                "id":           r["id"],
                "ts":           r["ts"].isoformat(),
                "alert_type":   r["alert_type"],
                "severity":     r["severity"],
                "value":        _f(r["value"]),
                "threshold":    _f(r["threshold"]),
                "message":      r["message"],
                "acknowledged": r["acknowledged"],
            }
            for r in rows
        ],
    }


@router.post("/alerts/acknowledge")
async def acknowledge_alerts(body: AlertAcknowledge):
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE alerts SET acknowledged=TRUE WHERE id=ANY($1::bigint[])",
            body.alert_ids,
        )
    updated = int(result.split()[-1])
    return {"acknowledged": updated, "ids": body.alert_ids}


@router.get("/alerts/stats")
async def get_alert_stats(device_id: str = Query(default="ESP32_ENERGY_01")):
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT alert_type, severity, COUNT(*) AS cnt
               FROM alerts
               WHERE device_id=$1
               GROUP BY alert_type, severity
               ORDER BY cnt DESC""",
            device_id,
        )
    return {
        "device_id": device_id,
        "stats": [
            {"type": r["alert_type"], "severity": r["severity"], "count": r["cnt"]}
            for r in rows
        ],
    }
