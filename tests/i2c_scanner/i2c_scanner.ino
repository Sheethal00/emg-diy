// I2C scanner for ESP32 (SDA = GPIO21, SCL = GPIO22).
// Upload, then open Serial Monitor at 115200 baud (not 921600).
// With the ADS1015 ADDR pin on GND, expect: "Found device at 0x48".
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(500);
  Wire.begin(21, 22);
  Serial.println("I2C scan (SDA=21, SCL=22)");
}

void loop() {
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print("Found device at 0x");
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) Serial.println("No devices found. Check power, SDA, SCL and ground wiring.");
  Serial.println("---");
  delay(2000);
}
