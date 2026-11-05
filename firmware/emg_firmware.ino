// DIY sEMG streamer: ESP32 + ADS1015 (differential AIN0-AIN1), 1 kHz, text lines "micros,counts"
//
// Sampling runs in loop() at exactly 1 kHz and puts samples in a ring buffer.
// A separate task sends the buffer out in small batches, so a slow or stalled
// Bluetooth link delays delivery but never stops the sampling.
#include <Wire.h>

#define USE_BT 1   // 1 = Bluetooth (use for body recordings). 0 = USB serial (bench tests ONLY, no electrodes on you)

#if USE_BT
#include "BluetoothSerial.h"
BluetoothSerial bt;
#endif
Stream* out;

const uint8_t ADS_ADDR = 0x48;
const uint32_t PERIOD_US = 1000;  // 1 kHz output
uint32_t nextT;

// ---- ring buffer: loop() writes, sendTask() reads ----
const uint16_t QN = 2048;          // about 2 s of samples
struct Sample { uint32_t t; int16_t v; };
Sample q[QN];
volatile uint16_t qHead = 0;       // next slot to write (sampler only)
volatile uint16_t qTail = 0;       // next slot to read (sender only)
volatile uint32_t dropped = 0;     // samples lost because the buffer was full

void adsConfig() {
  // 0x0483: continuous, AIN0-AIN1, +/-2.048 V, 1600 SPS, comparator off
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(0x01); Wire.write(0x04); Wire.write(0x83);
  Wire.endTransmission();
  Wire.beginTransmission(ADS_ADDR);   // point to conversion register
  Wire.write(0x00);
  Wire.endTransmission();
}

int16_t adsRead() {
  Wire.requestFrom(ADS_ADDR, (uint8_t)2);
  int16_t v = (Wire.read() << 8) | Wire.read();
  return v >> 4;  // 12-bit, 1 mV/count at +/-2.048 V
}

void sendTask(void*) {
  static char buf[1600];
  uint32_t lastDropped = 0;
  for (;;) {
#if USE_BT
    if (!bt.hasClient()) {           // nobody connected: throw away stale samples
      qTail = qHead;
      dropped = 0;
      lastDropped = 0;
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }
#endif
    int n = 0;
    uint16_t t = qTail;
    while (t != qHead && n < (int)sizeof(buf) - 40) {
      n += snprintf(buf + n, sizeof(buf) - n, "%lu,%d\n",
                    (unsigned long)q[t].t, (int)q[t].v);
      t = (t + 1) % QN;
    }
    uint32_t d = dropped;
    if (d != lastDropped && n < (int)sizeof(buf) - 40) {
      n += snprintf(buf + n, sizeof(buf) - n, "# dropped %lu\n", (unsigned long)d);
      lastDropped = d;
    }
    if (n > 0) {
      int off = 0;
      while (off < n) {
        size_t w = out->write((const uint8_t*)buf + off, n - off);
        if (w == 0) vTaskDelay(1);
        off += (int)w;
      }
      qTail = t;
    }
    vTaskDelay(pdMS_TO_TICKS(10));   // send roughly every 10 ms, about 10 samples per batch
  }
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
  adsConfig();
  xTaskCreatePinnedToCore(sendTask, "send", 4096, NULL, 1, NULL, 0);
  nextT = micros() + PERIOD_US;
}

void loop() {
  uint32_t now = micros();
  if ((int32_t)(now - nextT) >= 0) {
    nextT += PERIOD_US;
    int16_t v = adsRead();
    uint16_t h = qHead;
    uint16_t nh = (h + 1) % QN;
    if (nh != qTail) {
      q[h].t = now;
      q[h].v = v;
      __sync_synchronize();     // make sure the sample is stored before the sender can see it
      qHead = nh;
    } else {
      dropped++;
    }
  }
}
