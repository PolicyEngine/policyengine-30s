"""What national.json may say about small groups of survey records.

national.json is committed and public, while the enhanced FRS behind it is End User Licence data
that stays in data/uk/private/. A sum over a few records comes close to one record's value, so a
sum is published only when enough records actually contribute to it (a nonzero change), not merely
when the group it describes is large enough. Minimums and maximums are never published at all
(tests/uk/test_uk_video.py scans for them).
"""

from __future__ import annotations

MIN_CONTRIBUTORS = 10


def publishable_sums(sums: dict[str, float], contributors: dict[str, int],
                     min_contributors: int = MIN_CONTRIBUTORS) -> dict[str, float]:
    """The sums backed by at least min_contributors contributing records, unchanged; the rest dropped."""
    return {k: v for k, v in sums.items() if contributors.get(k, 0) >= min_contributors}
