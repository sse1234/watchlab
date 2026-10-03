#!/usr/bin/env python3
"""Grab a decimated capture from the Red Pitaya (stock SCPI server) and show a spectrum.

Milestone 2/3 tool: "do we see the Ushio at all, and at what frequency (8*p Hz)?"

Usage:
  ./capture.py                      # autodetect rp-xxxxxx.local via mDNS, IN1, dec 65536
  ./capture.py --host 192.168.178.x --ch 1 2 --dec 65536 --avg 4
  ./capture.py --file data/cap_....npz   # re-plot a saved capture

Prerequisite on the RP: SCPI server running (web UI -> "SCPI server" -> run,
or `ssh root@rp-xxxxxx.local systemctl start redpitaya_scpi`, password root).
"""
import argparse, socket, subprocess, sys, time, datetime, pathlib
import numpy as np
from scipy.signal import welch, find_peaks

ADC_CLK = 125e6
BUF = 16384

def find_rp():
    try:
        out = subprocess.run(["avahi-browse", "-t", "-r", "-p", "_http._tcp"],
                             capture_output=True, text=True, timeout=6).stdout
    except Exception:
        return None
    for line in out.splitlines():
        f = line.split(";")
        if len(f) > 7 and f[0] == "=" and f[3].lower().startswith("rp-") and f[2] == "IPv4":
            return f[7]
    return None

class Scpi:
    def __init__(self, host, port=5000, timeout=20):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.f = self.s.makefile("rb")
    def tx(self, cmd):
        self.s.sendall((cmd + "\r\n").encode())
    def q(self, cmd):
        self.tx(cmd)
        return self.f.readline().decode().strip()
    def close(self):
        self.s.close()

def acquire(sc, chans, dec, gain="LV"):
    sc.tx("ACQ:RST")
    sc.tx(f"ACQ:DEC {dec}")
    for c in chans:
        sc.tx(f"ACQ:SOUR{c}:GAIN {gain}")
    sc.tx("ACQ:DATA:FORMAT ASCII")
    sc.tx("ACQ:DATA:UNITS VOLTS")
    sc.tx("ACQ:TRig:DLY 8192")      # trigger in the middle -> full buffer after fill
    sc.tx("ACQ:AVG ON")
    sc.tx("ACQ:START")
    time.sleep(0.2)
    sc.tx("ACQ:TRig NOW")
    fs = ADC_CLK / dec
    t_fill = BUF / fs
    t0 = time.time()
    while True:
        if sc.q("ACQ:TRig:STAT?") == "TD":
            break
        if time.time() - t0 > t_fill + 10:
            raise RuntimeError("trigger never fired")
        time.sleep(0.2)
    # newer OS exposes buffer-fill flag; fall back to waiting one buffer time
    t0 = time.time()
    while True:
        r = sc.q("ACQ:TRig:FILL?")
        if r == "1":
            break
        if r not in ("0",) or time.time() - t0 > t_fill + 5:
            time.sleep(max(0, t_fill - (time.time() - t0)))
            break
        time.sleep(0.2)
    data = {}
    for c in chans:
        raw = sc.q(f"ACQ:SOUR{c}:DATA?")
        raw = raw.strip("{}").replace("ERR!", "")
        data[c] = np.array([float(x) for x in raw.split(",") if x.strip()])
    sc.tx("ACQ:STOP")
    return fs, data

def report(fs, x, label, fmax=250.0):
    x = x - x.mean()
    nper = min(len(x), 8192)
    f, p = welch(x, fs=fs, nperseg=nper, noverlap=nper // 2, window="hann", scaling="spectrum")
    m = f <= fmax
    f, p = f[m], p[m]
    amp = np.sqrt(p) * np.sqrt(2)              # peak amplitude of a sine in that bin
    print(f"[{label}] RMS {np.sqrt(np.mean(x**2))*1e3:8.3f} mV   "
          f"fs {fs:.2f} S/s  N {len(x)}  bin {f[1]-f[0]:.3f} Hz")
    idx, _ = find_peaks(20*np.log10(amp + 1e-12), prominence=10)
    top = sorted(idx, key=lambda i: -amp[i])[:12]
    print("   strongest lines (Hz, mV peak):")
    for i in sorted(top):
        tag = ""
        if abs(f[i] / 8 - round(f[i] / 8)) < 0.03 and f[i] > 4:
            tag = f"  <- 8*{round(f[i]/8)}"
        if abs(f[i] / 50 - round(f[i] / 50)) < 0.01:
            tag = "  <- mains harmonic"
        print(f"   {f[i]:8.2f}  {amp[i]*1e3:9.4f}{tag}")
    return f, amp

def plot(fs, data, name, fmax=250.0):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 1, figsize=(11, 7))
    for c, x in data.items():
        t = np.arange(len(x)) / fs
        ax[0].plot(t, x * 1e3, lw=0.5, label=f"IN{c}")
        f, amp = report(fs, x, f"IN{c}", fmax)
        ax[1].semilogy(f, amp * 1e3, lw=0.8, label=f"IN{c}")
    ax[0].set_xlabel("t [s]"); ax[0].set_ylabel("mV"); ax[0].legend(); ax[0].grid(alpha=.3)
    ax[1].set_xlabel("f [Hz]"); ax[1].set_ylabel("mV peak"); ax[1].legend(); ax[1].grid(alpha=.3, which="both")
    for k in range(1, int(fmax // 8) + 1):
        ax[1].axvline(8 * k, color="g", alpha=.08)
    for k in range(1, int(fmax // 50) + 1):
        ax[1].axvline(50 * k, color="r", alpha=.2, ls="--")
    fig.suptitle(name); fig.tight_layout()
    png = name + ".png"; fig.savefig(png, dpi=120); print("saved", png)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--ch", type=int, nargs="+", default=[1])
    ap.add_argument("--dec", type=int, default=65536)
    ap.add_argument("--avg", type=int, default=1, help="number of consecutive buffers to concatenate")
    ap.add_argument("--gain", default="LV", choices=["LV", "HV"])
    ap.add_argument("--fmax", type=float, default=250.0)
    ap.add_argument("--file", default=None, help="re-plot an existing .npz")
    ap.add_argument("--tag", default="cap")
    a = ap.parse_args()

    if a.file:
        z = np.load(a.file)
        data = {int(k[2:]): z[k] for k in z.files if k.startswith("ch")}
        plot(float(z["fs"]), data, a.file.rsplit(".", 1)[0], a.fmax)
        return

    host = a.host or find_rp()
    if not host:
        sys.exit("no Red Pitaya found; pass --host")
    print("connecting to", host)
    sc = Scpi(host)
    print("IDN:", sc.q("*IDN?"))
    bufs = {c: [] for c in a.ch}
    for i in range(a.avg):
        fs, d = acquire(sc, a.ch, a.dec, a.gain)
        for c in a.ch:
            bufs[c].append(d[c])
        print(f"buffer {i+1}/{a.avg}: {len(d[a.ch[0]])} samples")
    sc.close()
    data = {c: np.concatenate(v) for c, v in bufs.items()}
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = str(pathlib.Path("data") / f"{a.tag}_{stamp}_dec{a.dec}")
    np.savez(name + ".npz", fs=fs, dec=a.dec, stamp=stamp, **{f"ch{c}": x for c, x in data.items()})
    print("saved", name + ".npz")
    plot(fs, data, name, a.fmax)

if __name__ == "__main__":
    main()
