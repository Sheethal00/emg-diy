#!/usr/bin/env python3
"""Check the real sample rate and data quality coming from the ESP32 firmware.

  python tests/check_rate.py /dev/ttyUSB0            # USB mode
  python tests/check_rate.py /dev/rfcomm0 --seconds 20

Expects lines like "micros,ch1,ch2,ch3,ch4" (4-channel firmware).
Stop other programs (the dashboard, Serial Monitor) that use the same port first.
"""
import argparse
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--seconds", type=float, default=10.0)
    a = ap.parse_args()

    ser = serial.Serial(a.port, a.baud, timeout=0.2)
    end = time.time() + a.seconds
    buf = b""
    stamps, ch1 = [], []
    messages, bad = 0, 0
    nfields = set()

    while time.time() < end:
        data = ser.read(max(1, ser.in_waiting))
        if not data:
            continue
        buf += data
        *lines, buf = buf.split(b"\n")
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.startswith(b"#"):
                messages += 1
                continue
            p = s.split(b",")
            try:
                stamps.append(int(p[0]))
                ch1.append(int(p[1]))
                nfields.add(len(p))
            except (ValueError, IndexError):
                bad += 1

    ser.close()
    print(f"Lines received: {len(stamps)}   message lines (#): {messages}   unreadable lines: {bad}")
    if len(stamps) < 20:
        print("Too little data. Check the port, baud rate and that the firmware is running.")
        return

    gaps = [(b - a_) % (2 ** 32) for a_, b in zip(stamps, stamps[1:])]
    span_s = sum(gaps) / 1e6
    rate = (len(stamps) - 1) / span_s if span_s > 0 else 0.0
    mean_gap = sum(gaps) / len(gaps)
    late = sum(1 for g in gaps if g > 2000)

    print(f"Fields per line: {sorted(nfields)}")
    print(f"Sample rate from timestamps: {rate:.1f} Hz (target 1000)")
    print(f"Mean gap: {mean_gap:.0f} us   largest gap: {max(gaps)} us   gaps over 2 ms: {late}")
    print(f"Channel 1 counts: min {min(ch1)}, max {max(ch1)}, mean {sum(ch1) / len(ch1):.1f}")
    if rate < 950:
        print("VERDICT: slower than 1 kHz. Missing ADS1015 chips can slow the loop; try with all chips present.")
    elif late > len(gaps) * 0.02:
        print("VERDICT: rate is fine on average, but there are many late samples. Possibly Bluetooth or USB jitter.")
    else:
        print("VERDICT: sample rate looks good.")


if __name__ == "__main__":
    main()
