# Build Guide: DIY sEMG Recorder (1 channel, then expand to 4)

See `schematic.svg` for the circuit. Take it slowly and test after every stage. If a stage fails its check, **stop and fix it before adding the next one.**

## 0. Before you start

**Tools:** multimeter (with AC volts), soldering iron + fine solder + flux, tweezers, side cutters, phone or laptop for tone generation, 3.5 mm audio cable you can cut.
**Skills:** the INA333 and OPA2333 come in tiny SMD packages. Solder them onto adapter boards first (Section 1).

### Safety rules (non-negotiable)
1. Electrodes on your body only when the circuit runs from **battery** and talks over **Bluetooth**. No USB cable, no mains-powered equipment connected.
2. Never connect the audio test signal (Section 5) while electrodes are on you.
3. Do not use on broken skin, near the chest/heart, or with implanted devices. This is a hobby tool, not a medical device.

### Two power modes (use a jumper called J1)
| Mode | How | Use for |
|------|-----|---------|
| **Bench** | USB powers the ESP32. J1 *open* (regulator/battery disconnected). Wire the ESP32 3V3 pin to the 3V3 rail. | All testing, **no electrodes on you** |
| **Wearable** | Battery -> switch -> 1 A fuse/PTC -> 3.3 V regulator -> J1 *closed* -> 3V3 rail. USB unplugged. | Real recordings |

Never have USB and the battery regulator both feeding the 3V3 rail at the same time. **Flash the firmware first** (Section 6) before wiring the rest.

> Battery note: a plain LDO such as the AP2112K stays in regulation only while the LiPo is above about 3.6 V. Below that the 3.3 V rail sags slowly. It still works for a first build; a 3.3 V buck-boost module is the better long-term choice.

## 1. Prepare the SMD parts
1. Solder the INA333 (MSOP-8) and OPA2333 (SOIC/MSOP-8) onto adapter boards. Match **pin 1 (dot)** to the adapter's pin 1.
2. Method: flux on the pads, tack one corner pin, check alignment, solder the opposite corner, then drag-solder the rest. Remove bridges with flux and solder wick.
3. Check with the multimeter (continuity): no short between adjacent pins, and V+ is not shorted to V-.

## 2. Stage A: power and VREF
Build on perfboard or a breadboard. Use the rails: **3V3A** (analog supply), **GND**, **VREF**.

1. Bench power: ESP32 3V3 pin -> ferrite bead -> 3V3A. Put 10 uF and 0.1 uF from 3V3A to GND.
2. Divider: R1 (10k) from 3V3A to a node, R2 (10k) from that node to GND, C6 (1 uF) from the node to GND.
3. Do not add the op-amp yet. Power on and measure the node: expect **1.65 V +/- 0.05 V**.
4. Add U2A as a follower (see pin table below): node -> pin 3, pin 1 tied to pin 2. Measure pin 1: still **1.65 V**.

### U2 OPA2333 pin table
| Pin | Name | Connect to |
|-----|------|------------|
| 1 | OUT A | pin 2 (follower) and the **VREF** rail |
| 2 | -IN A | pin 1 |
| 3 | +IN A | R1/R2/C6 midpoint |
| 4 | V- | GND |
| 5 | +IN B | node X (C1 and R9 meet here) |
| 6 | -IN B | R8 (1k) to VREF, and R7 (49.9k) in parallel with C2 (6.8 nF) to pin 7 |
| 7 | OUT B | R7 || C2 (to pin 6) and R10 (1k) to the ADS1015 A0 |
| 8 | V+ | 3V3A, with 0.1 uF to GND |

Also add R11 (10k) from VREF to the reference electrode wire.

## 3. Stage B: instrumentation amplifier
### U1 INA333 pin table
| Pin | Name | Connect to |
|-----|------|------------|
| 1 | RG | Rg1 (11k, 0.1% preferred) to pin 8 |
| 2 | VIN- | R4 (1k) to Electrode -; C4 (1 nF) to VREF; C5 (10 nF) to pin 3; R6 (10 M, optional) to VREF |
| 3 | VIN+ | R3 (1k) to Electrode +; C3 (1 nF) to VREF; C5 to pin 2; R5 (10 M, optional) to VREF |
| 4 | V- | GND |
| 5 | REF | **VREF** |
| 6 | VOUT | C1 (1 uF), then node X |
| 7 | V+ | 3V3A, with 0.1 uF to GND |
| 8 | RG | Rg1 to pin 1 |

**Check B1 (inputs shorted):** Connect the Electrode + and Electrode - pads together *and to VREF*. Measure U1 pin 6: expect **1.65 V +/- 0.1 V**. If it's stuck near 0 V or 3.3 V, see Troubleshooting.

## 4. Stage C: filter and gain stage
1. Node X: C1 (from U1 pin 6) and R9 (8.2k to VREF) meet here, then go to U2 pin 5.
2. Wire U2B as in the pin table (pins 5-8).
3. **Check C1 (inputs still shorted to VREF):** U2 pin 7 reads **1.65 V +/- 0.1 V**.

## 5. Test with a known signal (no electrodes on you!)
Use a phone tone-generator app and a 3.5 mm cable. Keep the phone away from the mains charger.

1. Cut the cable. Connect the **sleeve (ground)** to **VREF**. Connect the **tip** through **100 kOhm** to a test point T.
2. Connect T to Electrode + (the R3 input pad). Put a **100 Ohm** resistor from T to VREF. Connect Electrode - to VREF. This divides the source by about **1001**.
3. **Your multimeter cannot measure this signal.** Cheap meters such as the DT830D have AC ranges that start at 200 V. Use the ADS1015 and ESP32 instead (wire them first, as in Section 6) and read the swing of the counts. 1 count = 1 mV.
4. First measure the **source**: before connecting the divider, feed the audio tip through a 1 kOhm resistor to the ADS1015 A0 (sleeve to A1 on the 1.65 V reference) and note the peak-to-peak swing of the counts, Vs(p-p). Play a steady 100 Hz sine at a low phone volume.
5. Then connect the divider to the amplifier and measure the swing of the counts at U2 pin 7 through the ADS1015 (R10 to A0). Expect: `Vout(p-p) = Vs(p-p) / 1001 x 513 x filter factor`.

Example: Vs(p-p) = 1000 counts gives about 490 counts peak-to-peak at 100 Hz (factor 0.96).

| Frequency | Relative factor | Meaning |
|-----------|-----------------|---------|
| 10 Hz | 0.46 | high-pass cutting |
| 20 Hz | 0.72 | about -3 dB corner |
| 100 Hz | 0.96 | passband |
| 200 Hz | 0.92 | passband |
| 470 Hz | 0.71 | about -3 dB corner |
| 1000 Hz | 0.42 | low-pass cutting |

Within about +/-15% is fine for the first build (resistor and capacitor tolerance). The ADS1015 samples at 1 kHz, so stop at 200 Hz for this test: higher frequencies are not measured reliably. Check the 20 Hz and 470 Hz corners later with a scope or by checking the dashboard.

## 6. ADC and ESP32
1. Wire the ADS1015: VDD to 3V3A, GND to GND, SCL to GPIO22, SDA to GPIO21, ADDR to GND (address 0x48), A0 to R10 (1k) from U2 pin 7, **A1 to VREF**. Leave ALRT open. Tie A2 and A3 to VREF.
2. **Flash first, with USB only and the analog board unpowered:** Arduino IDE -> ESP32 board support -> open `firmware/emg_firmware.ino` (1 channel) or `firmware_4ch/emg_firmware_4ch.ino`. Set `USE_BT` to **0** for bench tests. Upload.
3. Open Serial Monitor at **921600 baud**. With inputs shorted to VREF you should see lines like `123456,2` with counts near 0 (within about +/-5). If you see `# ADS fail`, check I2C wiring and address.
4. Repeat the 100 Hz test from Section 5: the counts should swing by a few hundred peak-to-peak (1 count = 1 mV; 0.5 V peak-to-peak is about 500 counts).

## 7. First recording on your body (wearable mode)
1. Set `USE_BT` to **1**, reflash (USB only), then unplug USB.
2. Switch to wearable power: battery regulator in, J1 closed.
3. Pair the ESP32 ("EMG-Logger") with your computer over Bluetooth; note the COM port or `/dev/rfcomm0`.
4. Skin prep: shave, lightly abrade, clean with alcohol, let dry. Use **two electrodes of the same type and lot** so their DC offsets match.
5. Placement: two electrodes on the muscle belly 15-20 mm apart, along the fibers; reference electrode on a bony site (elbow, wrist, collarbone).
6. Run `python emg_server.py --port <PORT>` and open `http://localhost:8000`. Calibrate rest, then max. You should see clear bursts when you flex.

## 8. Adding channels 2-4
Repeat Sections 3-4 for each channel (own INA333, OPA2333 gain stage, filters), sharing 3V3A, GND, and VREF (one VREF buffer is enough for four channels). Use one ADS1015 per channel with the ADDR wiring from the README (GND, VDD, SDA, SCL). Add one channel at a time and check each against Section 5 before moving on. If four ADS1015 boards each carry 10k I2C pull-ups, the combined pull-up is about 2.5k: that works, but you can remove pull-ups from all but one board if the bus looks noisy.

## 9. Troubleshooting
| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| VREF is 0 V or 3.3 V | Divider miswired or op-amp output shorted | Re-check R1/R2, pin 1-2 link, U2 supply pins |
| INA output (pin 6) stuck at a rail | Inputs floating (no bias return), electrode DC offset too large, or Rg wrong/open | Add R5/R6, mismatch of electrodes, check Rg1 between pins 1 and 8 |
| Output sits at 1.65 V but never moves | HPF/gain stage broken or ADS not reading | Do Section 5 at U2 pin 7; then check ADS wiring |
| Huge 50 Hz hum | Long unshielded leads, mains devices nearby | Shorter leads, shielded cable, move away from chargers, check reference electrode contact |
| Slow wandering baseline or big spikes | Electrode movement, dry skin, cable pull | Re-prep skin, strain-relieve cables, tape leads down |
| Clipped peaks on strong flexes | Gain too high | Change R7 to 24.9k (total gain about 261) and run with `--gain 261` |
| Signal too small | Poor placement/contact, electrodes too close | Move to muscle belly, separate to 20 mm, re-prep skin |
| `# ADS fail` in serial | I2C wiring, wrong address, missing power | Check SDA/SCL, ADDR pin, 3V3A at ADS VDD |
| Noise bursts every Bluetooth transmit | Radio noise coupling into analog supply | Ferrite bead + 10 uF on 3V3A, keep analog away from ESP32 antenna, extra 0.1 uF at IC pins |
| Rep counter misfires | Threshold too low or noisy baseline | Recalibrate rest, then max; fix noise first |
| Data looks choppy over USB | Baud too low | Use 921600 |
