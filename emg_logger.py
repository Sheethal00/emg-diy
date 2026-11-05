#!/usr/bin/env python3
"""DIY sEMG logger: calibration, live plot, rep detection, CSV logging."""
import argparse, csv, queue, threading, time
import numpy as np
import serial
from scipy import signal
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

FS = 1000
MV_PER_COUNT = 1.0  # ADS1015 at +/-2.048 V


def median_freq(x):
    if len(x) < 128:
        return float("nan")
    f, P = signal.welch(x, FS, nperseg=min(256, len(x)))
    c = np.cumsum(P)
    return float(f[np.searchsorted(c, c[-1] / 2)])


class Reader(threading.Thread):
    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.ser = serial.Serial(port, baud, timeout=0.2)
        self.q = queue.Queue()
        self.off, self.last, self.t0 = 0, None, None

    def run(self):
        while True:
            line = self.ser.readline().decode(errors="ignore").strip()
            try:
                us, c = line.split(",")
                us = int(us)
            except ValueError:
                continue
            if self.last is not None and us < self.last:
                self.off += 2**32  # micros() wrapped
            self.last = us
            t = (us + self.off) / 1e6
            if self.t0 is None:
                self.t0 = t
            self.q.put((t - self.t0, int(c)))


class Processor:
    def __init__(self):
        self.sos = signal.butter(4, [20, 450], btype="band", fs=FS, output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2))
        self.tail = np.zeros(99)

    def process(self, uv):
        filt, self.zi = signal.sosfilt(self.sos, uv, zi=self.zi)
        sq = np.concatenate([self.tail, filt ** 2])
        env = np.sqrt(np.convolve(sq, np.ones(100) / 100, "valid"))  # 100 ms RMS
        self.tail = sq[-99:]
        return filt, env


class RepDetector:
    def __init__(self, on_pct, min_ms=100):
        self.on, self.off, self.min_ms = on_pct, 0.7 * on_pct, min_ms
        self.active = False

    def update(self, t, filt, pct):
        done = []
        for ti, fi, pi in zip(t, filt, pct):
            if not self.active:
                if pi >= self.on:
                    self.active, self.t0 = True, ti
                    self.seg, self.pk, self.sm = [fi], pi, pi
            else:
                self.seg.append(fi)
                self.pk = max(self.pk, pi)
                self.sm += pi
                if pi < self.off:
                    self.active = False
                    dur = ti - self.t0
                    if dur * 1000 >= self.min_ms:
                        done.append((self.t0, dur, self.pk, self.sm / len(self.seg),
                                     median_freq(np.array(self.seg))))
        return done


def drain(rd, gain):
    rows = []
    while True:
        try:
            rows.append(rd.q.get_nowait())
        except queue.Empty:
            break
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 1] * MV_PER_COUNT / gain * 1000.0  # t, counts, uV at electrode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--gain", type=float, default=513.0, help="total analog gain")
    ap.add_argument("--out", default="session")
    a = ap.parse_args()

    rd = Reader(a.port, a.baud)
    rd.start()
    pr = Processor()

    def collect(sec, msg):
        input(f"\n{msg} Press Enter, then hold for {sec} s... ")
        drain(rd, a.gain)
        envs, start = [], time.time()
        while sum(len(e) for e in envs) < sec * FS:
            d = drain(rd, a.gain)
            if d is None:
                if time.time() - start > sec + 10:
                    raise SystemExit("No data received. Check connection/pairing.")
                time.sleep(0.01)
                continue
            envs.append(pr.process(d[2])[1])
        return np.concatenate(envs)[FS // 2:]  # drop first 0.5 s (filter settling)

    rest = collect(5, "RELAX the muscle completely.")
    mvc_env = collect(5, "Contract the muscle as HARD as you can.")
    rest_mean, rest_std = rest.mean(), rest.std()
    mvc = np.percentile(mvc_env, 95)
    on_uv = max(rest_mean + 5 * rest_std, 0.10 * mvc)
    on_pct = on_uv / mvc * 100
    print(f"\nRest {rest_mean:.1f} uV (sd {rest_std:.1f}), MVC {mvc:.1f} uV, "
          f"rep threshold {on_pct:.1f}% MVC")
    if mvc < 3 * rest_mean:
        print("WARNING: MVC barely above rest. Check electrode placement/contact.")

    det = RepDetector(on_pct)
    raw_f = open(f"{a.out}_raw.csv", "w", newline="")
    reps_f = open(f"{a.out}_reps.csv", "w", newline="")
    raw, reps = csv.writer(raw_f), csv.writer(reps_f)
    raw.writerow(["t_s", "counts", "uV_filtered", "env_uV"])
    reps.writerow(["rep", "t_start_s", "dur_s", "peak_pctMVC", "mean_pctMVC", "median_freq_Hz"])
    count = 0

    N = 5 * FS
    tb, fb, eb = np.zeros(N), np.zeros(N), np.zeros(N)
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    (l1,) = ax1.plot([], [], lw=0.6)
    (l2,) = ax2.plot([], [], color="C1")
    ax2.axhline(on_pct, ls="--", color="gray")
    ax1.set_ylabel("EMG (uV, filtered)")
    ax2.set_ylabel("% MVC (100 ms RMS)")
    ax2.set_xlabel("seconds")
    ax1.set_xlim(-5, 0)
    txt = ax2.text(0.01, 0.9, "", transform=ax2.transAxes)

    def update(_):
        nonlocal tb, fb, eb, count
        d = drain(rd, a.gain)
        if d is None:
            return l1, l2, txt
        t, c, uv = d
        f, e = pr.process(uv)
        pct = e / mvc * 100
        raw.writerows(zip(t, c, f, e))
        for r in det.update(t, f, pct):
            count += 1
            reps.writerow([count] + [f"{x:.3f}" for x in r])
            print(f"Rep {count}: {r[1]:.2f}s peak {r[2]:.0f}% mean {r[3]:.0f}% MDF {r[4]:.0f} Hz")
        tb = np.concatenate([tb, t])[-N:]
        fb = np.concatenate([fb, f])[-N:]
        eb = np.concatenate([eb, pct])[-N:]
        x = tb - tb[-1]
        l1.set_data(x, fb)
        l2.set_data(x, eb)
        lim = max(200, np.abs(fb).max() * 1.1)
        ax1.set_ylim(-lim, lim)
        ax2.set_ylim(0, max(120, eb.max() * 1.1))
        txt.set_text(f"Reps: {count}")
        return l1, l2, txt

    ani = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    try:
        plt.show()
    finally:
        raw_f.close()
        reps_f.close()
        print(f"Saved {a.out}_raw.csv and {a.out}_reps.csv")


if __name__ == "__main__":
    main()
