"""The score: equal-power panning, deterministic synthesis, platform mastering targets,
and swooshes that sit under the music instead of over it."""

import json

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import soundtrack as sd
from conftest import ROOT


@given(st.floats(min_value=-1, max_value=1))
def test_pan_law_keeps_power(pan):
    buf = np.zeros((2, 100))
    sd.place(buf, np.ones(10), 0.0, 1.0, pan)
    assert abs(buf[0, 0] ** 2 + buf[1, 0] ** 2 - 1) < 1e-12


def test_pan_direction():
    """-1 is hard left, +1 hard right, 0 centred."""
    for pan, (left, right) in ((-1, (1, 0)), (1, (0, 1)), (0, (np.sqrt(0.5), np.sqrt(0.5)))):
        buf = np.zeros((2, 4))
        sd.place(buf, np.ones(1), 0.0, 1.0, pan)
        assert abs(buf[0, 0] - left) < 1e-12 and abs(buf[1, 0] - right) < 1e-12


@given(st.floats(min_value=-0.5, max_value=31.0), st.floats(min_value=0.1, max_value=2))
def test_place_writes_exactly_where_and_when_asked(t, gain):
    buf = np.zeros((2, sd.N))
    n = int(0.2 * sd.SR)
    sd.place(buf, np.ones(n), t, gain, 0.0)
    start = int(round(t * sd.SR))
    nz = np.flatnonzero(buf[0] + buf[1])
    if start >= sd.N or start + n <= 0:
        assert nz.size == 0
    else:
        assert nz[0] == max(0, start) and nz[-1] == min(sd.N, start + n) - 1


@pytest.fixture(scope="module")
def score():
    events = json.loads((ROOT / "audio" / "events.json").read_text())
    report, stems = [], {}
    return events, sd.build(events, report, stems), report, stems


def test_mastering_hits_platform_targets(score):
    import pyloudnorm as pyln
    from scipy.signal import resample_poly

    _, mix, _, _ = score
    lufs = pyln.Meter(sd.SR).integrated_loudness(mix.T)
    true_peak = 20 * np.log10(np.abs(resample_poly(mix, 4, 1, axis=1)).max())
    # the limiter's ceiling is -2 dBTP; 1e-3 dB allows for the 4x resampling estimate
    assert abs(lufs + 14) < 0.5 and true_peak <= -2.0 + 1e-3
    # clean edges: the 30 ms fades start and end at exactly zero, and no sample inside them
    # exceeds the limiter ceiling (-2 dBTP) times the fade ramp
    edge = int(0.03 * sd.SR)
    ramp = np.linspace(0, 1, edge) * 10 ** (-2.0 / 20) + 1e-9
    assert (mix[:, 0] == 0).all() and (mix[:, -1] == 0).all()
    assert (np.abs(mix[:, :edge]) <= ramp).all() and (np.abs(mix[:, -edge:]) <= ramp[::-1]).all()


def test_heavy_cues_land_on_downbeats(score):
    """At 120 BPM in 4/4 a bar is 2 s, so the hit, the drop and the logo sit on even seconds
    (a hit on beat 4 made the bar sound like 3/4); the riser and swell end where they resolve."""
    events, _, _, _ = score
    at = {e["type"]: e for e in events}
    for kind in ("hit", "drop", "logo"):
        assert abs(at[kind]["t"] / 2 - round(at[kind]["t"] / 2)) < 1e-9, (kind, at[kind]["t"])
    assert 0 < at["hit"]["t"] - (at["rise"]["t"] + at["rise"]["dur"]) <= 0.1
    assert abs(at["swell"]["t"] + at["swell"]["dur"] - at["logo"]["t"]) < 1e-9


def test_curve_cue_survives_out_of_range_gains():
    """A curve gain outside [0, gmax] is clamped instead of pushing the filter past Nyquist."""
    cues = [{"t": t, "type": "curve", "gmax": 1.0, "samples": [[t, 0.0], [t + 0.5, g], [t + 1, g]]}
            for t, g in ((1.0, -5.0), (5.0, 2.2), (9.0, 1e6))]
    assert np.isfinite(sd.build(cues)).all()


def test_synthesis_is_deterministic(score):
    """One fresh process renders one score: the module-level rng is seeded at import, so the
    reload stands in for a new process (calling build() twice in one process would drift)."""
    import importlib

    events, mix, _, _ = score
    again = importlib.reload(sd).build(events)
    assert np.array_equal(mix, again)


# ------------------------------------------------------------------ swooshes
SWEEPS = ("whoosh", "rise", "swell")


def _filter_all(meter, x):
    for f in meter._filters.values():
        x = f.apply_filter(x)
    return x


def _loudness(x, i, w):
    """pyloudnorm's own K-weighting over the whole signal, then one window: an independent
    measurement of what the score actually contains (pinned pyloudnorm 0.2.0)."""
    import pyloudnorm as pyln

    meter = pyln.Meter(sd.SR)
    k = np.stack([_filter_all(meter, c[max(0, i - sd.SR): i + w]) for c in x])
    k = k[:, min(i, sd.SR):]
    return -0.691 + 10 * np.log10(np.mean(k ** 2, axis=1).sum() + 1e-20)


def test_every_sweep_sits_under_the_music_around_it(score):
    """Measured on the returned audio (not on the report's own numbers): at its loudest
    window, each levelled sweep is SWEEP_UNDER LU below the rest of the score, and the window
    never reaches the cue the sweep leads into."""
    events, _, report, stems = score
    cues = [e for e in events if e["type"] in SWEEPS]
    assert [r["t"] for r in report] == [e["t"] for e in cues]
    assert sd.SWEEP_UNDER >= 4.0
    for r, e in zip(report, cues):
        i, w = r["window_start"], r["window_len"]
        under = _loudness(stems["bed_pre"], i, w) - _loudness(stems["sweeps_pre"], i, w)
        assert abs(under - sd.SWEEP_UNDER) < 0.05, (r, under)
        assert e["t"] - 0.1 - 1e-9 <= i / sd.SR and (i + w) / sd.SR <= e["t"] + e.get("dur", 0.8) + 1e-9, (r, e)


def test_the_window_is_the_sweeps_loudest(score):
    """Scanning every per-sample window inside each sweep's own span (from the event timing:
    a whoosh starts 0.1 s early, the swell stops 30 ms short of the logo), none is louder than
    the one the sweep was levelled at."""
    events, _, report, stems = score
    cues = [e for e in events if e["type"] in SWEEPS]
    for r, e in zip(report, cues):
        i, w = r["window_start"], r["window_len"]
        t0 = e["t"] - 0.1 if e["type"] == "whoosh" else e["t"]
        t1 = e["t"] + e.get("dur", 0.8) - (0.03 if e["type"] == "swell" else 0.0)
        lo, hi = int(round(t0 * sd.SR)), int(round(t1 * sd.SR)) - w + 1
        at, ls = sd.momentary(stems["sweeps_pre"], lo, hi, w)
        assert lo <= i < hi and ls[at == i][0] >= ls.max() - 1e-3, (r, float(ls.max() - ls[at == i][0]))


def test_mastered_stems_are_the_score(score):
    """Conservation: the mastered bed plus the mastered sweeps is the score, sample for sample."""
    _, mix, _, stems = score
    assert np.abs(stems["bed"] + stems["sweeps"] - mix).max() < 1e-9


def test_sweeps_sit_under_the_music_in_the_mastered_score(score):
    """The same margin through the master's shared gain envelope, bounded on both sides so a
    muted or halved sweep fails as surely as a loud one. The limiter trims the swell's margin
    to about 4.6 LU: a kick and clap at 25.5 s share its window."""
    _, _, report, stems = score
    for r in report:
        i, w = r["window_start"], r["window_len"]
        under = _loudness(stems["bed"], i, w) - _loudness(stems["sweeps"], i, w)
        assert 4.0 <= under <= sd.SWEEP_UNDER + 0.3, (r["t"], under)


@settings(max_examples=15, deadline=None)
@given(st.integers(0, 2**32 - 1), st.floats(-40, 0), st.floats(200, 8000))
def test_k_weighting_matches_pyloudnorm(seed, level_db, centre):
    """Differential: our BS.1770 filter bank and loudness sum agree with pyloudnorm on
    stationary band-limited noise, to within the two filter designs' 0.04 dB offset."""
    import pyloudnorm as pyln

    g = np.random.default_rng(seed)
    x = sd.bp(g.standard_normal((2, 3 * sd.SR)), centre / 2, min(20000, centre * 2)) * 10 ** (level_db / 20)
    at, ours = sd.momentary(x, sd.SR, sd.SR + 1)          # one window, filters settled
    assert at[0] == sd.SR
    meter = pyln.Meter(sd.SR)
    k = np.stack([_filter_all(meter, c) for c in x])[:, sd.SR: sd.SR + sd.MOMENT]
    theirs = -0.691 + 10 * np.log10(np.mean(k ** 2, axis=1).sum())
    assert abs(ours[0] - theirs) < 0.1


def _synthetic(bed_db, t, dur, n=3 * sd.SR, seed=7):
    g = np.random.default_rng(seed)
    bed = sd.bp(g.standard_normal((2, n)), 100, 6000) * 10 ** (bed_db / 20)
    buf = np.zeros((2, n))
    sd.place(buf, sd.bp(g.standard_normal(int(dur * sd.SR)), 300, 5000), t, 1.0)
    return bed, buf


@settings(max_examples=12, deadline=None)
@given(st.floats(-30, 0), st.floats(-40, 10), st.floats(0.5, 1.2), st.floats(0.05, 1.5), st.sampled_from([0.0, 0.32]))
def test_levelling_ignores_the_sweep_gain_and_follows_the_bed(bed_db, sweep_db, t, dur, wet):
    """Invariants of level_sweeps on synthetic input, measured on its output: the result sits
    exactly SWEEP_UNDER below the bed whatever the sweep's own gain (scale invariance in the
    sweep), and scales one-for-one with the bed (homogeneity in the bed). Sweeps shorter than
    400 ms are measured over their own length."""
    bed, buf = _synthetic(bed_db, t, dur)
    buf *= 10 ** (sweep_db / 20)
    rep1 = []
    a = sd.level_sweeps(bed, [(buf, wet, t)], rep1)
    b = sd.level_sweeps(bed, [(buf * 10.0, wet, t)])
    c = sd.level_sweeps(bed * 2.0, [(buf, wet, t)])
    i, w = rep1[0]["window_start"], rep1[0]["window_len"]
    assert w == min(sd.MOMENT, int(dur * sd.SR))
    _, lb = sd.momentary(bed, i, i + 1, w)
    _, la = sd.momentary(a, i, i + 1, w)
    assert abs(lb[0] - la[0] - sd.SWEEP_UNDER) < 1e-6
    assert np.allclose(a, b, atol=1e-12 + 1e-9 * np.abs(a).max())
    assert np.allclose(c, 2.0 * a, atol=1e-12 + 1e-9 * np.abs(a).max())


@settings(max_examples=12, deadline=None)
@given(st.floats(0.05, 1.5), st.floats(0.3, 1.0), st.floats(0, 40))
def test_what_plays_after_a_sweep_cannot_set_its_level(dur, t, boost_db):
    """Making the bed louder after the sweep ends (the hit a riser leads into) leaves the
    sweep's level unchanged, however short the sweep."""
    bed, buf = _synthetic(-20, t, dur)
    end = int(round(t * sd.SR)) + int(dur * sd.SR)
    loud = bed.copy()
    loud[:, end:] *= 10 ** (boost_db / 20)
    a = sd.level_sweeps(bed, [(buf, 0.0, t)])
    b = sd.level_sweeps(loud, [(buf, 0.0, t)])
    assert np.allclose(a, b, atol=1e-12 + 1e-9 * np.abs(a).max())


@pytest.mark.parametrize("t", [29.2, 29.7, 29.9, 29.999, 30.5, -2.0])
def test_sweeps_at_the_edges_of_the_score_render(t):
    """A sweep cut off by the end of the score is levelled over what remains; one wholly
    outside it is dropped. Neither may crash the render."""
    bed = sd.bp(np.random.default_rng(3).standard_normal((2, sd.N)), 100, 6000) * 0.1
    buf = np.zeros((2, sd.N))
    sd.place(buf, sd.bp(np.random.default_rng(4).standard_normal(int(0.9 * sd.SR)), 300, 5000), t, 1.0)
    rep = []
    out = sd.level_sweeps(bed, [(buf, 0.0, t)], rep)
    assert np.isfinite(out).all()
    if not buf.any():
        assert rep == [] and not out.any()
    else:
        assert len(rep) == 1 and out.any()
