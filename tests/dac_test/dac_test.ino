// EMG test rig: the normal 1 kHz sampler/sender from firmware/emg_firmware.ino, plus a test signal
// from the ESP32's own DAC, so the whole software chain can be tested with no phone and no extra parts.
//
// Wiring (USB unplugged while wiring):
//   GPIO25 (DAC1, labelled P25)  --- 1 kOhm ---  ADS1015 A0
//   ADS1015 A1 stays on the 1.65 V divider node.   Nothing else changes.
//
// Use: hold the BOOT button (GPIO0) = "muscle on" (100 Hz sine around mid-scale). Release = rest.
// Do NOT hold BOOT while resetting or plugging in USB (that enters the bootloader).
//
// Bench test only: no electrodes on your body. Output goes over USB serial (USE_BT 0).
#include <Wire.h>

#define USE_BT 0   // 0 = USB serial (this test). 1 = Bluetooth.
#define SIGNAL_NOISE 0   // 0 = 100 Hz sine (median frequency should read about 100 Hz). 1 = random noise (EMG-like).

#if USE_BT
#include "BluetoothSerial.h"
BluetoothSerial bt;
#endif
Stream* out;

const uint8_t ADS_ADDR = 0x48;
const uint32_t PERIOD_US = 1000;  // 1 kHz output
uint32_t nextT;

// ---- test signal ----
const int DAC_PIN = 25;           // DAC1
const int BTN_PIN = 0;            // BOOT button, reads LOW when pressed
const float SIG_HZ = 100.0f;
const float SIG_AMP = 30.0f;      // DAC steps (about 12.9 mV each): about +/-390 mV, i.e. about +/-390 counts
const int NOISE_AMP = 40;         // DAC steps, used when SIGNAL_NOISE is 1
const int DAC_MID = 128;          // about 1.65 V, the same level as the divider node
float phase = 0.0f;

void updateDac() {
  int v = DAC_MID;
  if (digitalRead(BTN_PIN) == LOW) {
#if SIGNAL_NOISE
    v = DAC_MID + (int)(esp_random() % (2 * NOISE_AMP + 1)) - NOISE_AMP;
#else
    v = DAC_MID + (int)lroundf(SIG_AMP * sinf(phase));
#endif
  }
  phase += 2.0f * PI * SIG_HZ / 1000.0f;   // advance one sample at 1 kHz
  if (phase > 2.0f * PI) phase -= 2.0f * PI;
  dacWrite(DAC_PIN, v);
}

// ---- ring buffer: loop() writes, sendTask() reads ----
const uint16_t QN = 2048;          // about 2 s of samples
struct Sample { uint32_t t; int16_t v; };
Sample q[QN];
volatile uint16_t qHead = 0;
volatile uint16_t qTail = 0;
volatile uint32_t dropped = 0;

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
    vTaskDelay(pdMS_TO_TICKS(10));   // send roughly every 10 ms
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
  pinMode(BTN_PIN, INPUT_PULLUP);
  dacWrite(DAC_PIN, DAC_MID);
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
      __sync_synchronize();
      qHead = nh;
    } else {
      dropped++;
    }
    updateDac();                     // set the test signal for the next sample
  }
}
