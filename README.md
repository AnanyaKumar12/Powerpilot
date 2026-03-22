# Smart Energy Monitor

Real-time electricity monitoring and fault detection using ESP32 + PZEM-004T + DS18B20.

---

## Project Structure

```
smart-energy-monitor/
├── firmware/
│   ├── main.ino
│   ├── pzem_reader.h
│   ├── pzem_reader.cpp
│   ├── temp_sensor.h
│   └── temp_sensor.cpp
│
├── backend/
│   ├── app.py
│   ├── mqtt_subscriber.py
│   ├── models/
│   │   ├── telemetry.py
│   │   └── alert.py
│   └── routes/
│       ├── telemetry.py
│       ├── alerts.py
│       └── devices.py
│
├── ai/
│   ├── anomaly.py
│   └── model.py
│
├── frontend/
│   ├── index.html
│   └── app.js
│
├── README.md
└── requirements.txt
```

---

## Hardware

| Component     | Role                              | Interface        |
|---------------|-----------------------------------|------------------|
| ESP32         | Microcontroller + WiFi            | —                |
| PZEM-004T v3  | Voltage / Current / Power / kWh   | UART2 GPIO 16/17 |
| DS18B20       | Temperature                       | OneWire GPIO 4   |
| Relay module  | Circuit breaker                   | GPIO 26          |

---

## Firmware Setup

1. Open the `firmware/` folder in Arduino IDE
2. Install libraries via Library Manager:
   - `PZEM004Tv30` by Jakub Mandula
   - `DallasTemperature` by Miles Burton
   - `OneWire` by Paul Stoffregen
   - `PubSubClient` by Nick O'Leary
   - `ArduinoJson` by Benoit Blanchon
3. Edit `main.ino` — set `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_TOKEN`
4. Select board: ESP32 Dev Module
5. Flash to ESP32

---

## Backend Setup

```bash
cd backend/
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r ../requirements.txt
```

Create a `.env` file inside `backend/`:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smart_monitor
MQTT_BROKER=demo.thingsboard.io
MQTT_PORT=1883
MQTT_USERNAME=YOUR_THINGSBOARD_TOKEN
MQTT_PASSWORD=
THRESH_V_MAX=250
THRESH_V_MIN=180
THRESH_I_MAX=15
THRESH_T_MAX=75
THRESH_PF_MIN=0.5
```

Run the server:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Swagger docs: `http://localhost:8000/docs`

---

## AI Analytics

```bash
cd ai/
python model.py --device ESP32_ENERGY_01 --hours 24
python model.py --hours 48 --output results.json
```

Minimum 50 telemetry records required for Isolation Forest.

---

## Frontend

Open `frontend/index.html` directly in a browser, or serve via nginx.

Update `API_BASE` in `frontend/app.js` to match your backend URL.

---

## API Endpoints

| Method | Endpoint                    | Description                    |
|--------|-----------------------------|--------------------------------|
| GET    | /api/realtime               | Latest sensor reading + faults |
| GET    | /api/history                | Time-series data (last N hours)|
| GET    | /api/history/summary        | Aggregated stats               |
| GET    | /api/alerts                 | Fault alert list               |
| POST   | /api/alerts/acknowledge     | Acknowledge alerts by ID       |
| GET    | /api/alerts/stats           | Alert counts by type           |
| GET    | /api/devices                | All registered devices         |
| GET    | /health                     | Service health check           |

---

## Fault Detection Thresholds

| Fault          | Condition         | Relay Trips |
|----------------|-------------------|-------------|
| Overvoltage    | > 250 V           | No          |
| Undervoltage   | < 180 V           | No          |
| Overcurrent    | > 15 A            | Yes         |
| Overheating    | > 75 °C           | Yes         |
| Low Power Factor | < 0.50          | No          |
| Current Spike  | > 5 A from MA     | No          |

---

## Fault Code Bitmask

| Bit | Fault           |
|-----|-----------------|
| 0   | Overvoltage     |
| 1   | Undervoltage    |
| 2   | Overcurrent     |
| 3   | Overheating     |
| 4   | Low Power Factor|
| 5   | Current Spike   |

---

## AI Anomaly Detection Methods

| Method           | File         | Detects                              |
|------------------|--------------|--------------------------------------|
| Isolation Forest | anomaly.py   | Multi-feature statistical outliers   |
| Z-Score          | anomaly.py   | Per-signal rolling deviation         |
| Moving Average   | anomaly.py   | Sudden power spikes                  |
| Domain Rules     | anomaly.py   | Standby loss, thermal trend, low PF  |
| Runner + CLI     | model.py     | Orchestrates all methods + DB write  |

---

## Database Tables

**telemetry** — every sensor reading from the ESP32
**alerts** — threshold breaches and AI anomalies

Both tables are auto-created on first backend startup.
