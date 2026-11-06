#!/usr/bin/env python3
"""4-channel sEMG server: serial or simulated input -> processing -> browser dashboard.

  python emg_server.py --sim                      # simulated data, open http://localhost:8000
  python emg_server.py --port COM5                # live data from the ESP32 (Bluetooth COM port)
Add --host 0.0.0.0 to open the dashboard from a phone/tablet on the same Wi-Fi (no password: trusted network only).
"""
import argparse, csv, itertools, json, math, os, queue, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from scipy import signal

FS = 1000
NCH = 4
MV_PER_COUNT = 1.0  # ADS1015 at +/-2.048 V
PAIRS = list(itertools.combinations(range(NCH), 2))
HERE = os.path.dirname(os.path.abspath(__file__))


def median_freq(x):
    if len(x) < 128:
        return float("nan")
    f, P = signal.welch(x, FS, nperseg=min(256, len(x)))
    c = np.cumsum(P)
    return float(f[np.searchsorted(c, c[-1] / 2)])


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, np.ndarray)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not math.isfinite(o) else round(float(o), 3)
    if isinstance(o, np.integer):
        return int(o)
    return o


# ---------------------------------------------------------------- sources
class SimSource:
    name = "SIMULATED"

    def __init__(self):
        self.mode = "auto"  # auto | rest | mvc (server sets rest/mvc during calibration)
        self.start, self.emitted = time.time(), 0
        self.rng = np.random.default_rng()
        self.peak = np.array([0.6, 0.25, 0.55, 0.4])   # fraction of MVC
        self.delay = np.array([0.0, 0.15, 0.0, 0.3])   # s, onset delay per channel

    def read(self):
        n = int((time.time() - self.start) * FS) - self.emitted
        if n <= 0:
            time.sleep(0.005)
            return None
        t = (self.emitted + np.arange(n)) / FS
        self.emitted += n
        x = np.empty((n, NCH))
        for c in range(NCH):
            if self.mode == "rest":
                a = np.zeros(n)
            elif self.mode == "mvc":
                a = np.ones(n)
            else:
                ph = (t - self.delay[c]) % 4.0
                a = np.where(ph < 1.6, 0.5 * (1 - np.cos(2 * np.pi * ph / 1.6)), 0.0) * self.peak[c]
            x[:, c] = self.rng.normal(size=n) * (4 + 300 * a)  # uV rms
        return x


class SerialSource:
    name = "LIVE"
    mode = "auto"

    def __init__(self, port, baud, gain):
        import serial
        self.port, self.baud = port, baud
        self.ser = serial.Serial(port, baud, timeout=0.05)
        self.buf, self.gain = b"", gain

    def _reopen(self):
        # Bluetooth ports can fail a read right after opening or when the link drops: retry, don't crash.
        import serial
        try:
            self.ser.close()
        except Exception:
            pass
        print("Port read failed (link dropped or not connected yet). Retrying...")
        time.sleep(1.0)
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            self.buf = b""
        except (serial.SerialException, OSError):
            pass

    def read(self):
        import serial
        try:
            if not self.ser.is_open:
                raise serial.SerialException("port closed")
            data = self.ser.read(max(1, self.ser.in_waiting))
        except (serial.SerialException, OSError):
            self._reopen()
            return None
        if not data:
            return None
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        rows = []
        for ln in lines:
            p = ln.strip().split(b",")
            # 4-channel firmware: micros,ch1..ch4.  1-channel firmware: micros,ch1 (channels 2-4 are padded with 0).
            if len(p) == NCH + 1 or len(p) == 2:
                try:
                    v = [int(x) for x in p[1:]]
                    if len(v) == 1:
                        v += [0] * (NCH - 1)
                    rows.append(v)
                except ValueError:
                    pass
        if not rows:
            return None
        return np.array(rows, float) * MV_PER_COUNT / self.gain * 1000.0  # uV at the electrode


# ---------------------------------------------------------------- rep detection
class RepDetector:
    def __init__(self, on_pct, min_ms=100):
        self.on, self.off, self.min_ms, self.active = on_pct, 0.7 * on_pct, min_ms, False

    def update(self, t, filt, pct):
        done, onsets = [], []
        for ti, fi, pi in zip(t, filt, pct):
            if not self.active:
                if pi >= self.on:
                    self.active, self.t0, self.seg, self.pk, self.sm = True, ti, [fi], pi, pi
                    onsets.append(ti)
            else:
                self.seg.append(fi)
                self.pk = max(self.pk, pi)
                self.sm += pi
                if pi < self.off:
                    self.active = False
                    dur = ti - self.t0
                    if dur * 1000 >= self.min_ms:
                        done.append(dict(t0=self.t0, dur=dur, peak=self.pk, mean=self.sm / len(self.seg),
                                         mdf=median_freq(np.array(self.seg))))
        return done, onsets


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, src, outdir):
        self.src, self.outdir = src, outdir
        self.lock = threading.RLock()
        self.clients = []
        self.sos = signal.butter(4, [20, 450], btype="band", fs=FS, output="sos")
        self.zi = [np.zeros((self.sos.shape[0], 2)) for _ in range(NCH)]
        self.tail = np.zeros((NCH, 99))
        self.n_total = 0
        self.rest_mean, self.rest_std = np.full(NCH, 5.0), np.full(NCH, 1.0)
        self.mvc = np.full(NCH, 200.0)
        self.N = 5 * FS
        self.pctbuf = np.zeros((NCH, self.N))
        self.dw, self.de = [], []
        self.cal, self.rec = None, None
        self.rebuild()

    # -- state
    def rebuild(self):
        on_uv = np.maximum(self.rest_mean + 5 * self.rest_std, 0.10 * self.mvc)
        self.on_pct = on_uv / self.mvc * 100
        self.det = [RepDetector(self.on_pct[c]) for c in range(NCH)]
        self.reps = [[] for _ in range(NCH)]
        self.onset = [None] * NCH

    def command(self, m):
        with self.lock:
            c = m.get("cmd")
            if c in ("cal_rest", "cal_mvc") and self.cal is None:
                self.cal = dict(kind=c, env=[], seen=0)
                self.src.mode = "rest" if c == "cal_rest" else "mvc"
            elif c == "reset":
                self.rebuild()
            elif c == "record":
                self.set_record(bool(m.get("on")), re.sub(r"[^A-Za-z0-9_-]", "", str(m.get("name", "session"))) or "session")

    def set_record(self, on, name):
        if on and self.rec is None:
            os.makedirs(self.outdir, exist_ok=True)
            base = os.path.join(self.outdir, f"{name}_{time.strftime('%Y%m%d_%H%M%S')}")
            rf, pf = open(base + "_raw.csv", "w", newline=""), open(base + "_reps.csv", "w", newline="")
            self.rec = dict(rf=rf, pf=pf, raw=csv.writer(rf), reps=csv.writer(pf), base=base)
            self.rec["raw"].writerow(["t_s"] + [f"raw_uV_ch{i+1}" for i in range(NCH)] + [f"env_uV_ch{i+1}" for i in range(NCH)])
            self.rec["reps"].writerow(["channel", "rep", "t_start_s", "dur_s", "peak_pctMVC", "mean_pctMVC", "median_freq_Hz"])
            print("Recording to", base + "_*.csv")
        elif not on and self.rec:
            self.rec["rf"].close()
            self.rec["pf"].close()
            self.rec = None

    # -- processing
    def process(self, x):
        n = len(x)
        t = (self.n_total + np.arange(n)) / FS
        self.n_total += n
        filt, env = np.empty((NCH, n)), np.empty((NCH, n))
        for c in range(NCH):
            f, self.zi[c] = signal.sosfilt(self.sos, x[:, c], zi=self.zi[c])
            sq = np.concatenate([self.tail[c], f ** 2])
            env[c] = np.sqrt(np.convolve(sq, np.ones(100) / 100, "valid"))  # 100 ms RMS
            self.tail[c] = sq[-99:]
            filt[c] = f
        if self.cal:
            self.cal["env"].append(env)
            self.cal["seen"] += n
            if self.cal["seen"] >= int(5.5 * FS):
                self.finish_cal()
        pct = env / self.mvc[:, None] * 100
        for c in range(NCH):
            done, onsets = self.det[c].update(t, filt[c], pct[c])
            if onsets:
                self.onset[c] = onsets[-1]
            for r in done:
                self.reps[c].append(r)
                if self.rec:
                    self.rec["reps"].writerow([c + 1, len(self.reps[c]), f"{r['t0']:.3f}", f"{r['dur']:.3f}",
                                               f"{r['peak']:.1f}", f"{r['mean']:.1f}", f"{r['mdf']:.1f}"])
        self.pctbuf = np.concatenate([self.pctbuf, pct], axis=1)[:, -self.N:]
        self.dw.append(filt)
        self.de.append(pct)
        if self.rec:
            self.rec["raw"].writerows(np.column_stack([t, x, env.T]).round(3))

    def finish_cal(self):
        e = np.concatenate(self.cal["env"], axis=1)[:, FS // 2:]  # drop 0.5 s settling
        if self.cal["kind"] == "cal_rest":
            self.rest_mean, self.rest_std = e.mean(axis=1), e.std(axis=1)
        else:
            self.mvc = np.maximum(np.percentile(e, 95, axis=1), 1.0)
        self.src.mode = "auto"
        self.cal = None
        self.rebuild()

    # -- metrics + message
    def pair_metrics(self):
        out = {}
        for a, b in PAIRS:
            A, B = self.pctbuf[a], self.pctbuf[b]
            mask = (A >= self.on_pct[a]) | (B >= self.on_pct[b])  # only count active time
            if mask.sum() > 50:
                Am, Bm = A[mask], B[mask]
                ma, mb = Am.mean(), Bm.mean()
                bal = (ma - mb) / (ma + mb) * 100
                cci = 2 * np.minimum(Am, Bm).sum() / (Am + Bm).sum() * 100
            else:
                ma = mb = bal = cci = 0.0
            ta, tb = self.onset[a], self.onset[b]
            lag = (tb - ta) * 1000 if ta is not None and tb is not None and abs(ta - tb) < 1.0 else None
            out[f"{a+1}-{b+1}"] = dict(a=ma, b=mb, bal=bal, cci=cci, lag=lag)
        return out

    def make_msg(self):
        dw = np.concatenate(self.dw, axis=1) if self.dw else np.zeros((NCH, 0))
        de = np.concatenate(self.de, axis=1) if self.de else np.zeros((NCH, 0))
        k = dw.shape[1] // 10 * 10
        w = dw[:, :k].reshape(NCH, -1, 10)
        idx = np.abs(w).argmax(axis=2)
        wave = np.take_along_axis(w, idx[..., None], axis=2)[..., 0]  # peak-hold decimation to 100 Hz
        envd = de[:, :k].reshape(NCH, -1, 10).mean(axis=2)
        self.dw, self.de = [dw[:, k:]], [de[:, k:]]
        chans = []
        for c in range(NCH):
            r = self.reps[c]
            last = r[-1] if r else None
            chg = None
            if len(r) >= 2 and math.isfinite(r[0]["mdf"]) and math.isfinite(r[-1]["mdf"]) and r[0]["mdf"] > 0:
                chg = (r[-1]["mdf"] / r[0]["mdf"] - 1) * 100
            chans.append(dict(reps=len(r), peak=last and last["peak"], mean=last and last["mean"],
                              mdf=last and last["mdf"], dur=last and last["dur"], mdf_chg=chg,
                              now=self.pctbuf[c][-50:].mean(), th=self.on_pct[c],
                              rest=self.rest_mean[c], mvc=self.mvc[c]))
        cal = None
        if self.cal:
            cal = dict(kind=self.cal["kind"], left=max(0.0, 5.5 - self.cal["seen"] / FS))
        return dict(w=wave, e=envd, ch=chans, pairs=self.pair_metrics(), cal=cal,
                    rec=bool(self.rec), src=self.src.name)

    def broadcast(self, msg):
        data = json.dumps(clean(msg)).encode()
        for q in list(self.clients):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def run(self):
        last = time.time()
        while True:
            x = self.src.read()
            if x is not None:
                with self.lock:
                    self.process(x)
            if time.time() - last >= 0.05:
                last = time.time()
                with self.lock:
                    msg = self.make_msg()
                self.broadcast(msg)


# ---------------------------------------------------------------- http
def make_handler(engine):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = open(os.path.join(HERE, "dashboard.html"), "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = queue.Queue(maxsize=200)
                engine.clients.append(q)
                try:
                    while True:
                        try:
                            self.wfile.write(b"data: " + q.get(timeout=10) + b"\n\n")
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    if q in engine.clients:
                        engine.clients.remove(q)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/cmd":
                return self.send_error(404)
            n = int(self.headers.get("Content-Length", 0))
            try:
                engine.command(json.loads(self.rfile.read(n) or b"{}"))
                body = b'{"ok":true}'
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="simulated data (no hardware)")
    ap.add_argument("--port", help="serial/Bluetooth port of the ESP32")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--gain", type=float, default=448.0, help="total analog gain")
    ap.add_argument("--http-port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--out", default="sessions")
    a = ap.parse_args()
    src = SerialSource(a.port, a.baud, a.gain) if a.port and not a.sim else SimSource()
    eng = Engine(src, a.out)
    threading.Thread(target=eng.run, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.http_port), make_handler(eng))
    srv.daemon_threads = True
    print(f"{src.name} data. Dashboard: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.http_port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        eng.set_record(False, "")


if __name__ == "__main__":
    main()
