"""
feed.py

Pure rules for turning a live fixturedownload feed into a safe season snapshot.

update_season.py does all the I/O. These functions only take and return row
dicts (the shape loader.rows_from_feed / rows_from_csv produce), so every rule
about malformed data, complete weeks and suspicious changes is unit-testable
without a network:

  validate_rows         -> refusals no flag can approve (malformed data)
  regular_season        -> drop postseason rows (weeks > 18)
  complete_through_week -> keep only fully-scored weeks, report what blocks the next
  diff_snapshots        -> new scores vs. suspicious changes against the saved CSV
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

Row = Dict[str, Any]
LAST_REGULAR_WEEK = 18


def _is_int(value: Any) -> bool:
    """True for real ints only (JSON true/false would otherwise pass as 1/0)."""
    return isinstance(value, int) and not isinstance(value, bool)


def label(r: Row) -> str:
    """Human label for a game, e.g. 'Week 3 Miami Dolphins @ Buffalo Bills'."""
    return f"Week {r['week']} {r['away_team']} @ {r['home_team']}"


def score_text(r: Row) -> str:
    """Score as away-home, matching label()'s away @ home order."""
    if r["home_score"] is None:
        return "(no score)"
    return f"{r['away_score']}-{r['home_score']}"


def validate_rows(rows: List[Row], teams: Iterable[str]) -> List[str]:
    """Return refusal messages for malformed data; an empty list means the feed is usable."""
    if not rows:
        return ["Feed is empty"]
    teams = set(teams)
    problems: List[str] = []
    seen: set = set()
    for r in rows:
        m, week = r["match_number"], r["week"]

        # Week must be a real round; postseason rows are skipped, not checked.
        if not _is_int(week) or week < 1:
            problems.append(f"Match {m}: invalid week {week!r}")
            continue
        if week > LAST_REGULAR_WEEK:
            continue

        if m in seen:
            problems.append(f"Duplicate match number {m}")
        seen.add(m)

        for side in ("home_team", "away_team"):
            if r[side] not in teams:
                problems.append(f"Match {m}: unknown team {r[side]!r}")

        # Scores: both blank (unplayed) or both non-negative ints.
        hs, as_ = r["home_score"], r["away_score"]
        if (hs is None) != (as_ is None):
            problems.append(f"Match {m}: only one side has a score ({label(r)})")
        elif hs is not None and not (_is_int(hs) and _is_int(as_) and hs >= 0 and as_ >= 0):
            problems.append(f"Match {m}: invalid score {as_!r}-{hs!r} ({label(r)})")
    return problems


def regular_season(rows: List[Row]) -> List[Row]:
    """Drop postseason rows; call after validate_rows so every week is an int."""
    return [r for r in rows if r["week"] <= LAST_REGULAR_WEEK]


@dataclass
class Cut:
    """A snapshot cut back to its last complete week."""

    week: int                 # last week where every scheduled game is scored (0 = none)
    rows: List[Row]           # all games; scores after `week` blanked
    blocked: List[Row]        # unscored games in week+1 when that week has started


def complete_through_week(rows: List[Row]) -> Cut:
    """Keep scores only for the unbroken run of fully-scored weeks starting at week 1."""
    by_week: Dict[int, List[Row]] = {}
    for r in rows:
        by_week.setdefault(r["week"], []).append(r)

    # Walk forward while the next week exists and every game in it has a score.
    week = 0
    while week + 1 in by_week and all(g["home_score"] is not None for g in by_week[week + 1]):
        week += 1

    # A started-but-unfinished next week is "blocked"; a week nobody has played yet is not.
    nxt = by_week.get(week + 1, [])
    started = any(g["home_score"] is not None for g in nxt)
    blocked = [g for g in nxt if g["home_score"] is None] if started else []

    cut_rows = [r if r["week"] <= week else {**r, "home_score": None, "away_score": None}
                for r in rows]
    return Cut(week=week, rows=cut_rows, blocked=blocked)
