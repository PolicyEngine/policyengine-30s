"""The score: equal-power panning, deterministic synthesis, platform mastering targets."""

import json

import numpy as np
import pytest
from hypothesis import given
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
    return events, sd.build(events)


def test_mastering_hits_platform_targets(score):
    import pyloudnorm as pyln
    from scipy.signal import resample_poly

    _, mix = score
    lufs = pyln.Meter(sd.SR).integrated_loudness(mix.T)
    true_peak = 20 * np.log10(np.abs(resample_poly(mix, 4, 1, axis=1)).max())
    assert abs(lufs + 14) < 0.5 and true_peak <= -1.0
    # clean edges: the 30 ms fades start and end at exactly zero, and no sample inside them
    # exceeds the limiter ceiling (-2 dBTP) times the fade ramp
    edge = int(0.03 * sd.SR)
    ramp = np.linspace(0, 1, edge) * 10 ** (-2.0 / 20) + 1e-9
    assert (mix[:, 0] == 0).all() and (mix[:, -1] == 0).all()
    assert (np.abs(mix[:, :edge]) <= ramp).all() and (np.abs(mix[:, -edge:]) <= ramp[::-1]).all()


def test_synthesis_is_deterministic(score):
    """One fresh process renders one score: the module-level rng is seeded at import, so the
    reload stands in for a new process (calling build() twice in one process would drift)."""
    import importlib

    events, mix = score
    again = importlib.reload(sd).build(events)
    assert np.array_equal(mix, again)
