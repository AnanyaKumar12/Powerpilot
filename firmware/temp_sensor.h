#pragma once
#include <Arduino.h>

#define TEMP_ERROR_VALUE -127.0f

void  tempSensorInit();
float tempRead();
int   tempSensorCount();
