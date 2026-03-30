import argparse
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List

import asyncpg
from dotenv import load_dotenv

from anomaly import AnomalyAlert, Severity, run_all

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("model")

DB_DSN = os.getenv("DATABASE_URL",
                   "postgresql://postgres:postgres@localhost:5432/smart_monitor")


def compute_summary(alerts: List[AnomalyAlert]) -> Dict:
    return {
        "total":    len(alerts),
        "critical": sum(1 for a in alerts if a.severity == Severity.CRITICAL),
        "warning":  sum(1 for a in alerts if a.severity == Severity.WARNING),
        "info":     sum(1 for a in alerts if a.severity == Severity.INFO),
        "by_type":  {
            t: sum(1 for a in alerts if a.anomaly_type.value == t)
            for t in set(a.anomaly_type.value for a in alerts)
        },
    }


async def persist_alerts(pool: asyncpg.Pool, alerts: List[AnomalyAlert]):
    if not alerts:
        return
    records = [
        (a.ts, a.device_id,
         f"AI_{a.anomaly_type.value}",
         a.severity.value,
         a.value, a.baseline, a.message)
        for a in alerts
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO alerts
               (ts, device_id, alert_type, severity, value, threshold, message)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            records,
        )
    log.info(f"[model] Persisted {len(records)} AI alert(s)")


async def analyse(pool: asyncpg.Pool, device_id: str,
                  hours: int = 24, persist: bool = True) -> Dict:
    log.info(f"[model] Analysing {device_id} ({hours}h)...")
    alerts = await run_all(pool, device_id, hours)

    if persist and alerts:
        await persist_alerts(pool, alerts)

    return {
        "device_id":   device_id,
        "analysed_at": datetime.utcnow().isoformat(),
        "hours":       hours,
        "summary":     compute_summary(alerts),
        "alerts":      [a.to_dict() for a in alerts],
    }


async def _cli_main():
    parser = argparse.ArgumentParser(description="Smart Energy Monitor - AI analysis")
    parser.add_argument("--device",     default="ESP32_ENERGY_01")
    parser.add_argument("--hours",      type=int, default=24)
    parser.add_argument("--db",         default=DB_DSN)
    parser.add_argument("--output",     default=None)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(args.db, min_size=1, max_size=3)
    try:
        result = await analyse(pool, args.device, args.hours,
                               persist=not args.no_persist)
        s = result["summary"]
        print(f"\n{'='*55}")
        print(f"  Analysis: {args.device}  |  last {args.hours}h")
        print(f"{'='*55}")
        print(f"  Total     : {s['total']}")
        print(f"  CRITICAL  : {s['critical']}")
        print(f"  WARNING   : {s['warning']}")
        if s["by_type"]:
            print(f"  By type:")
            for t, n in s["by_type"].items():
                print(f"    {t:<30} {n}")
        print(f"{'='*55}")

        if result["alerts"]:
            print("\nTop alerts:")
            for a in result["alerts"][:10]:
                print(f"  [{a['severity']:8s}] {a['anomaly_type']:30s} | "
                      f"{a['message'][:70]}")

        if args.output:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\nSaved to {args.output}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_cli_main())
