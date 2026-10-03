#!/usr/bin/env python3
"""First-look capture through the Behringer UMC202HD on USB (no Red Pitaya yet).

Records N seconds from the interface via PipeWire, decimates to ~2 kS/s and
runs the same spectrum/report as capture.py.

  ./audio_capture.py                 # 20 s, input 1 (XLR 1), spectrum to 250 Hz
  ./audio_capture.py --sec 60 --ch 1 2 --fmax 500
  ./audio_capture.py --file data/aud_....npz
"""
import argparse, subprocess, datetime, pathlib, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import decimate
from capture import plot

RATE = 48000

def find_source(mic=1):
    out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) > 1 and "monitor" not in f[1] and ("UMC" in f[1] or "U202" in f[1]):
            if ("Mic%d" % mic) in f[1] or "Mic" not in f[1]:
                return f[1]
    return None

def record(src, sec, wav):
    cmd = ["pw-record", "--target", src, "--rate", str(RATE), "--channels", "1",
           "--format", "f32", wav]
    print("recording", sec, "s from", src)
    p = subprocess.Popen(cmd)
    try:
        p.wait(timeout=sec)
    except subprocess.TimeoutExpired:
        p.terminate(); p.wait()
    if p.returncode not in (0, 1, -15):
        sys.exit(f"pw-record failed ({p.returncode})")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=20)
    ap.add_argument("--ch", type=int, nargs="+", default=[1])
    ap.add_argument("--q", type=int, default=24, help="decimation factor (48k/24 = 2 kS/s)")
    ap.add_argument("--fmax", type=float, default=250.0)
    ap.add_argument("--file", default=None)
    ap.add_argument("--wav", default=None, help="analyse an existing wav instead of recording")
    ap.add_argument("--tag", default="aud")
    ap.add_argument("--mic", type=int, default=1, help="Behringer input 1 or 2")
    a = ap.parse_args()

    if a.file:
        z = np.load(a.file)
        plot(float(z["fs"]), {int(k[2:]): z[k] for k in z.files if k.startswith("ch")},
             a.file.rsplit(".", 1)[0], a.fmax)
        return

    src = find_source(a.mic)
    if not src and not a.wav:
        sys.exit("UMC202HD not found in `pactl list short sources` -- plugged in?")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = str(pathlib.Path("data") / f"{a.tag}_{stamp}")
    if a.wav:
        name = a.wav.rsplit(".", 1)[0]
    else:
        record(src, a.sec, name + ".wav")
    rate, x = wavfile.read(name + ".wav")
    x = x.astype(np.float64)
    if not np.issubdtype(wavfile.read(name + ".wav")[1].dtype, np.floating):
        x /= 2**31                               # full scale = 1.0
    if x.ndim == 1:
        x = x[:, None]
    print(f"got {len(x)/rate:.1f} s at {rate} Hz; full-scale peak ch1 {np.abs(x[:,0]).max():.3f}"
          + (f", ch2 {np.abs(x[:,1]).max():.3f}" if x.shape[1] > 1 else ""))
    if np.abs(x).max() > 0.98:
        print("!! clipping -- turn the gain down")
    data = {}
    for c in a.ch:
        y = x[:, c - 1]
        y = decimate(y, 4, ftype="fir", zero_phase=True)
        y = decimate(y, a.q // 4, ftype="fir", zero_phase=True) if a.q > 4 else y
        data[c] = y
    fs = rate / a.q
    np.savez(name + ".npz", fs=fs, dec=a.q, stamp=stamp, **{f"ch{c}": v for c, v in data.items()})
    print("saved", name + ".npz")
    plot(fs, data, name, a.fmax)   # units are full-scale*1e3 ("mV" label = milli-FS)

if __name__ == "__main__":
    main()
