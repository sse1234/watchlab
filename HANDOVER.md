# Watch Timing Lab — Handover

Goal: measure the frequency drift and short-term stability of two wristwatches non-invasively, referenced to GPS, over multi-day runs, with a Red Pitaya Gen 2 as the acquisition platform. Everything below was worked out in conversation; nothing has been built yet.

## 1. Devices under test

| Watch | Movement | Signal source | Expected observable |
|---|---|---|---|
| Grand Seiko SLGB023 "Ushio 300" | 9RB1 Spring Drive U.F.A. | Glide wheel carries a multipole permanent magnet rotating at exactly 8 rev/s, regulated by quartz via electromagnetic braking | Continuous magnetic carrier at **8·p Hz** (p = pole pairs, unknown, probably 2–8) plus 8 Hz braking sidebands |
| Grand Seiko SBGP007 | 9F85 quartz | Lavet stepper drive pulse once per second + rotor flip | 1 Hz magnetic transient, few ms wide, edge derived from 32,768 Hz crystal via divider |

Spec accuracies: 9RB1 ±20 s/year (≈0.6 ppm), 9F85 ±10 s/year (≈0.3 ppm). Quartz short-term ADEV ~1e-8 at 1 s; Spring Drive adds control-loop phase jitter on top at short τ.

Spring Drive specifics that matter:
- The IC only regulates glide-wheel *rate* against the crystal. Hands' position is the only time state. Any hand slip is invisible to the IC.
- The 9RB1 is thermocompensated via a factory TC table (temperature sampled 540×/day). Rate-at-temperature is what a short run measures; ageing drift needs repeated runs.
- Both watches ignore 50 Hz hum physically; the *measurement* may not.

## 2. Hardware on hand

- **Red Pitaya STEMlab 125-14 Gen 2** — 2× ADC inputs (SMA female), LV ±1 V / HV ±20 V jumper, 125 MS/s, FPGA (Zynq), Linux on ARM, USB host, Ethernet, E1 header with 3.3 V LVCMOS digital I/O.
- **Leo Bodnar LBE-1420 GPSDO** — 10 MHz + 1 PPS + programmable output, 3.3 V CMOS, SMA female. USB port exposes the u-blox (UBX) stream for fix status / timepulse quantization error.
- **Behringer UMC202HD** — used purely as an analog preamp via Direct Monitor (no USB audio). Midas preamp, ~60 dB gain, balanced XLR input, TRS line out + headphone out. Flat to <20 Hz (corner probably ~5 Hz, to be measured). Headroom limited (clips ~0.5–1 V), rails from USB 5 V.
- **2× Eagle A171 telephone pickup coils** — inductive, ~1 kΩ, ferrite core, suction cup, single-conductor shielded lead ending in a mono 3.5 mm plug (centre = one coil end, shield = other).
- **Nooelec HF LaNA** — NOT usable here (50 kHz lower limit, 50 Ω). Ignore.
- Spare OCXO board — NOT needed; DUT-limited by 2 orders of magnitude. Ignore for this project.
- TE0802 FPGA board — NOT needed. Red Pitaya covers everything.
- DS18B20 (to buy if not present) for temperature logging.
- USB power bank with multiple ports.
- Adapters: SMA-male→BNC-female, BNC-male→screw terminal, ¼" TS→BNC, bootlace ferrules. Cable: RG-174/RG-316 for single-ended links, shielded twisted pair (mic cable) only if coils get rewired.

## 3. Signal chain

```
Coil A (watch on it) ─┐
                      ├─ anti-series ──► UMC202HD XLR in 1 ──► Direct Monitor ──► TRS out ──► RP IN1 (LV)
Coil B (gradiometer) ─┘

LBE-1420 1 PPS ──(100 Ω series)──► RP E1 digital input (3.3 V)        ← hardware timestamp in FPGA
LBE-1420 USB ──► RP USB host (UBX stream: fix, sats, qErr)             ← optional, for masking unlocked intervals

DS18B20 ──► RP E2/1-wire or GPIO                                        ← temperature, 1 sample/s

RP Ethernet ──► laptop (galvanically isolated)
```

Coil wiring with stock leads (balanced, nothing grounded):
- Coil A centre → XLR pin 2
- Coil A shield joined to Coil B shield at terminal block
- Coil B centre → XLR pin 3
- XLR pin 1 unconnected
- Watch caseback flat on Coil A; Coil B a few cm away, same orientation, no watch. Trim B position/angle to null the 50 Hz line.

Single-coil fallback: centre → pin 2, shield → pin 3, pin 1 open.

Behringer: gain so carrier sits ~100–300 mV at output. Watch for hum-driven clipping (hum clips before signal does).

Power: **everything analog on the power bank**, no mains connection to the rig. Red Pitaya may not run from Framework 13 USB-C (needs 5 V/3 A, may not negotiate) — use the bank or the supplied PSU. Laptop talks to RP via Ethernet/Wi-Fi only.

Reference path alternative (if digital timestamper isn't ready): LBE programmable output (e.g. a few hundred Hz square) → SMA cable → RP IN2 on **HV** jumper. No attenuator needed. Then both channels share the ADC clock and the lock-in handles both.

## 4. Why the design is this way (constraints)

- **Ratio measurement**: everything is measured as a frequency/phase ratio against the GPS reference captured on the *same* time base (ADC sample clock or FPGA counter). The Red Pitaya's own crystal cancels. Never rely on absolute sample rate.
- **Don't timestamp edges at low sample rate**: at a few kS/s a zero crossing falls between samples. Use a **lock-in estimator** (multiply by sin/cos at nominal f, integrate, atan2) on every sample. Phase precision ∝ 1/(SNR·√N).
- **Phase stability of the analog chain matters, not just gain**: a high-pass at f_c adds ~f_c/f rad of lead at the carrier; if that phase *wanders* (temperature) it looks like frequency error while it moves. Keep carrier ≥10× above the Behringer corner; keep the rig at constant temperature; log temperature.
- **Hum**: lock-in rejects hum unless carrier is within a fraction of a Hz of 50 Hz or a harmonic. First result needed: the value of p. If 8p lands at 48 or 56 Hz, work on the 8 Hz sidebands or the gradiometer.
- **The coil is the antenna**: adapter/terminal pickup is ~10⁴ below the coil's own ambient pickup. Fix hum at the coil (gradiometer, steel/mu-metal can), not at connectors.

## 5. Software plan (on the Red Pitaya)

### 5.1 FPGA side (minimal custom logic, or use what the stock image offers)
- Free-running 64-bit counter at 125 MHz.
- Latch counter on rising edge of PPS input → register readable by ARM (one event/s). 8 ns resolution → 8e-9 per PPS, ~1e-11 over 1000 s.
- Decimated ADC stream (CIC/FIR decimation to 1–2 kS/s) with each sample block tagged by the same counter, so lock-in phase and PPS timestamps share a time base.
- Fallback if FPGA work stalls: stock acquisition at decimation 65536 (≈1.9 kS/s) on both inputs, reference on IN2, pure software.

### 5.2 Logger (C or Python on ARM, one process, systemd service, writes to SD)
Per 1-second record:
- `t_pps` (counter value at PPS), `t_block` (counter at block start)
- lock-in I/Q for carrier on IN1 → amplitude, phase; also I/Q at nominal 8 Hz sideband(s)
- (IN2 I/Q if analog reference path is used)
- noise estimate (residual RMS after removing carrier)
- temperature
- UBX: fix type, numSV, timepulse qErr (if USB to LBE works; else photodiode on lock LED → GPIO as crude lock flag)
Format: append-only CSV or Parquet, one file per hour. 48 h ≈ 50 MB. Keep raw decimated PCM optionally (1.4 GB/48 h) for the first runs only.

### 5.3 Analysis (offline, laptop, Python)
- Unwrap carrier phase; compute fractional frequency vs. PPS timestamps.
- Allan deviation (allantools) vs τ from 1 s to 10⁴ s. Expect loop-jitter-dominated at short τ with a corner where the quartz takes over — that corner is the Spring Drive regulator bandwidth (unpublished).
- Correlate rate with temperature.
- Repeat runs monthly → ageing slope.
- For the 9F: detect 1 Hz pulses on the coil channel, timestamp only the **first** edge per second (ignore twin-pulse corrective pulses within ~100 ms, ignore midnight date-change burst), same ADEV pipeline.

### 5.4 Characterization before the first watch run (same pipeline, free dry run)
1. **Transfer function of the Behringer path**: RP OUT1 generator at ~100 mV through a 1000:1 divider (100 kΩ/100 Ω) into XLR, Direct Monitor out → IN1, generator also → IN2. Step 1 Hz…1 kHz. Record magnitude *and phase* per frequency and per gain setting.
2. **Noise floor**: 1 kΩ resistor across XLR input (mimics coil), high gain, record minutes, divide by measured gain → equivalent input noise in 10–100 Hz band. Target: within 2× of the coil's 4 nV/√Hz thermal floor. Look for supply spurs.
3. **Find p**: watch on coil, spectrum of IN1. Identify 8·p Hz line and 8 Hz sidebands. This single screenshot fixes the carrier frequency, signal level, hum situation.

## 6. Milestones

1. Bring up RP Gen 2 on power bank + Ethernet; verify both inputs and E1 digital input.
2. Cables/adapters; coil A into Behringer; see any signal from the Ushio on IN1 at all.
3. Determine p, signal level, hum. Decide gradiometer vs single coil.
4. Behringer transfer function + noise characterization (5.4).
5. Software lock-in on IN1 with analog LBE reference on IN2 (quick path). First ADEV plot, even if only 1 hour.
6. FPGA PPS timestamper; move reference to digital input; free IN2.
7. DS18B20 + UBX logging; systemd service; 48 h run.
8. Second DUT (SBGP007 on coil B, IN2) in the same run.
9. Monthly repeats for ageing.

## 7. Things explicitly decided against
- LaNA as preamp (wrong band, wrong impedance).
- OCXO disciplined by LBE (no benefit at DUT-limited precision; loop design risk).
- TE0802 / custom USB audio core (unnecessary; RP has ADC + Linux).
- Edge timestamping at low sample rate (use lock-in).
- Powering rig from laptop/mains (ground loops; RP power negotiation).
- Acoustic sensing of the 32 kHz crystal (hermetic can, no airborne sound; MEMS mic can only hear the stepper tick — optional second modality for the 9F).

## 8. Open questions
- Exact p for the 9RB1 rotor (measure).
- Behringer high-pass corner and phase slope (measure).
- Whether the LBE's USB UBX stream is readable from the RP (libusb/pyubx2) or needs the LED-photodiode fallback.
- RP Gen 2: which E1 pin is wired to a trigger-capable FPGA input in the stock image; whether a custom bitstream is needed or the stock "external trigger" path can be abused for PPS timestamping.
- Watch temperature vs. rig temperature: a single DS18B20 under the coil is probably adequate; consider a second on the Behringer.

## 9. Numbers to keep in mind
- 8·p Hz carrier; 8 Hz loop cadence; seconds hand 1/60 rev/s; glide wheel 480× seconds-arbor speed.
- Coil thermal noise ≈4 nV/√Hz (1 kΩ, 300 K). Preamp target <8 nV/√Hz referred to input in 10–100 Hz.
- Earth field 50 µT; 1 pF at 50 Hz ≈ 3 GΩ; room stray 50 Hz field ~0.1 µT.
- 1° phase at 50 Hz = 55 µs. 1000 s window: 1e-10 needs 100 ns net timing stability.
- LV input ±1 V, HV ±20 V (2.4 mV/LSB); 3.3 V CMOS fits HV directly or E1 digital directly.
