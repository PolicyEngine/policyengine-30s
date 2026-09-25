"""Synthesize the 30-second score from the video's own event log.

The music (pad, bass, drums, arpeggio) runs on a 120 BPM grid whose bar lines
match the scene cuts; the sound effects come from events.json, which the page
exports from the same timeline that draws the frames, so every click, tick and
plink lands on the frame that causes it:

  pour   the statute pours in         word   quote words appear
  whoosh camera dive / token flight   lock   the $2,200 box locks
  ping   citation / reform value      key    code lines type in
  land   $2,200 lands in the code    curve  the family's gain drawn across earnings (brightness = gain)
  rise   into the second fact        hit    "+$1,600 from $58,000" lands
  drop   zoom out to the nation      plink  households light up ($800 step = pitch)
  stat   a statistic lands           decile a decile bar grows (pitch = height)
  swell  households become the logo  logo   the wordmark lands

usage: uv run --with numpy --with scipy --with pyloudnorm tools/soundtrack.py audio/events.json audio/score.wav
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
DUR = 30.0
N = int(SR * DUR)
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
# seeded once at import: one process renders one score (build() twice in a process would drift)
rng = np.random.default_rng(20260924)


# ------------------------------------------------------------------ helpers
def t_axis(n):
    return np.arange(n) / SR


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n, a=0.01, d=0.1, s=0.7, r=0.2, hold=None):
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    hold_n = max(0, n - a_n - d_n - r_n) if hold is None else int(hold * SR)
    e = np.concatenate([
        np.linspace(0, 1, max(a_n, 1), endpoint=False),
        np.linspace(1, s, max(d_n, 1), endpoint=False),
        np.full(hold_n, s),
        np.linspace(s, 0, max(r_n, 1)),
    ])
    return np.pad(e, (0, max(0, n - len(e))))[:n]


def exp_decay(n, tau):
    return np.exp(-t_axis(n) / tau)


def lp(x, fc, order=2):
    return sosfilt(butter(order, min(fc, SR / 2 - 100) / (SR / 2), "low", output="sos"), x)


def hp(x, fc, order=2):
    return sosfilt(butter(order, fc / (SR / 2), "high", output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)


def saw(freq, n, phase=0.0):
    inc = (np.full(n, freq) if np.isscalar(freq) else np.asarray(freq)) / SR
    ph = (phase + np.cumsum(inc)) % 1.0
    y = 2 * ph - 1
    # PolyBLEP: remove the naive ramp's aliasing at each wrap
    a = ph < inc
    tt = ph[a] / inc[a]; y[a] -= tt + tt - tt * tt - 1
    b = ph > 1 - inc
    tt = (ph[b] - 1) / inc[b]; y[b] -= tt * tt + tt + tt + 1
    return y


def tri(freq, n):
    ph = (np.cumsum(np.full(n, freq)) / SR) % 1.0
    return 2 * np.abs(2 * ph - 1) - 1


def place(buf, sig, t, gain=1.0, pan=0.0):
    """Mix a mono signal into the stereo buffer at time t with equal-power pan."""
    i = int(round(t * SR))
    if i >= buf.shape[1] or i + len(sig) <= 0:
        return
    j = min(buf.shape[1], i + len(sig))
    s = sig[max(0, -i): j - i] * gain
    i = max(0, i)
    lg, rg = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:j] += s * lg
    buf[1, i:j] += s * rg


def reverb_ir(seconds=2.4, predelay=0.012, bright=6000):
    n = int(seconds * SR)
    ir = np.zeros((2, n))
    for c in range(2):
        noise = rng.standard_normal(n) * np.exp(-t_axis(n) / (seconds / 6.5))
        ir[c] = lp(noise, bright)
    ir[:, : int(predelay * SR)] = 0
    return ir / np.sqrt((ir ** 2).sum(axis=1, keepdims=True))


IR = reverb_ir()


def verb(x, wet=0.3):
    out = np.zeros_like(x)
    for c in range(2):
        out[c] = hp(fftconvolve(x[c], IR[c])[: x.shape[1]], 250, 4)
    return x * (1 - wet) + out * wet * 1.6


# ------------------------------------------------------------------ harmony
# D minor, four chords per 8-second cycle: Dm - Bb - F - C (i - VI - III - VII)
CHORDS = [
    [50, 53, 57, 62],  # Dm
    [46, 50, 53, 58],  # Bb
    [53, 57, 60, 65],  # F
    [48, 52, 55, 60],  # C
]
ROOTS = [38, 34, 41, 36]
PENTA = [62, 65, 67, 69, 72, 74, 77, 79, 81, 84]  # D minor pentatonic, upper


def chord_at(t):
    if t >= 26: return 2          # F: the logo resolve
    if t >= 24: return 3          # C: dominant of F, sets up the resolve
    if t >= 22: return 1          # Bb
    return int(t // BAR) % 4


# ------------------------------------------------------------------ instruments
def kick():
    n = int(0.45 * SR)
    f = 48 + 110 * np.exp(-t_axis(n) / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * exp_decay(n, 0.12)
    click = hp(rng.standard_normal(n), 3000) * exp_decay(n, 0.004) * 0.35
    return np.tanh(1.6 * (body + click)) * 0.9


def hat(open_=False):
    n = int((0.22 if open_ else 0.06) * SR)
    x = hp(rng.standard_normal(n), 8000, 4) * exp_decay(n, 0.06 if open_ else 0.014)
    return x * 0.35


def clap():
    n = int(0.3 * SR)
    x = bp(rng.standard_normal(n), 900, 5000) * exp_decay(n, 0.07)
    for k, d in enumerate([0.0, 0.011, 0.022]):
        x[int(d * SR): int(d * SR) + 250] *= 1.6 - 0.2 * k
    tone = np.sin(2 * np.pi * 190 * t_axis(n)) * exp_decay(n, 0.04) * 0.3
    return (x + tone) * 0.45


def pluck(m, dur=0.28, bright=1.0):
    n = int(dur * SR)
    f = midi(m)
    x = 0.6 * saw(f, n) + 0.4 * saw(f * 1.004, n)
    cutoff_env = 800 + 5200 * bright * exp_decay(n, 0.06)
    # time-varying lowpass approximated in blocks
    out = np.zeros(n)
    blk = 64
    zi = np.zeros((1, 2))
    for s in range(0, n, blk):
        sos = butter(2, min(cutoff_env[s], SR / 2 - 100) / (SR / 2), "low", output="sos")
        out[s: s + blk], zi = sosfilt(sos, x[s: s + blk], zi=zi)
    return out * exp_decay(n, dur / 3.2) * 0.25


def felt(m, dur=0.9):
    """A soft felted mallet: mostly fundamental, a little second harmonic that dies fast,
    a short muffled contact noise, and a low-pass so nothing sparkles."""
    n = int(dur * SR)
    f = midi(m)
    t = t_axis(n)
    tone = (np.sin(2 * np.pi * f * t)
            + 0.3 * np.sin(4 * np.pi * f * t) * exp_decay(n, 0.06)
            + 0.06 * np.sin(6 * np.pi * f * t) * exp_decay(n, 0.03))
    x = tone * (1 - np.exp(-t / 0.004)) * exp_decay(n, 0.22)
    k = int(0.012 * SR)
    x[:k] += bp(rng.standard_normal(k), 600, 2400) * exp_decay(k, 0.003) * 0.25
    return lp(x, 2400) * 0.2


def pad_voice(m, n, detune=0.12):
    f = midi(m)
    x = np.zeros(n)
    for k, d in enumerate(np.linspace(-detune, detune, 5)):
        x += saw(f * 2 ** (d / 12), n, phase=rng.random())
    return x / 5


def noise_sweep(dur, f0, f1, q=0.5):
    n = int(dur * SR)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    blk = 128
    zi = np.zeros((2, 2))
    for s in range(0, n, blk):
        u = s / n
        fc = f0 * (f1 / f0) ** u
        sos = butter(2, [max(40, fc * (1 - q)) / (SR / 2), min(20000, fc * (1 + q)) / (SR / 2)], "band", output="sos")
        out[s: s + blk], zi = sosfilt(sos, x[s: s + blk], zi=zi)
    return out


# ------------------------------------------------------------------ build
def build(events):
    mus = np.zeros((2, N))   # music bus (gets ducked by the kick)
    drm = np.zeros((2, N))   # drums
    sfx = np.zeros((2, N))   # effects
    dry = np.zeros((2, N))   # transition sweeps: kept out of the reverb so they don't mask the cues
    duck = np.ones(N)

    # sections: 0 intro, 1 code, 2 family, 3 nation, 4 deciles, 5 outro
    def section(t):
        if t < 4: return 0
        if t < 8.5: return 1
        if t < 14: return 2
        if t < 20: return 3
        if t < 26: return 4
        return 5

    # pad: whole piece, swelling with the story
    for b in range(int(DUR / BAR) + 1):
        t0 = b * BAR
        if t0 >= DUR: break
        ch = CHORDS[chord_at(t0 + 0.01)]
        n = int(BAR * SR) + int(0.6 * SR)
        v = sum(pad_voice(m + 12, n) for m in ch) / len(ch)
        v2 = sum(pad_voice(m + 12, n) for m in ch) / len(ch)
        sec = section(t0 + 0.01)
        bright = [1300, 1400, 1800, 2600, 2600, 1600][sec]
        e_ = env_adsr(n, a=0.25 if b else 0.35, d=0.3, s=0.8, r=0.6)
        v = lp(v, bright, 2) * e_; v2 = lp(v2, bright, 2) * e_
        g = [0.26, 0.17, 0.17, 0.21, 0.21, 0.24][sec]
        place(mus, v, t0, g, -0.6)
        place(mus, v2, t0, g, 0.6)

    # sub drone in the intro
    n = int(4.2 * SR)
    drone = np.sin(2 * np.pi * midi(50) * t_axis(n)) * np.linspace(0.2, 1, n) ** 2 * env_adsr(n, a=0.8, d=0.2, s=0.9, r=0.5) * 0.13
    place(mus, drone, 0.0, 1.0)

    # bass: eighth notes on the root from bar 3 (t=8) through bar 13
    for k in range(int(DUR / (BEAT / 2))):
        t = k * BEAT / 2
        sec = section(t)
        if sec not in (2, 3, 4) or (sec == 2 and t < 8.5) or 11.0 <= t < 12.0:
            continue
        root = ROOTS[chord_at(t)]
        m = root + (12 if k % 4 == 3 else 0)
        n = int(BEAT / 2 * 0.92 * SR)
        x = 0.7 * saw(midi(m), n) + 0.3 * np.sign(np.sin(2 * np.pi * midi(m) * t_axis(n)))
        x = lp(x, 520 if sec == 2 else 760, 2) * env_adsr(n, a=0.004, d=0.08, s=0.6, r=0.03)
        place(mus, x, t, 0.34)

    # arpeggio: sixteenths from t=4 to t=26, chord tones across two octaves
    pattern = [0, 1, 2, 3, 2, 1, 3, 2]
    for k in range(int(DUR / (BEAT / 4))):
        t = k * BEAT / 4
        sec = section(t)
        if sec == 0 or sec == 5:
            continue
        ch = CHORDS[chord_at(t)]
        m = ch[pattern[k % 8]] + (24 if (k // 8) % 2 else 12)
        g = {1: 0.30, 2: 0.24, 3: 0.33, 4: 0.30}[sec]
        if sec == 1 and t < 4.9:
            g *= P(t, 4.0, 4.9)
        if 15.0 <= t < 17.0 or 21.0 <= t < 21.9:
            g *= 0.4
        if 20 <= t < 24 and k % 2:
            continue
        place(mus, pluck(m, 0.26, bright=0.7 if sec < 3 else 1.0), t, g, 0.35 if k % 2 else -0.35)

    # drums
    kick_s, hat_c, hat_o, clap_s = kick(), hat(), hat(True), clap()
    for k in range(int(DUR / BEAT)):
        t = k * BEAT
        sec = section(t)
        beat_in_bar = k % 4
        if sec == 1:
            if beat_in_bar in (0, 2):
                place(drm, kick_s, t, 0.5)
                duck_at(duck, t, 0.45)
            place(drm, hat_c, t + BEAT / 2, 0.22, 0.25)
            if beat_in_bar == 0 and 7.9 < t < 8.1:
                for s16 in range(4):
                    place(drm, clap_s, t + s16 * BEAT / 4, 0.12 + 0.08 * s16)
        if sec in (2, 3, 4):
            if sec == 2 and 11.0 <= t < 12.0:
                continue  # drop out under the riser
            if sec == 4 and t < 24 and beat_in_bar in (1, 3):
                continue  # half-time under the decile chart
            place(drm, kick_s, t, 0.6)
            duck_at(duck, t, 0.35)
            ripple = 15.0 <= t < 17.0
            if beat_in_bar in (1, 3) and not ripple:
                place(drm, clap_s, t, 0.55 if sec > 2 else 0.4)
            if not ripple:
                place(drm, hat_o, t + BEAT / 2, 0.35, 0.2)
            for s in (1, 3):
                place(drm, hat_c, t + s * BEAT / 4, 0.25, -0.2)
    # intro hats: quiet ticking sixteenths like a clock under the quote
    for k in range(int(4.0 / (BEAT / 4))):
        t = k * BEAT / 4
        place(drm, hat_c, t, 0.16 + 0.08 * (k % 4 == 0), 0.3 if k % 2 else -0.3)

    # ---------------------------------------------------------- effects
    for e in events:
        t, kind = e["t"], e["type"]
        if kind == "pour":
            # dry paper-tick texture while the statute pours in
            for k in range(90):
                tk = t + e["dur"] * (k / 90) ** 0.7
                n = int(0.03 * SR)
                x = bp(rng.standard_normal(n), 2000, 7000) * exp_decay(n, 0.006) * 0.12
                place(sfx, x, tk, rng.uniform(0.5, 1.0), rng.uniform(-0.8, 0.8))
        elif kind == "word":
            n = int(0.05 * SR)
            x = bp(rng.standard_normal(n), 1800, 6000) * exp_decay(n, 0.008) * 0.25
            place(sfx, x, t, 1.0, rng.uniform(-0.3, 0.3))
        elif kind == "lock":
            place(sfx, felt(62, 1.0), t, 0.7)
        elif kind == "whoosh":
            d = e.get("dur", 0.8) + 0.1
            env_w = env_adsr(int(d * SR), a=d * 0.85, d=0.02, s=1.0, r=0.06)
            place(dry, noise_sweep(d, 300, 7000) * env_w * 0.5, t - 0.1, 1.0, -0.45)
            place(dry, noise_sweep(d, 300, 7000) * env_w * 0.5, t - 0.1, 1.0, 0.45)
        elif kind == "land":
            n = int(0.5 * SR)
            thump = np.tanh(2.5 * np.sin(2 * np.pi * 110 * t_axis(n)) * exp_decay(n, 0.08)) * 0.6
            place(sfx, thump, t, 0.9)
            k = int(0.04 * SR)
            place(sfx, np.sin(2 * np.pi * 1320 * t_axis(k)) * exp_decay(k, 0.008) * 0.5, t, 1.0)
        elif kind == "key":
            n = int(0.03 * SR)
            lo, hi_ = (2500, 6000) if e["i"] % 2 == 0 else (4000, 9000)
            x = bp(rng.standard_normal(n), lo, hi_) * exp_decay(n, 0.005) * 0.25
            place(sfx, x, t + rng.uniform(-0.008, 0.008), 1.0, rng.uniform(-0.5, 0.5))
        elif kind == "ping":
            place(sfx, felt(PENTA[e.get("note", 0) % len(PENTA)], 0.9), t, 0.6)
        elif kind == "tick":
            n = int(0.04 * SR)
            f = midi(74 + e["k"] * 0.75)
            x = np.sin(2 * np.pi * f * t_axis(n)) * exp_decay(n, 0.012) * 0.35
            place(sfx, x, t, 1.0, -0.2 + e["k"] * 0.025)
        elif kind == "curve":
            # the held chord opens as the computed gain rises: dark while the family gains $0,
            # brightening as income tax absorbs the extra credit, fully open at the top
            sm = np.array(e["samples"], dtype=float)
            assert sm.ndim == 2 and np.isfinite(sm).all() and np.isfinite(e["gmax"]) and e["gmax"] > 0, "bad curve cue"
            t0, t1 = sm[0, 0], sm[-1, 0]
            n = int((t1 - t0 + 0.25) * SR)
            tt = t0 + t_axis(n)
            # clamped so a gain beyond gmax can never push the cutoff past Nyquist
            g = np.clip(np.interp(tt, sm[:, 0], sm[:, 1]) / e["gmax"], 0.0, 1.0)
            v = sum(pad_voice(m + 12, n) for m in CHORDS[chord_at(t0)]) / 4
            out = np.zeros(n); zi = np.zeros((1, 2)); blk = 128
            for s0 in range(0, n, blk):
                fc = 350 * (2600 / 350) ** g[s0]           # 350 Hz at $0, 2.6 kHz at the full gain
                sos = butter(2, fc / (SR / 2), "low", output="sos")
                out[s0: s0 + blk], zi = sosfilt(sos, v[s0: s0 + blk], zi=zi)
            amp = (0.5 + 0.5 * g) * env_adsr(n, a=0.12, d=0.05, s=1.0, r=0.3)
            place(sfx, out * amp * 0.22, t0, 1.0, 0.2)
        elif kind == "rise":
            d = e["dur"]
            n = int(d * SR)
            v = sum(pad_voice(m + 12, n) for m in CHORDS[chord_at(t)]) / 4
            out = np.zeros(n); zi = np.zeros((1, 2)); blk = 128
            for s0 in range(0, n, blk):
                fc = 300 * (6000 / 300) ** (s0 / n)
                sos = butter(2, fc / (SR / 2), "low", output="sos")
                out[s0: s0 + blk], zi = sosfilt(sos, v[s0: s0 + blk], zi=zi)
            place(sfx, out * np.linspace(0, 1, n) ** 2 * 0.3, t, 1.0)
            place(sfx, noise_sweep(d, 400, 9000) * np.linspace(0, 1, n) ** 2 * 0.2, t, 1.0)
        elif kind == "hit":
            n = int(2.5 * SR)
            boom = np.sin(2 * np.pi * np.cumsum(38 + 60 * exp_decay(n, 0.05)) / SR) * exp_decay(n, 0.5)
            place(sfx, boom * 0.5, t, 1.0)
            for m in CHORDS[2]:
                place(sfx, pad_voice(m + 12, n) * exp_decay(n, 0.7) * 0.5, t, 0.5)
            place(sfx, hp(rng.standard_normal(n), 5000) * exp_decay(n, 0.6) * 0.25, t, 1.0)
        elif kind == "drop":
            n = int(3.0 * SR)
            boom = np.sin(2 * np.pi * np.cumsum(30 + 90 * exp_decay(n, 0.08)) / SR) * exp_decay(n, 0.9)
            place(sfx, np.tanh(2 * boom) * 0.35, t, 1.0)
            place(sfx, hp(rng.standard_normal(n), 4000) * exp_decay(n, 0.9) * 0.22, t, 1.0, -0.3)
            place(sfx, hp(rng.standard_normal(n), 4000) * exp_decay(n, 0.9) * 0.22, t, 1.0, 0.3)
        elif kind == "plink":
            nlit, step = e["n"], e.get("step", 1)
            # G5 -> D6 -> A6: one child's worth, two, three or more; fits both Dm and C
            m = [79, 86, 93][min(3, max(1, step)) - 1]
            g = min(0.6, 0.12 + 0.02 * np.sqrt(nlit))
            place(sfx, felt(m - 12, 0.7), t, 0.8 * g, rng.uniform(-0.7, 0.7))
        elif kind == "stat":
            place(sfx, felt(62 + 5 * e["i"], 0.9), t, 0.5)
        elif kind == "decile":
            FPENT = [65, 67, 69, 72, 74, 77, 79, 81, 84]
            m = FPENT[int(round(e.get("v", (e["n"] - 3) / 9) * (len(FPENT) - 1)))]
            place(sfx, felt(m - 12, 0.8), t, 0.3, -0.6 + 0.12 * (e["n"] - 3))
        elif kind == "swell":
            d = e["dur"] - 0.03
            n = int(d * SR)
            x = noise_sweep(d, 800, 12000) * np.linspace(0, 1, n) ** 3 * env_adsr(n, a=0.001, d=0.001, s=1.0, r=0.04) * 0.35
            place(sfx, x, t, 1.0)
        elif kind == "logo":
            n = int(4.0 * SR)
            boom = np.sin(2 * np.pi * np.cumsum(36 + 50 * exp_decay(n, 0.06)) / SR) * exp_decay(n, 1.1)
            place(sfx, boom * 0.45, t, 1.0)
            for m in [53, 57, 60, 65, 69, 72]:  # F major, open voicing: the resolve
                v = pad_voice(m, n) * exp_decay(n, 1.0)
                place(sfx, lp(v, 3000), t, 0.16, rng.uniform(-0.5, 0.5))

    # sidechain duck on the music bus
    mus *= duck[None, :]
    # the outro: music fades under the logo resolve
    fade = np.ones(N)
    a, b = int(26.0 * SR), int(29.6 * SR)
    fade[a:b] = np.linspace(1, 0.0, b - a) ** 1.5
    fade[b:] = 0
    mus *= fade[None, :]
    drm *= fade[None, :]
    tail = np.ones(N)
    a2, b2 = int(28.0 * SR), int(29.8 * SR)
    tail[a2:b2] = np.linspace(1, 0, b2 - a2) ** 2
    tail[b2:] = 0
    sfx *= tail[None, :]

    mix = verb(mus, 0.28) + verb(drm, 0.08) + verb(sfx, 0.32) + 0.5 * dry
    # gentle master: glue + soft clip, then normalize loudness to ~-14 LUFS (RMS proxy)
    mix = hp(mix, 30)
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    meter = pyln.Meter(SR)
    for _ in range(3):
        L = meter.integrated_loudness(mix.T)
        mix *= 10 ** ((-14.0 - L) / 20)
        # true-peak limiter: 4x oversampled peak detector, 3 ms lookahead, 120 ms release
        pk = np.abs(resample_poly(mix, 4, 1, axis=1)).max(0).reshape(-1, 4).max(1)[: mix.shape[1]]
        ceil = 10 ** (-2.0 / 20)
        g = np.minimum(1.0, ceil / np.maximum(pk, 1e-9))
        la = int(0.003 * SR)
        g = np.minimum.reduce([np.roll(g, -k) for k in range(la)])
        rel = np.exp(-1 / (0.12 * SR))
        from scipy.signal import lfilter
        # release smoothing (attack instant): track min with exponential recovery
        out = np.empty_like(g); cur = 1.0
        for i in range(len(g)):
            cur = g[i] if g[i] < cur else g[i] + (cur - g[i]) * rel
            out[i] = cur
        mix *= out[None, :]
    # 30 ms fade in/out at the edges to avoid clicks
    edge = int(0.03 * SR)
    mix[:, :edge] *= np.linspace(0, 1, edge)
    mix[:, -edge:] *= np.linspace(1, 0, edge)
    return mix


def P(t, a, b):
    return float(np.clip((t - a) / (b - a), 0, 1))


def duck_at(duck, t, depth):
    n = int(0.28 * SR)
    i = int(t * SR)
    shape = 1 - depth * np.exp(-t_axis(n) / 0.07)
    j = min(len(duck), i + n)
    duck[i:j] = np.minimum(duck[i:j], shape[: j - i])


def write_wav(path, x):
    x16 = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x16.T.tobytes())


if __name__ == "__main__":
    ev_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    events = json.loads(ev_path.read_text())
    mix = build(events)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out, mix)
    print(f"wrote {out}  {len(events)} events  peak {np.max(np.abs(mix)):.3f}  rms {20*np.log10(np.sqrt(np.mean(mix**2))):.1f} dBFS")
