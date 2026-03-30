import asyncio
import json
import logging
import os
from datetime import datetime

import asyncpg
import paho.mqtt.client as mqtt

log = logging.getLogger("mqtt")

MQTT_BROKER   = os.getenv("MQTT_BROKER",   "demo.thingsboard.io")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "YOUR_THINGSBOARD_TOKEN")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC    = os.getenv("MQTT_TOPIC",    "v1/devices/me/telemetry")

THRESH_V_MAX  = float(os.getenv("THRESH_V_MAX",  "250"))
THRESH_V_MIN  = float(os.getenv("THRESH_V_MIN",  "180"))
THRESH_I_MAX  = float(os.getenv("THRESH_I_MAX",  "15"))
THRESH_T_MAX  = float(os.getenv("THRESH_T_MAX",  "75"))
THRESH_PF_MIN = float(os.getenv("THRESH_PF_MIN", "0.5"))

_pool:   asyncpg.Pool             = None
_loop:   asyncio.AbstractEventLoop = None
_client: mqtt.Client               = None


def set_pool(pool: asyncpg.Pool):
    global _pool
    _pool = pool


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info(f"[MQTT] Connected to {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        log.info(f"[MQTT] Subscribed to {MQTT_TOPIC}")
    else:
        log.error(f"[MQTT] Connect failed rc={rc}")


def _on_disconnect(client, userdata, rc):
    log.warning(f"[MQTT] Disconnected rc={rc} - auto-reconnect active")


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        asyncio.run_coroutine_threadsafe(_handle_message(payload), _loop)
    except Exception as e:
        log.error(f"[MQTT] Parse error: {e}")


async def _handle_message(data: dict):
    if _pool is None:
        return
    device_id = data.get("device_id", "unknown")
    try:
        await _store_telemetry(data, device_id)
        await _evaluate_alerts(data, device_id)
    except Exception as e:
        log.error(f"[MQTT] DB error: {e}")


async def _store_telemetry(data: dict, device_id: str):
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO telemetry
               (device_id, voltage, current, power, energy_kwh,
                frequency, power_factor, temperature,
                apparent_power, wifi_rssi, uptime_sec, raw)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            device_id,
            _f(data.get("voltage")),
            _f(data.get("current")),
            _f(data.get("power")),
            _f(data.get("energy_kwh")),
            _f(data.get("frequency")),
            _f(data.get("power_factor")),
            _f(data.get("temperature")),
            _f(data.get("apparent_power")),
            data.get("rssi"),
            data.get("uptime_sec"),
            json.dumps(data),
        )


async def _evaluate_alerts(data: dict, device_id: str):
    now    = datetime.utcnow()
    alerts = []

    def add(atype, severity, value, threshold, msg):
        alerts.append((now, device_id, atype, severity, value, threshold, msg))

    v  = data.get("voltage")
    i  = data.get("current")
    t  = data.get("temperature")
    pf = data.get("power_factor")

    if v is not None:
        if v > THRESH_V_MAX:
            add("OVERVOLTAGE",  "CRITICAL", v, THRESH_V_MAX,
                f"Voltage {v:.1f}V > max {THRESH_V_MAX}V")
        elif v < THRESH_V_MIN:
            add("UNDERVOLTAGE", "WARNING",  v, THRESH_V_MIN,
                f"Voltage {v:.1f}V < min {THRESH_V_MIN}V")

    if i and i > THRESH_I_MAX:
        add("OVERCURRENT", "CRITICAL", i, THRESH_I_MAX,
            f"Current {i:.2f}A > max {THRESH_I_MAX}A")

    if t and t > THRESH_T_MAX:
        add("OVERHEATING", "CRITICAL", t, THRESH_T_MAX,
            f"Temperature {t:.1f}C > max {THRESH_T_MAX}C")

    if pf and pf < THRESH_PF_MIN and (i or 0) > 0.5:
        add("LOW_POWER_FACTOR", "WARNING", pf, THRESH_PF_MIN,
            f"Power factor {pf:.3f} < {THRESH_PF_MIN}")

    if data.get("fault_spike"):
        add("CURRENT_SPIKE", "WARNING", i, None,
            f"Sudden current spike: {i:.3f}A")

    if alerts:
        async with _pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO alerts
                   (ts, device_id, alert_type, severity, value, threshold, message)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                alerts,
            )
        log.info(f"[ALERT] {len(alerts)} alert(s) stored for {device_id}")


def _f(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def start_mqtt_subscriber(loop: asyncio.AbstractEventLoop):
    global _loop, _client
    _loop = loop

    _client = mqtt.Client(client_id="backend_sub_01")
    _client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    _client.on_connect    = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.on_message    = _on_message
    _client.reconnect_delay_set(min_delay=2, max_delay=60)

    try:
        _client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        _client.loop_start()
        log.info("[MQTT] Subscriber thread started")
    except Exception as e:
        log.error(f"[MQTT] Could not connect: {e}")


def stop_mqtt_subscriber():
    if _client:
        _client.loop_stop()
        _client.disconnect()
        log.info("[MQTT] Subscriber stopped")
