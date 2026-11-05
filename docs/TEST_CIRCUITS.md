# Day 1 test circuits: how to build each one and what you should see

All of these are bench tests on USB power. **No electrodes on your body.** Power the ADS1015 from 3V3 only, never 5V/VIN.

Parts used: ESP32 DevKit (38-pin), ADS1015 module, breadboard, jumper wires, 2 x 10 kOhm resistors, 10 kOhm trimpot, multimeter, USB-C data cable.

## Multimeter settings (DT830D)
- Red probe in VOhm-mA, black probe in COM. Order does not matter for resistance or continuity.
- Continuity: diode/buzzer position. A beep means connected.
- Resistance: 20k range for the 10 kOhm resistors.
- Voltage: DCV 20 (not ACV).
- Probe tips are too thick for breadboard holes. Push a spare jumper lead into the hole and touch the probe to the lead's metal end.

---

## Circuit 1: Power rails
**Build**
1. ESP32 3V3 pin -> breadboard + rail (the row beside the red line).
2. ESP32 GND pin -> breadboard - rail (the row beside the blue line).
3. Remember the rails may be split in the middle (near column 30). Do not put parts at the break.

**Check (USB connected)**
- Red probe on a lead in the + rail, black on a lead in the - rail: **about 3.3 V**.
- Empty holes read nothing: only holes with a lead or part in them are reachable with a thick probe.

**If you read 0.08 V**: the 3V3 or GND wire to the rails is missing.

## Circuit 2: 1.65 V reference divider
**Build** (in a free row, for example row 20, away from the rail break)
1. R1 = 10 kOhm from the + rail to a free row.
2. R2 = 10 kOhm from the same free row to the - rail.
3. The shared row is the reference node (call it VREF).

**Check**
- Unplug the ESP32 power wires first, then measure each resistor in the 20k range: **about 9.7 to 10 kOhm** each. (With the ESP32 connected you read about 5.5 kOhm because of a parallel path.)
- Reconnect power. Voltage from VREF to the - rail: **about 1.64 V**.

## Circuit 3: ADS1015 and the I2C scan
**Build**
| ADS1015 pin | Connect to |
|---|---|
| VDD | ESP32 3V3 (rail) |
| GND | ESP32 GND (rail) |
| SCL | GPIO22 |
| SDA | GPIO21 |
| ADDR | GND (address 0x48) |
| ALRT | leave open |

**Test**: upload `tests/i2c_scanner/i2c_scanner.ino`, Serial Monitor at 115200 baud.

**Expected**: `Found device at 0x48`.

**If "No devices found"**: re-check VDD and GND reach the rails (the 3V3 and GND wires from the ESP32), then SDA/SCL, then ADDR.

## Circuit 4: Reference and trimpot (reads real voltages)
**Build**
1. A1 -> VREF (the 1.65 V node).
2. Trimpot outer pins -> 3V3 rail and GND rail. Trimpot middle pin (wiper) -> A0.

**Test**: upload `firmware/emg_firmware.ino` with `#define USE_BT 0`, Serial Monitor at 921600 baud. Output lines are `microseconds,counts`.

**Expected**
- Turn the trimpot slowly end to end: counts swing from about **-1644 to +1643**.
- Counts = (voltage at A0 - 1.65 V) x 1000. A multimeter at A0 should agree.
- Wiper in the middle: counts near 0.

**If the Serial Monitor shows garbage**: the sketch is in Bluetooth mode. Set `USE_BT 0` and re-upload.
**If every reading is -1**: the ADS1015 is not answering. Return to Circuit 3.

## Circuit 5: Sample rate check (USB)
**Test**: close the Serial Monitor and dashboard, then run `python tests/check_rate.py /dev/ttyUSB0`.

**Expected**: **1000.0 Hz**, no gaps over about 2 ms, verdict good.

## Circuit 6: Bluetooth and the dashboard
**Build**: no new wiring. Set `USE_BT 1`, upload. USB stays connected for power only.

**Steps**
1. Pair "EMG-Logger" in Ubuntu Bluetooth settings.
2. `sudo rfcomm bind 0 20:50:0D:4E:0A:3E`
3. `python tests/check_rate.py /dev/rfcomm0`

**Expected**: **1000.0 Hz**, largest gap about 1003 microseconds, no `# dropped` lines.

4. Run the dashboard: `python emg_server.py --port /dev/rfcomm0 --gain 1` and open `http://localhost:8000`. (`--gain 1` because there is no amplifier yet.)

**Expected**: a live trace that follows the trimpot. Calibrate rest and max, press Record, and you get `session_*_raw.csv` and `session_*_reps.csv`.

## Circuit 7: DAC test signal (written, not yet run)
**Build**
1. Remove the trimpot from A0.
2. ESP32 GPIO25 -> 1 kOhm resistor -> A0. A1 stays on VREF.

**Test**: upload `tests/dac_test/dac_test.ino`, then run the dashboard with `--gain 1`.

**Expected**
- A 100 Hz sine of about +/-375 mV peak, about **279 counts RMS**.
- Calibrate rest (press nothing), then max (signal on): % max rises with the signal.
- Press the BOOT button (GPIO0) to toggle the signal on and off. Reps count up and are written to `reps.csv`.

**Safety**: this test is bench-only, with no electrodes on your body. Never hold BOOT during reset or power-up.

## Lessons from Day 1
- Check each wire with continuity before moving on.
- Disconnect the ESP32 power wires before measuring resistors.
- Do not put parts across the rail break near column 30.
- ADS1015 reads 12 bits at 1 mV per count at +/-2.048 V. With the future amplifier (gain about 448), 1 count is about 2 microvolts at the skin.
