"""Verification preview: join districts.json to district_layout.json and draw
the hex cartogram (x = lon, y = lat, as the app's geoEquirectangular does).

Writes out/preview_avg_change.png and out/preview_share_gaining.png. These are
QA images for checking the join and the layout, not video frames.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1]


def draw(field: str, label: str, fmt, out: Path) -> None:
    res = {d["geoid"]: d for d in json.loads((DATA / "districts.json").read_text())["districts"]}
    lay = json.loads((DATA / "district_layout.json").read_text())["districts"]
    patches, vals = [], []
    for d in lay:
        v = res[d["geoid"]][field]
        for poly in d["polygons"]:
            patches.append(Polygon(poly[0], closed=True))
            vals.append(v)
    fig, ax = plt.subplots(figsize=(12, 7.5), dpi=120)
    pc = PatchCollection(patches, cmap="Blues", edgecolor="white", linewidth=0.4)
    pc.set_array(vals)
    ax.add_collection(pc)
    for d in lay:
        if d["district_number"] in (0, 1):
            ax.text(d["centroid"]["x"], d["centroid"]["y"], d["state_code"], ha="center", va="center", fontsize=5, color="#333")
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.axis("off")
    cb = fig.colorbar(pc, ax=ax, shrink=0.6)
    cb.set_label(label)
    cb.ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: fmt(x)))
    ax.set_title(f"QA preview: {label} by congressional district (PolicyEngine, 2026)", fontsize=11)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    (HERE / "out").mkdir(exist_ok=True)
    draw("avg_change", "Average change in household net income ($)", lambda x: f"${x:,.0f}", HERE / "out" / "preview_avg_change.png")
    draw("share_gaining", "Share of households gaining", lambda x: f"{x:.0%}", HERE / "out" / "preview_share_gaining.png")
    print("ok")


if __name__ == "__main__":
    main()
