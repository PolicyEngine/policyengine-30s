"""The family-curve text for the UK video, derived from computed facts and checked point by point.

Two callers use this module:
  * tools/uk/earnings_sweep.py derives the facts from a £1 grid (every pound from
    £0 to £80,000), words the on-screen statements from them, and asserts every
    statement at every one of those 80,001 points;
  * tools/uk/build_uk_video.py re-derives the same statements from the stored
    £1 facts and asserts them again at every point of the £250 grid it plots.

Nothing on screen is typed here: each threshold, amount and rate comes from the
computed curve or from the parameter value the model read.

Plain Python on lists (no numpy), so the builder needs no scientific stack.
"""

from __future__ import annotations

import math

TOL = 0.02  # policyengine-uk computes in float32; net incomes near £40,000 carry ~£0.004 of rounding each


def _run(E, ok, i):
    """Maximal contiguous index range [a, b] around i where ok(j) holds."""
    assert ok(i), f"seed point {E[i]} does not satisfy the run condition"
    a = i
    while a > 0 and ok(a - 1):
        a -= 1
    b = i
    while b < len(E) - 1 and ok(b + 1):
        b += 1
    return a, b


def facts(E, G, UC0, UC1, CUT, pin_earnings):
    """Where the curve is flat, and where Universal Credit ends, on a given earnings grid.

    E: earnings; G: change in household net income; UC0 / UC1: Universal Credit in
    the baseline / reform run; CUT: fall in income tax (baseline minus reform).
    """
    n = len(E)
    on0 = [u > 0.005 for u in UC0]
    on1 = [u > 0.005 for u in UC1]
    last_uc0 = max(i for i in range(n) if on0[i])
    last_uc1 = max(i for i in range(n) if on1[i])
    first_pos = min(i for i in range(n) if G[i] > TOL)
    # plateau 1: the flat stretch through the pinned earnings, family on UC in both runs
    ip = E.index(pin_earnings)
    v1 = G[ip]
    a1, b1 = _run(E, lambda j: abs(G[j] - v1) < TOL and on0[j] and on1[j], ip)
    # plateau 2: the flat stretch that starts at the first point after today's UC ends
    i2 = last_uc0 + 1
    v2 = G[i2]
    a2, b2 = _run(E, lambda j: abs(G[j] - v2) < TOL and not on0[j] and not on1[j], i2)
    # plateau 3: the flat stretch that reaches the end of the grid
    v3 = G[n - 1]
    a3, b3 = _run(E, lambda j: abs(G[j] - v3) < TOL, n - 1)
    r2 = lambda x: round(float(x), 2)
    return {
        "first_positive_gain_at": E[first_pos],
        "baseline_uc_last_positive_at": E[last_uc0],
        "reform_uc_last_positive_at": E[last_uc1],
        "plateau_on_uc": {"from": E[a1], "to": E[b1], "gain": r2(v1), "tax_cut": r2(CUT[ip])},
        "plateau_off_uc": {"from": E[a2], "to": E[b2], "gain": r2(v2), "tax_cut": r2(CUT[i2])},
        "plateau_top": {"from": E[a3], "to": E[b3], "gain": r2(v3), "tax_cut": r2(CUT[n - 1])},
        "pin": [pin_earnings, r2(v1)],
    }


def up100(x):
    return int(math.ceil(x / 100) * 100)


def down10(x):
    return int(math.floor(x / 10) * 10)


def pounds(x):
    return f"£{x:,.0f}"


def statements(f, reduction_rate):
    """On-screen lines and note, from the £1 facts. Lower bounds round up to £100, upper bounds down to £10,
    so every stated range sits inside the computed flat stretch."""
    p1, p2 = f["plateau_on_uc"], f["plateau_off_uc"]
    c1 = {"id": "plateau_on_uc", "lo": up100(p1["from"]), "hi": down10(p1["to"]), "gain": p1["gain"], "uc": "on_in_both_runs"}
    c2 = {"id": "plateau_off_uc", "lo": up100(p2["from"]), "hi": down10(p2["to"]), "gain": p2["gain"], "uc": "off_in_both_runs"}
    for c in (c1, c2):
        assert c["lo"] < c["hi"], c
        c["text"] = f"+{pounds(c['gain'])} from {pounds(c['lo'])} to {pounds(c['hi'])}."
    pence = reduction_rate * 100
    assert abs(pence - round(pence)) < 1e-9, pence
    note = (
        "Universal Credit counts pay after tax, so it takes back "
        f"{round(pence)}p of each £1 of the tax cut."
    )
    return {"lines": [c1["text"], c2["text"]], "note": note, "claims": [c1, c2], "reduction_rate": reduction_rate}


def check(E, G, UC0, UC1, CUT, DUC, DNI, DUCE, stm, pin):
    """Assert every on-screen statement at every point of the grid. Returns points checked per statement."""
    rate = stm["reduction_rate"]
    n = len(E)
    out = {}
    for c in stm["claims"]:
        idx = [i for i in range(n) if c["lo"] <= E[i] <= c["hi"]]
        assert idx, c
        for i in idx:
            assert abs(G[i] - c["gain"]) < TOL, (c["text"], E[i], G[i])
            # the rounded figure on screen is the same at every point of the range
            assert pounds(G[i]) == pounds(c["gain"]), (c["text"], E[i], G[i])
            on0, on1 = UC0[i] > 0.005, UC1[i] > 0.005
            if c["uc"] == "on_in_both_runs":
                assert on0 and on1, (c["text"], E[i], UC0[i], UC1[i])
            else:
                assert not on0 and not on1, (c["text"], E[i], UC0[i], UC1[i])
        out[c["text"]] = len(idx)
    # the note: wherever the family is on UC in both runs and the tax cut is positive, UC falls by
    # rate x the tax cut, UC earned income rises by the whole tax cut, and National Insurance is unchanged
    idx = [i for i in range(n) if UC0[i] > 0.005 and UC1[i] > 0.005 and CUT[i] > 0.005]
    for i in idx:
        assert abs(DUC[i] + rate * CUT[i]) < TOL, ("note", E[i], DUC[i], CUT[i])
        assert abs(DUCE[i] - CUT[i]) < TOL, ("note: UC counts pay after tax", E[i], DUCE[i], CUT[i])
    assert all(abs(x) < TOL for x in DNI), "National Insurance changed; the tax cut is not all income tax"
    out[stm["note"]] = len(idx)
    # the pin sits inside the first stated range, so its rounded label matches line 1
    c1 = stm["claims"][0]
    assert c1["lo"] <= pin[0] <= c1["hi"] and pounds(pin[1]) == pounds(c1["gain"]), (pin, c1)
    # the gain never goes below zero and never exceeds the tax cut
    for i in range(n):
        assert -TOL < G[i] <= CUT[i] + TOL, ("0 <= gain <= tax cut", E[i], G[i], CUT[i])
    out["0 <= gain <= tax cut (not on screen)"] = n
    return out
