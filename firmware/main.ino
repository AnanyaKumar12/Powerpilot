#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include "pzem_reader.h"
#include "temp_sensor.h"

const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

const char* MQTT_SERVER  = "demo.thingsboard.io";
const int   MQTT_PORT    = 1883;
const char* MQTT_TOKEN   = "YOUR_THINGSBOARD_TOKEN";
const char* DEVICE_ID    = "ESP32_ENERGY_01";

const char* TOPIC_TELEMETRY  = "v1/devices/me/telemetry";
const char* TOPIC_ATTRIBUTES = "v1/devices/me/attributes";

#define PIN_RELAY  26
#define PIN_LED     2

#define INTERVAL_SAMPLE_MS     2000
#define INTERVAL_RECONNECT_MS  5000

const float THRESH_V_MAX   = 250.0f;
const float THRESH_V_MIN   = 180.0f;
const float THRESH_I_MAX   = 15.0f;
const float THRESH_T_MAX   = 75.0f;
const float THRESH_PF_MIN  = 0.50f;
const float THRESH_SPIKE_A = 5.0f;

#define MA_WINDOW 10

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

struct FaultStatus {
  bool    overvoltage;
  bool    undervoltage;
  bool    overcurrent;
  bool    overheating;
  bool    lowPowerFactor;
  bool    currentSpike;
  uint8_t code;
};

static float  _maBuf[MA_WINDOW] = {};
static int    _maIdx   = 0;
static float  _maSum   = 0.0f;
static bool   _maReady = false;

static unsigned long _uptimeSec    = 0;
static unsigned long _lastUptickMs = 0;
static unsigned long _lastSampleMs = 0;
static unsigned long _lastReconnMs = 0;

void        wifiConnect();
void        mqttConnect();
void        ensureConnections();
float       movingAverage(float val);
FaultStatus detectFaults(const PzemData& p, float tempC);
void        publishTelemetry(const PzemData& p, float tempC, const FaultStatus& f);
void        publishAttributes();
void        mqttCallback(char* topic, byte* payload, unsigned int len);
void        setRelay(bool trip);
void        blinkLED(int n, int ms);
String      buildJSON(const PzemData& p, float tempC, const FaultStatus& f);

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println(F("\n[BOOT] Smart Energy Monitor starting..."));

  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED,   OUTPUT);
  digitalWrite(PIN_RELAY, LOW);

  pzemInit();
  tempSensorInit();

  wifiConnect();
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(1024);
  mqttConnect();
  publishAttributes();

  blinkLED(3, 80);
  Serial.println(F("[BOOT] Ready.\n"));
}

void loop() {
  if (mqtt.connected()) mqtt.loop();

  if (millis() - _lastUptickMs >= 1000) {
    _uptimeSec++;
    _lastUptickMs = millis();
  }

  ensureConnections();

  if (millis() - _lastSampleMs >= INTERVAL_SAMPLE_MS) {
    _lastSampleMs = millis();

    PzemData pzem = pzemRead();
    float    temp = tempRead();

    if (!pzem.valid) {
      Serial.println(F("[WARN] PZEM read failed - skipping cycle"));
      return;
    }

    FaultStatus faults = detectFaults(pzem, temp);

    if (faults.overcurrent || faults.overheating) {
      setRelay(true);
      Serial.println(F("[RELAY] TRIPPED - overcurrent or overheat"));
    }

    publishTelemetry(pzem, temp, faults);
  }
}

void wifiConnect() {
  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print('.');
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED)
    Serial.printf("\n[WiFi] Connected - IP %s  RSSI %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  else
    Serial.println(F("\n[WiFi] Failed - will retry in loop"));
}

void mqttConnect() {
  if (mqtt.connected()) return;
  Serial.print(F("[MQTT] Connecting..."));
  if (mqtt.connect(DEVICE_ID, MQTT_TOKEN, ""))
    Serial.println(F(" OK"));
  else
    Serial.printf(" FAILED rc=%d\n", mqtt.state());
}

void ensureConnections() {
  if (millis() - _lastReconnMs < INTERVAL_RECONNECT_MS) return;
  _lastReconnMs = millis();
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); return; }
  if (!mqtt.connected()) mqttConnect();
}

void mqttCallback(char* topic, byte* payload, unsigned int len) {
  String msg;
  for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
  Serial.printf("[MQTT] Rx %s : %s\n", topic, msg.c_str());

  StaticJsonDocument<128> doc;
  if (!deserializeJson(doc, msg) && doc.containsKey("relay"))
    setRelay(doc["relay"].as<bool>());
}

float movingAverage(float val) {
  _maSum -= _maBuf[_maIdx];
  _maBuf[_maIdx] = val;
  _maSum += val;
  _maIdx = (_maIdx + 1) % MA_WINDOW;
  if (_maIdx == 0) _maReady = true;
  int count = _maReady ? MA_WINDOW : _maIdx;
  return _maSum / count;
}

FaultStatus detectFaults(const PzemData& p, float tempC) {
  FaultStatus f = {};

  f.overvoltage    = (p.voltage     > THRESH_V_MAX);
  f.undervoltage   = (p.voltage     < THRESH_V_MIN && p.voltage > 10.0f);
  f.overcurrent    = (p.current     > THRESH_I_MAX);
  f.overheating    = (tempC         > THRESH_T_MAX);
  f.lowPowerFactor = (p.powerFactor < THRESH_PF_MIN && p.current > 0.5f);

  float ma       = movingAverage(p.current);
  f.currentSpike = (_maReady && fabsf(p.current - ma) > THRESH_SPIKE_A);

  f.code  = (f.overvoltage    ? 0x01 : 0);
  f.code |= (f.undervoltage   ? 0x02 : 0);
  f.code |= (f.overcurrent    ? 0x04 : 0);
  f.code |= (f.overheating    ? 0x08 : 0);
  f.code |= (f.lowPowerFactor ? 0x10 : 0);
  f.code |= (f.currentSpike   ? 0x20 : 0);

  return f;
}

String buildJSON(const PzemData& p, float tempC, const FaultStatus& f) {
  StaticJsonDocument<512> doc;

  doc["voltage"]        = serialized(String(p.voltage,     2));
  doc["current"]        = serialized(String(p.current,     3));
  doc["power"]          = serialized(String(p.power,       2));
  doc["energy_kwh"]     = serialized(String(p.energy,      4));
  doc["frequency"]      = serialized(String(p.frequency,   1));
  doc["power_factor"]   = serialized(String(p.powerFactor, 3));
  doc["temperature"]    = serialized(String(tempC,         1));
  doc["apparent_power"] = serialized(String(
      (p.powerFactor > 0.01f) ? p.power / p.powerFactor : 0.0f, 2));

  doc["fault_overvoltage"]  = f.overvoltage;
  doc["fault_undervoltage"] = f.undervoltage;
  doc["fault_overcurrent"]  = f.overcurrent;
  doc["fault_overheating"]  = f.overheating;
  doc["fault_low_pf"]       = f.lowPowerFactor;
  doc["fault_spike"]        = f.currentSpike;
  doc["fault_code"]         = f.code;
  doc["any_fault"]          = (f.code != 0);

  doc["device_id"]  = DEVICE_ID;
  doc["uptime_sec"] = _uptimeSec;
  doc["rssi"]       = WiFi.RSSI();

  String out;
  serializeJson(doc, out);
  return out;
}

void publishTelemetry(const PzemData& p, float tempC, const FaultStatus& f) {
  if (!mqtt.connected()) { Serial.println(F("[MQTT] Not connected")); return; }

  String payload = buildJSON(p, tempC, f);
  bool   ok      = mqtt.publish(TOPIC_TELEMETRY, payload.c_str());

  Serial.printf("[MQTT] %s  %d bytes  faultCode=0x%02X\n",
                ok ? "OK" : "FAIL", payload.length(), f.code);

  if (ok) blinkLED(1, 50);
}

void publishAttributes() {
  if (!mqtt.connected()) return;
  StaticJsonDocument<256> doc;
  doc["firmware"]  = "1.0.0";
  doc["device_id"] = DEVICE_ID;
  doc["v_max"]     = THRESH_V_MAX;
  doc["i_max"]     = THRESH_I_MAX;
  doc["t_max"]     = THRESH_T_MAX;
  doc["pf_min"]    = THRESH_PF_MIN;
  String out;
  serializeJson(doc, out);
  mqtt.publish(TOPIC_ATTRIBUTES, out.c_str());
}

void setRelay(bool trip) {
  digitalWrite(PIN_RELAY, trip ? HIGH : LOW);
}

void blinkLED(int n, int ms) {
  for (int i = 0; i < n; i++) {
    digitalWrite(PIN_LED, HIGH); delay(ms);
    digitalWrite(PIN_LED, LOW);  delay(ms);
  }
}
