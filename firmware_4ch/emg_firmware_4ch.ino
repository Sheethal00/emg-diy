// DIY 4-channel sEMG streamer: ESP32 + 4x ADS1015 (one per channel, each AIN0-AIN1 differential vs VREF)
// Output: text lines "micros,ch1,ch2,ch3,ch4" at 1 kHz (counts, 1 mV/count). Lines starting with '#' are messages.
#include <Wire.h>

#define USE_BT 1   // 1 = Bluetooth (use for body recordings). 0 = USB serial (bench tests ONLY, no electrodes on you)

#if USE_BT
#include "BluetoothSerial.h"
BluetoothSerial bt;
#endif
Stream* out;

// ADS1015 ADDR pin wiring: GND=0x48, VDD=0x49, SDA=0x4A, SCL=0x4B
const uint8_t ADDR[4] = {0x48, 0x49, 0x4A, 0x4B};
const uint32_t PERIOD_US = 1000;   // 1 kHz per channel
const int BATCH = 10;              // lines per transmit (10 ms)
uint32_t nextT;
char buf[BATCH * 36];
int len = 0, nLines = 0;

bool adsConfig(uint8_t a) {
  // 0x04C3: continuous, AIN0-AIN1, +/-2.048 V, 3300 SPS, comparator off
  Wire.beginTransmission(a);
  Wire.write(0x01); Wire.write(0x04); Wire.write(0xC3);
  if (Wire.endTransmission() != 0) return false;
  Wire.beginTransmission(a);          // point at conversion register
  Wire.write(0x00);
  return Wire.endTransmission() == 0;
}

int16_t adsRead(uint8_t a) {
  if (Wire.requestFrom(a, (uint8_t)2) != 2) return 0;
  int16_t v = (Wire.read() << 8) | Wire.read();
  return v >> 4;  // 12-bit, 1 mV/count
}

void setup() {
#if USE_BT
  bt.begin("EMG-Logger");
  out = &bt;
#else
  Serial.begin(921600);
  out = &Serial;
#endif
  Wire.begin(21, 22);
  Wire.setClock(400000);
  for (int i = 0; i < 4; i++) {
    if (!adsConfig(ADDR[i])) {
      char m[32];
      int n = snprintf(m, sizeof(m), "# ADS fail ch%d\n", i + 1);
      out->write((const uint8_t*)m, n);
    }
  }
  nextT = micros() + PERIOD_US;
}

void loop() {
  uint32_t now = micros();
  if ((int32_t)(now - nextT) >= 0) {
    nextT += PERIOD_US;
    int16_t v[4];
    for (int i = 0; i < 4; i++) v[i] = adsRead(ADDR[i]);
    len += snprintf(buf + len, sizeof(buf) - len, "%lu,%d,%d,%d,%d\n",
                    (unsigned long)now, v[0], v[1], v[2], v[3]);
    if (++nLines >= BATCH) {
      out->write((const uint8_t*)buf, len);
      len = 0; nLines = 0;
    }
  }
}
