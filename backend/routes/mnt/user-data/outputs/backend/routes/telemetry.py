import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from models.telemetry import RealTimeData, SummaryStats

router = APIRouter()


def _get_pool():
    from app import db_pool
    return db_pool


def _f(val):
    return round(float(val), 4) if val is not None else None


@router.get("/realtime", response_model=RealTimeData)
async def get_realtime(device_id: str = Query(default="ESP32_ENERGY_01")):
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM telemetry WHERE device_id=$1 ORDER BY ts DESC LIMIT 1",
            device_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="No data found for device")

    raw    = json.loads(row["raw"]) if row["raw"] else {}
    faults = []
    if raw.get("fault_overvoltage"):  faults.append("OVERVOLTAGE")
    if raw.get("fault_undervoltage"): faults.append("UNDERVOLTAGE")
    if raw.get("fault_overcurrent"):  faults.append("OVERCURRENT")
    if raw.get("fault_overheating"):  faults.append("OVERHEATING")
    if raw.get("fault_low_pf"):       faults.append("LOW_POWER_FACTOR")
    if raw.get("fault_spike"):        faults.append("CURRENT_SPIKE")

    return RealTimeData(
        device_id      = row["device_id"],
        ts             = row["ts"],
        voltage        = _f(row["voltage"]),
        current        = _f(row["current"]),
        power          = _f(row["power"]),
        energy_kwh     = _f(row["energy_kwh"]),
        frequency      = _f(row["frequency"]),
        power_factor   = _f(row["power_factor"]),
        temperature    = _f(row["temperature"]),
        apparent_power = _f(row["apparent_power"]),
        status         = "FAULT" if faults else "NORMAL",
        active_faults  = faults,
    )


@router.get("/history")
async def get_history(
    device_id: str = Query(default="ESP32_ENERGY_01"),
    hours:     int = Query(default=24, ge=1, le=720),
    limit:     int = Query(default=1000, ge=1, le=5000),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    pool  = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ts, device_id, voltage, current, power, energy_kwh,
                      frequency, power_factor, temperature, apparent_power
               FROM telemetry
               WHERE device_id=$1 AND ts >= $2
               ORDER BY ts ASC LIMIT $3""",
            device_id, since, limit,
        )
    return {
        "device_id": device_id,
        "from":      since.isoformat(),
        "count":     len(rows),
        "data": [
            {
                "ts":             r["ts"].isoformat(),
                "voltage":        _f(r["voltage"]),
                "current":        _f(r["current"]),
                "power":          _f(r["power"]),
                "energy_kwh":     _f(r["energy_kwh"]),
                "frequency":      _f(r["frequency"]),
                "power_factor":   _f(r["power_factor"]),
                "temperature":    _f(r["temperature"]),
                "apparent_power": _f(r["apparent_power"]),
            }
            for r in rows
        ],
    }


@router.get("/history/summary", response_model=SummaryStats)
async def get_summary(
    device_id: str = Query(default="ESP32_ENERGY_01"),
    hours:     int = Query(default=24, ge=1, le=720),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    pool  = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                 AVG(voltage)                          AS avg_v,
                 AVG(current)                          AS avg_i,
                 AVG(power)                            AS avg_p,
                 MAX(power)                            AS max_p,
                 MAX(energy_kwh) - MIN(energy_kwh)     AS total_e,
                 AVG(power_factor)                     AS avg_pf,
                 COUNT(*)                              AS recs
               FROM telemetry
               WHERE device_id=$1 AND ts >= $2""",
            device_id, since,
        )
        fault_count = await conn.fetchval(
            "SELECT COUNT(*) FROM alerts WHERE device_id=$1 AND ts >= $2",
            device_id, since,
        )

    return SummaryStats(
        device_id    = device_id,
        from_ts      = since,
        to_ts        = datetime.utcnow(),
        avg_voltage  = _f(row["avg_v"]),
        avg_current  = _f(row["avg_i"]),
        avg_power    = _f(row["avg_p"]),
        max_power    = _f(row["max_p"]),
        total_energy = _f(row["total_e"]),
        avg_pf       = _f(row["avg_pf"]),
        fault_count  = fault_count or 0,
        records      = row["recs"] or 0,
    )
