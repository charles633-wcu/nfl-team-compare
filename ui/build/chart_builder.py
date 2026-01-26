# ui/build/chart_builder.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List
from jinja2 import Environment


def build_elo_chart_pages(
    env: Environment,
    dist_dir: Path,
    elo_all: Dict[str, Any],
    teams: Iterable[str],
    slugify,
) -> None:
    """
    Writes: dist/elo/<team-slug>.html

    Expects:
      - env has template "team_elo_chart.html"
      - elo_all comes from /elo/all and contains:
          elo_all["elo"] = { "0": { "Team A": 1500, ... }, "1": {...}, ... }
      - dist_dir is ui/dist
      - teams is an iterable of team names (strings)
      - slugify is your existing slugify() function
    """
    elo_by_week: Dict[str, Dict[str, Any]] = elo_all.get("elo", {}) or {}
    if not elo_by_week:
        raise RuntimeError("elo_all['elo'] missing or empty; cannot build chart pages.")

    # Determine available weeks from keys (strings)
    weeks: List[int] = []
    for k in elo_by_week.keys():
        try:
            weeks.append(int(k))
        except ValueError:
            continue
    weeks.sort()

    season = elo_all.get("season")

    out_dir = dist_dir / "elo"
    out_dir.mkdir(parents=True, exist_ok=True)

    tpl = env.get_template("team_elo_chart.html")

    for team in teams:
        team_weeks: List[int] = []
        team_elos: List[float] = []

        for w in weeks:
            week_map = elo_by_week.get(str(w), {})
            if team not in week_map:
                continue

            val = week_map[team]
            try:
                team_elos.append(float(val))
            except Exception:
                team_elos.append(float(str(val)))

            team_weeks.append(w)

        # If a team is missing entirely, still generate a page (with empty series)
        html = tpl.render(
            team=team,
            season=season,
            weeks=team_weeks,
            elos=team_elos,
        )

        (out_dir / f"{slugify(team)}.html").write_text(html, encoding="utf-8")
