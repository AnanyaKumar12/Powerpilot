#include "pzem_reader.h"
#include <PZEM004Tv30.h>

#define PZEM_RX_PIN    16
#define PZEM_TX_PIN    17
#define READ_RETRIES    3
#define RETRY_DELAY_MS 50

static HardwareSerial pzemSerial(2);
static PZEM004Tv30    pzem(&pzemSerial, PZEM_RX_PIN, PZEM_TX_PIN);

void pzemInit() {
  delay(300);
  Serial.println(F("[PZEM] Initialised on UART2 (GPIO16/17)"));
}

PzemData pzemRead() {
  PzemData data = {};

  for (int attempt = 0; attempt < READ_RETRIES; attempt++) {
    float v  = pzem.voltage();
    float i  = pzem.current();
    float p  = pzem.power();
    float e  = pzem.energy();
    float f  = pzem.frequency();
    float pf = pzem.pf();

    if (isnan(v) || isnan(i) || isnan(p)) {
      Serial.printf("[PZEM] Read attempt %d failed (NaN)\n", attempt + 1);
      delay(RETRY_DELAY_MS);
      continue;
    }

    data.voltage     = v;
    data.current     = i;
    data.power       = p;
    data.energy      = isnan(e)  ? 0.0f  : e;
    data.frequency   = isnan(f)  ? 50.0f : f;
    data.powerFactor = isnan(pf) ? 1.0f  : pf;
    data.valid       = true;

    Serial.printf("[PZEM] V=%.2fV  I=%.3fA  P=%.2fW  E=%.4fkWh  F=%.1fHz  PF=%.3f\n",
                  data.voltage, data.current, data.power,
                  data.energy, data.frequency, data.powerFactor);
    return data;
  }

  Serial.println(F("[PZEM] ERROR: all retries failed - check wiring"));
  return data;
}

void pzemResetEnergy() {
  pzem.resetEnergy();
  Serial.println(F("[PZEM] Energy counter reset to 0.0000 kWh"));
}
