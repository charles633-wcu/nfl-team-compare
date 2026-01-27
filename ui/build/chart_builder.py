from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from jinja2 import Environment


def build_elo_chart_pages(
    env: Environment,
    dist_dir: Path,
    elo_all: Dict[str, Any],
    teams: Iterable[str],
    slugify,
    division_rivals: Optional[Dict[str, List[str]]] = None,
) -> None:
    elo_by_week: Dict[str, Dict[str, Any]] = elo_all.get("elo", {}) or {}
    if not elo_by_week:
        raise RuntimeError("elo_all['elo'] missing or empty; cannot build chart pages.")

    weeks: List[int] = []
    for k in elo_by_week.keys():
        try:
            weeks.append(int(k))
        except ValueError:
            continue
    weeks.sort()

    season = elo_all.get("season")
    baseline = elo_all.get("baseline", 1500)

    out_dir = dist_dir / "elo"
    out_dir.mkdir(parents=True, exist_ok=True)

    tpl = env.get_template("team_elo_chart.html")
    rivals_map = division_rivals or {}

    for team in teams:
        rivals = rivals_map.get(team, [])
        plot_teams = [team] + rivals[:3]

        series: List[Dict[str, Any]] = []
        for t in plot_teams:
            t_elos: List[float | None] = []
            for w in weeks:
                week_map = elo_by_week.get(str(w), {})
                val = week_map.get(t)
                if val is None:
                    t_elos.append(None)
                    continue
                try:
                    t_elos.append(float(val))
                except Exception:
                    t_elos.append(float(str(val)))

            series.append({"team": t, "elos": t_elos})

        html = tpl.render(
            team=team,
            season=season,
            weeks=weeks,
            baseline=baseline,
            series=series,
        )

        (out_dir / f"{slugify(team)}.html").write_text(html, encoding="utf-8")
