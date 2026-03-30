import asyncio
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.telemetry import router as telemetry_router
from routes.alerts    import router as alerts_router
from routes.devices   import router as devices_router
from mqtt_subscriber  import start_mqtt_subscriber, stop_mqtt_subscriber, set_pool

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("app")

DB_DSN = os.getenv("DATABASE_URL",
                   "postgresql://postgres:postgres@localhost:5432/smart_monitor")

db_pool: asyncpg.Pool = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    id             BIGSERIAL    PRIMARY KEY,
    ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    device_id      TEXT         NOT NULL,
    voltage        NUMERIC(7,2),
    current        NUMERIC(7,3),
    power          NUMERIC(10,2),
    energy_kwh     NUMERIC(12,4),
    frequency      NUMERIC(5,1),
    power_factor   NUMERIC(5,3),
    temperature    NUMERIC(5,1),
    apparent_power NUMERIC(10,2),
    wifi_rssi      INTEGER,
    uptime_sec     BIGINT,
    raw            JSONB
);

CREATE TABLE IF NOT EXISTS alerts (
    id           BIGSERIAL    PRIMARY KEY,
    ts           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    device_id    TEXT         NOT NULL,
    alert_type   TEXT         NOT NULL,
    severity     TEXT         NOT NULL,
    value        NUMERIC,
    threshold    NUMERIC,
    message      TEXT,
    acknowledged BOOLEAN      DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_telemetry_ts        ON telemetry(ts DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts ON telemetry(device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ts           ON alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ack          ON alerts(acknowledged);
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool

    db_pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    log.info("[DB] Connected and schema ready")

    set_pool(db_pool)
    start_mqtt_subscriber(asyncio.get_event_loop())

    yield

    stop_mqtt_subscriber()
    await db_pool.close()
    log.info("[SHUTDOWN] Clean shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Energy Monitor API",
        version="1.0.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(telemetry_router, prefix="/api", tags=["Telemetry"])
    app.include_router(alerts_router,    prefix="/api", tags=["Alerts"])
    app.include_router(devices_router,   prefix="/api", tags=["Devices"])

    @app.get("/", tags=["Health"])
    async def root():
        return {"status": "ok", "service": "Smart Energy Monitor", "version": "1.0.0"}

    @app.get("/health", tags=["Health"])
    async def health():
        try:
            async with db_pool.acquire() as c:
                await c.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"db": "ok" if db_ok else "error"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
