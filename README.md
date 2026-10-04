# watchlab

Non-invasive watch rate measurement (see HANDOVER.md). Python env: `uv venv .venv && uv pip install -r requirements.txt`
(numpy, scipy, matplotlib, allantools, pyubx2, pyserial).

## Bring-up checklist (milestone 1)
1. RP on power bank (needs 5 V / 3 A, use the bank or the supplied PSU) + Ethernet to router.
2. Wait ~1 min, then `http://rp-XXXXXX.local` (XXXXXX = last 6 hex digits of MAC on the sticker).
3. In the web UI start **SCPI server**, or `ssh root@rp-XXXXXX.local` (pw `root`) and
   `systemctl start redpitaya_scpi`.
4. IN1 jumper on **LV** for the Behringer output; IN2 on **HV** if the LBE reference goes there.

## First looks
- `./capture.py` -> autodetects the RP, 8.6 s on IN1 at 1.9 kS/s, prints the strongest lines,
  flags multiples of 8 Hz and mains harmonics, saves `data/*.npz` + `.png`.
- `./capture.py --ch 1 2 --avg 4` -> both channels, 34 s record.
- `./capture.py --file data/cap_....npz` -> re-plot.

## First result (2026-10-03, Behringer USB path, `audio_capture.py`)
Ushio on coil A, single coil, no gradiometer, gain ~3/4, laptop on battery. Peak 3.3 % of full scale.
- 8 Hz fundamental + harmonics 16/24/32/40/48 Hz (rotor, p = 1).
- 256 Hz (= 32768/128, crystal-derived chopper) with ±8 Hz sidebands *stronger* than the carrier
  (DSB: 248/264 Hz at 3.3 mFS, 256 at 1.8 mFS); same pattern repeats at 512, 768, 1024 Hz.
- 50 Hz hum 0.38 mFS, ~10x below the signal lines and not near any line of interest. No gradiometer needed.
- Rotor phase vs. crystal/32 wanders ~3 ms rms (loop jitter), OADEV(rotor) ~2e-3 @1 s, 1e-4 @40 s.
- The USB audio path is useless as a time base: PipeWire rate matching gives ~250 us sawtooth
  timing error (common to all lines; cancels in rotor/crystal ratio). Absolute numbers need the RP.
Use for the lock-in: 264 Hz (or 256) for the crystal, 8 Hz for the rotor. Avoid 248 Hz (2 Hz from the
mains 5th harmonic at 250).

Listen: `data/ushio_9rb1_coil_20s.mp3` (20 s from the 120 s record, peak-normalised, 1.5 s fade in / 3 s fade out, mono to both channels).

### The 256 Hz family is the rotor EMF chopped at 256 Hz (2026-10-04)
Demodulating the 256 Hz band (`data/ushio_256Hz_envelope.png`): modulation index ~3.6, envelope goes to zero
twice per rotor turn, in-phase component flips sign. The raw waveform is a 256 Hz spike train whose amplitude and
polarity follow the 8 Hz rotor sine, i.e. the brake switching the generator coil at 256 Hz = DSB with almost no
carrier (0.9 mFS carrier vs 3.3 mFS sidebands). Modulation correlates -0.97 with the 8 Hz line at a quarter-turn lag
(one derivative apart). Envelope peaks alternate 4.4 / 3.6 mFS between half turns (16 Hz term): half-turn asymmetry.
Consequence: lock in on the 248/264 Hz *pair*: (phi264 + phi248)/2 = chopper (crystal) phase, (phi264 - phi248)/2 =
rotor phase. Do not rely on the 256 Hz carrier alone.
