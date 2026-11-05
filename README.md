# DIY sEMG Recorder (from scratch)

**Live animation:** https://sheethal00.github.io/emg-diy/ (end-to-end walkthrough from muscle to dashboard; source in `docs/index.html`).

**Start here:** `docs/BUILD_GUIDE.md` (step-by-step assembly and testing) and `docs/schematic.svg` (circuit diagram).

Single-supply (3.3 V), battery-powered surface EMG front end + ESP32 + Python logger.

## SAFETY (read first)
- Run from a **battery only** while electrodes are on your body.
- Never use USB-to-computer or any mains-connected equipment while wearing electrodes. Use the Bluetooth firmware mode (`USE_BT 1`) for body recordings. USB mode is for bench testing with no electrodes on you.
- Hobby/fitness tool only. Not a medical device. Do not use on broken skin or with implanted devices.

## Block diagram
```
Electrode+ --1k--+                                         
                 +--> INA333 (G=10) --> C1 1uF --> U2B (G~51, LPF 470 Hz) --1k--> ADS1015 AIN0
Electrode- --1k--+        REF=Vref        |  HPF 19 Hz                                  |
                                          R 8.2k to Vref                       AIN1 = Vref
Reference electrode --10k-- Vref (U2A buffer, 1.65 V)                                  |
                                                                      I2C (SDA21/SCL22) --> ESP32 --> Bluetooth --> Python
```
Total gain = 10.09 x 50.9 = ~513. ADS1015 differential (AIN0 - AIN1), +/-2.048 V range, 1 mV/count.
Full scale at the electrode = +/-4 mV. If strong contractions clip, change Rf (R7) to 24.9k (total gain ~261, +/-7.8 mV) and run the logger with `--gain 261`.

## Parts list
| Ref | Part | Value / note |
|-----|------|--------------|
| U1 | INA333 (MSOP-8 on breakout, or INA128/AD620 with adjusted supply) | Instrumentation amp |
| U2 | OPA2333 (dual, rail-to-rail, low-noise, 3.3 V) | A = Vref buffer, B = gain stage |
| U3 | ADS1015 breakout (Adafruit/generic) | ADDR to GND = 0x48 |
| U4 | AP2112K-3.3 (600 mA LDO) | MCP1700 is NOT enough: ESP32 Bluetooth peaks above 250 mA |
| MCU | ESP32 DevKit (classic ESP32, not S2/S3/C3: needs Bluetooth Classic) | Powered at its 3V3 pin from U4 |
| BAT | 1S LiPo 500+ mAh with protection circuit | Plus slide switch and 1 A fuse/PTC |
| Rg1 | 11 kOhm 0.1% | INA333 gain = 1 + 100k/Rg1 = 10.09 |
| R1, R2 | 10 kOhm 1% | Vref divider |
| R3, R4 | 1 kOhm | Input series (RFI) |
| R5, R6 | 10 MOhm (optional) | Input bias return to Vref (stops rail drift if an electrode lifts) |
| R7 | 49.9 kOhm 1% | Gain stage feedback |
| R8 | 1 kOhm 1% | Gain stage to Vref |
| R9 | 8.2 kOhm | HPF resistor to Vref |
| R10 | 1 kOhm | ADC input series |
| R11 | 10 kOhm | Reference electrode series (current limit) |
| C1 | 1 uF film (or C0G/X7R) | HPF, fc = 19.4 Hz |
| C2 | 6.8 nF C0G | Across R7, LPF fc = 469 Hz |
| C3, C4 | 1 nF C0G | Input to Vref (common mode RFI) |
| C5 | 10 nF C0G | Across inputs (differential RFI) |
| C6 | 1 uF | Vref node |
| C7-C10 | 0.1 uF | Decoupling at each IC supply pin |
| C11 | 10 uF | Analog supply bulk |
| FB1 | Ferrite bead + C11 | Separates analog 3.3 V from ESP32 3.3 V |
| - | Ag/AgCl snap electrodes (3), snap leads, shielded cable | Keep leads short |

## Connections (netlist)
| Net | Connections |
|-----|-------------|
| 3V3 | U4 out -> ESP32 3V3, FB1 -> **3V3A** |
| 3V3A | U1 V+, U2 V+, U3 VDD, R1 top, C7-C11 |
| GND | U4 GND, ESP32 GND, U1 V-, U2 V-, U3 GND, ADDR, R2 bottom |
| VREF | R1/R2 midpoint -> C6 -> U2A (+). U2A out tied to U2A (-) (follower) = **VREF** |
| VREF users | U1 REF, R5, R6 (other ends), C3, C4, R8 (bottom), R9 (bottom), R11 (to reference electrode), U3 AIN1 |
| IN+ | Electrode+ -> R3 -> U1 IN+ ; C3 from IN+ to VREF ; C5 across IN+/IN- |
| IN- | Electrode- -> R4 -> U1 IN- ; C4 from IN- to VREF |
| Rg | Rg1 between U1 RG pins (1 and 8) |
| U1 OUT | -> C1 -> node X |
| Node X | R9 to VREF ; U2B (+) |
| U2B | (-) to R8 (to VREF) and R7 || C2 to U2B out |
| U2B out | -> R10 -> U3 AIN0 |
| I2C | U3 SDA -> ESP32 GPIO21, SCL -> GPIO22 (ESP32 or breakout pull-ups to 3V3) |

Layout: keep the INA333 inputs short and away from the ESP32 and antenna, ground pour under analog section, one star point joining analog and digital grounds.

## Electrode placement
Sensor pair over the muscle belly, 15-20 mm apart, parallel to the fibers. Reference on a bony site (elbow, wrist, clavicle). Shave, abrade lightly, clean with alcohol.

## Build and test order
1. Build and check the Vref (should read 1.65 V) with no signal chain connected.
2. Add U1 and U2. Short IN+ and IN- to VREF: output should sit at 1.65 V.
3. Inject a 100 Hz, ~2 mV p-p sine (via a 1000:1 divider from a signal generator or phone/sound card) and confirm about 1 V p-p output, then sweep 5 Hz (attenuated), 20 Hz (-3 dB), 100 Hz (flat), 470 Hz (-3 dB).
4. Add the ADS1015 and flash `firmware/emg_firmware.ino` with `USE_BT 0` for bench tests (no electrodes on you).
5. Switch to `USE_BT 1`, pair the ESP32 ("EMG-Logger") with your computer, find the COM port / `/dev/rfcomm0`, then run the logger on battery power with electrodes on.

## Run the logger
```
pip install pyserial numpy scipy matplotlib
python emg_logger.py COM5 --out biceps_session1        # Windows
python emg_logger.py /dev/rfcomm0 --out biceps_session1 # Linux
```
It asks for 5 s relaxed, then 5 s maximum contraction, then goes live with rep detection. Outputs `<out>_raw.csv` and `<out>_reps.csv` (duration, peak and mean %MVC, median frequency per rep: a falling median frequency across a set indicates fatigue).

---

# Version 2: 4 channels, comparison metrics, browser dashboard, simulator

## Files
- `firmware_4ch/emg_firmware_4ch.ino`: streams 4 channels at 1 kHz (`micros,ch1,ch2,ch3,ch4`)
- `emg_server.py`: processing (20-450 Hz band-pass, 100 ms RMS), calibration, rep detection, comparison metrics, CSV recording, web server
- `dashboard.html`: the browser UI (served by the server)

## Hardware for 4 channels
Build the analog front end (INA333 + OPA2333 + filters) **four times**, one per muscle, all sharing the same 3.3 V rails and one VREF buffer (or a separate buffer per channel if you prefer isolation between channels). Use **one ADS1015 per channel**, each reading AIN0 (signal) minus AIN1 (VREF). A single ADS1015 cannot give four 1 kHz channels, because its input multiplexer would have to switch for every sample.

| Channel | ADS1015 ADDR pin to | I2C address |
|---------|--------------------|-------------|
| 1 | GND | 0x48 |
| 2 | VDD | 0x49 |
| 3 | SDA | 0x4A |
| 4 | SCL | 0x4B |

All four share SDA (GPIO21) and SCL (GPIO22). Tie unused inputs (AIN2/AIN3) to VREF.

## Run (no hardware needed to try it)
```
pip install numpy scipy pyserial
python emg_server.py --sim                        # then open http://localhost:8000
python emg_server.py --port COM5                  # real hardware over Bluetooth
python emg_server.py --port COM5 --host 0.0.0.0   # also view on a phone/tablet on the same Wi-Fi (no password: trusted network only)
```
Simulated mode generates four channels with different activation levels, delays, and co-contraction, and responds to the calibration buttons, so you can try the whole workflow first.

## Using the dashboard
1. **Calibrate rest** (5 s fully relaxed), then **Calibrate max** (5 s hardest contraction). Everything is shown as % of your own maximum.
2. Rename channels by clicking the name. Names are remembered in the browser.
3. Pick a muscle pair under *Muscle comparison*:
   - **Balance:** (A - B) / (A + B) in % over active time. +30 means A works harder.
   - **Co-activation:** overlap of the two envelopes, 2 x sum(min(A,B)) / sum(A+B). High means both muscles are on together.
   - **Onset lag:** which muscle starts first, in ms.
4. **Record** saves `sessions/<name>_<timestamp>_raw.csv` (raw and envelope in uV) and `_reps.csv` (duration, peak %, mean %, median frequency for each rep).
5. The median-frequency change since the first rep is shown per channel; a falling trend over a set suggests fatigue.

## Notes and limits
- Rep detection uses a threshold of max(rest + 5 SD, 10% of max) with hysteresis. Tune it in `rebuild()` and `RepDetector` if needed.
- Median frequency is only meaningful for contractions of at least about 0.5 s.
- Simulated data has a constant spectrum, so the fatigue readout will not trend in simulation.
- The USB baud rate is now 921600 (the earlier 115200 setting could not carry 1 kHz data).
- Same safety rules apply: battery power and Bluetooth only while electrodes are on you.
