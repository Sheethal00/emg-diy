# Day 1 plan: ESP32 + ADS1015 + adapter boards (no amplifier yet)

Goal: prove the digital half of the system (ESP32, ADS1015, software, Bluetooth) before the INA333 and OPA2333 arrive.
**No electrodes on your body today.** Everything here is bench testing on USB power.

## Bring / have ready
Must have:
- ESP32 DevKit (classic WROOM, 38-pin), ADS1015 module, USB-C **data** cable
- SOP8/TSSOP8/MSOP8 to DIP8 adapter boards (for soldering practice only today)
- Breadboard, male-to-male jumper wires
- 2 x 10 kOhm resistors (reference divider), 1 x 10 kOhm potentiometer, 1 x 1 kOhm resistor
- Multimeter
- Soldering iron, solder, flux (to solder header pins on the ADS1015)
- Laptop with Arduino IDE and Python set up (done), phone with a tone-generator app
- A 3.5 mm audio cable or earphone cable you can cut, or a headphone-jack breakout

Nice to have: magnifier or phone camera (to read the chip marking), tweezers, desoldering wick.

Do first on Ubuntu: confirm `groups` lists `dialout` (log out and back in if not).

## Steps

### 1. Inspect and prepare (15 min)
1. Read the marking on the ADS1015 chip. It should be an ADS1015, not ADS1115. If it is an ADS1115, stop and tell me.
2. Solder the header pins onto the ADS1015 module. Check with continuity mode that neighboring pins are not shorted.
3. Check the ESP32 header pins are firmly soldered.

### 2. ESP32 alone (10 min)
1. Plug the ESP32 into USB. In Arduino IDE choose Tools > Board > ESP32 Dev Module and the right port.
2. Open `firmware_4ch/emg_firmware_4ch.ino`, set `#define USE_BT 0`, and upload.
3. Open Serial Monitor at **921600** baud.
Expected: lines starting with `# ADS fail`. This confirms the board, cable and upload all work.
If upload fails with "permission denied": the `dialout` group step is not active yet.

### 3. Wire the ADS1015 (15 min)
Power off while wiring.

| ADS1015 pin | Connect to |
|---|---|
| VDD | ESP32 3V3 |
| GND | ESP32 GND |
| SCL | GPIO22 |
| SDA | GPIO21 |
| ADDR | GND (address 0x48) |
| A0, A1 | see the next steps |
| ALRT | leave open |

### 4. I2C scan (5 min)
1. Upload `tests/i2c_scanner/i2c_scanner.ino`, Serial Monitor at **115200** baud.
Expected: `Found device at 0x48`.
2. If nothing is found: re-check SDA/SCL, VDD, GND, and the ADDR wire.

### 5. Zero test (5 min)
1. Re-upload the 4-channel firmware (USB mode). Tie A0 and A1 together and to GND.
2. Serial Monitor at 921600: lines look like `123456,x,0,0,0`.
Expected: channel 1 near 0 (within a few counts). Channels 2 to 4 show 0.

### 6. Reference and potentiometer test (15 min)
1. Build the 1.65 V reference: 10 kOhm from 3V3 to a node, 10 kOhm from that node to GND. Measure the node with the multimeter: about 1.65 V. Connect the node to **A1**.
2. Connect the potentiometer's outer pins to 3V3 and GND, and its middle pin to **A0**.
3. Turn the potentiometer slowly from end to end.
Expected: channel 1 counts swing from about -1650 to +1650 (1 count = 1 mV). A multimeter at A0 should agree (counts = (A0 voltage - 1.65 V) x 1000).

### 7. Sample rate check (5 min)
1. Close Serial Monitor and the dashboard.
2. Run `python tests/check_rate.py /dev/ttyUSB0`.
Expected: about 1000 Hz and few late samples. The three missing ADS1015 chips may slow the loop. If the rate is low, send me the output.

### 8. Full software chain with an audio tone (30 min)
This feeds a phone tone directly into the ADS1015 (the amplifier is not needed for a loud signal).
1. Unplug your phone's charger. Do not use a charging phone.
2. Wire the audio cable: **sleeve to A1** (still on the 1.65 V node), **tip through the 1 kOhm resistor to A0**. Remove the potentiometer from A0.
3. Start with the phone volume low (about 30%). Play a 100 Hz sine tone.
4. Run `python emg_server.py --port /dev/ttyUSB0` and open `http://localhost:8000`.
5. Calibrate rest (tone off, 5 s), then calibrate max (tone on, 5 s). Then switch the tone on and off.
Expected: channel 1 "% max" rises when the tone plays and falls when it stops. Rep counts go up. Record a short file and open the CSV.
If the trace is flat: check the tip and sleeve wires, that A1 is on the 1.65 V node, and the phone volume.

### 9. Bluetooth (20 min)
1. Set `USE_BT 1` in the firmware, upload, and leave USB connected for power only.
2. Pair "EMG-Logger" in Ubuntu Bluetooth settings. Find its address with `bluetoothctl devices`.
3. `sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF`
4. `python tests/check_rate.py /dev/rfcomm0`, then run the dashboard with `--port /dev/rfcomm0`.
Expected: the same behavior as USB.

### 10. Soldering practice (rest of the time)
Practice with the adapter boards and flux, and on any spare SMD part. Aim to get the pads wetted evenly with no bridges. The INA333 and OPA2333 come on the 7th.

## What to send me if something fails
- The exact text in Serial Monitor or the terminal
- A photo of the wiring
- The step number

## Checklist to tick off
- [ ] Chip marking is ADS1015
- [ ] ESP32 uploads over USB
- [ ] I2C scan finds 0x48
- [ ] Zero test near 0
- [ ] Potentiometer sweeps about +/-1650
- [ ] Sample rate near 1000 Hz
- [ ] Tone shows up on the dashboard
- [ ] Bluetooth data flows
