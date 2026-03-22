#pragma once
#include <Arduino.h>

struct PzemData {
  float voltage;
  float current;
  float power;
  float energy;
  float frequency;
  float powerFactor;
  bool  valid;
};

void     pzemInit();
PzemData pzemRead();
void     pzemResetEnergy();
