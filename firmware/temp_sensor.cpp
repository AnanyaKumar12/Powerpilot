#include "temp_sensor.h"
#include <OneWire.h>
#include <DallasTemperature.h>

#define DS18B20_PIN 4

static OneWire           oneWire(DS18B20_PIN);
static DallasTemperature sensors(&oneWire);
static int               _sensorCount = 0;

void tempSensorInit() {
  sensors.begin();
  _sensorCount = sensors.getDeviceCount();
  Serial.printf("[TEMP] Found %d DS18B20 sensor(s) on GPIO%d\n",
                _sensorCount, DS18B20_PIN);

  if (_sensorCount == 0)
    Serial.println(F("[TEMP] WARNING: No sensors found - check wiring and 4.7k pull-up"));

  sensors.setResolution(12);
  sensors.setWaitForConversion(true);
}

float tempRead() {
  if (_sensorCount == 0) return TEMP_ERROR_VALUE;

  sensors.requestTemperatures();
  float tempC = sensors.getTempCByIndex(0);

  if (tempC == DEVICE_DISCONNECTED_C) {
    Serial.println(F("[TEMP] ERROR: Sensor disconnected or read failed"));
    return TEMP_ERROR_VALUE;
  }

  Serial.printf("[TEMP] %.2f C\n", tempC);
  return tempC;
}

int tempSensorCount() {
  return _sensorCount;
}
