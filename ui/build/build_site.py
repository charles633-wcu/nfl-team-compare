from __future__ import annotations

import json
import os
import re
import shutil
from chart_builder import build_elo_chart_pages
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from team_sites import fetch_team_timeline, enrich_weeks, compute_rank_and_elo
import time
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape


DEFAULT_ANALYTICS_API = "http://127.0.0.1:8001"


@dataclass(frozen=True)
class SiteConfig:
    analytics_api_base: str
    timeout_s: int = 15


def slugify(name: str) -> str:
    """
    "Philadelphia Eagles" -> "philadelphia-eagles"
    """
    s = name.strip().lower()
    s = s.replace("&", "and")
    s = re.sub(r"[’']", "", s)            # drop apostrophes
    s = re.sub(r"[^a-z0-9]+", "-", s)     # non-alnum -> hyphen
    s = re.sub(r"-{2,}", "-", s)          # collapse hyphens
    s = s.strip("-")
    return s


# HTTP helpers
def http_get_json(url: str, timeout_s: int) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


# Data shaping
def parse_weeks_from_elo_all(payload: Dict[str, Any]) -> List[int]:
    """
    payload["elo"] is a dict keyed by week as string: { "0": {...}, "1": {...} }
    """
    elo_by_week = payload.get("elo", {})
    weeks = []
    for k in elo_by_week.keys():
        try:
            weeks.append(int(k))
        except ValueError:
            continue
    weeks.sort()
    return weeks


def leaderboard_rows_for_week(
    elo_all: Dict[str, Any],
    week: int,
) -> List[Tuple[str, int, int | None]]:
    """
    Returns rows: (team, elo, delta_vs_prev_week_or_None)
    Sorted by elo desc, then team name asc for stability.
    """
    elo_by_week: Dict[str, Dict[str, Any]] = elo_all["elo"]
    cur_map: Dict[str, Any] = elo_by_week[str(week)]

    prev_map: Dict[str, Any] | None = None
    if str(week - 1) in elo_by_week:
        prev_map = elo_by_week[str(week - 1)]

    rows: List[Tuple[str, int, int | None]] = []
    for team, elo_val in cur_map.items():
        try:
            elo_int = int(elo_val)
        except Exception:
            elo_int = int(float(elo_val))

        delta: int | None = None
        if prev_map is not None and team in prev_map:
            try:
                delta = elo_int - int(prev_map[team])
            except Exception:
                delta = elo_int - int(float(prev_map[team]))

        rows.append((team, elo_int, delta))

    rows.sort(key=lambda t: (-t[1], t[0]))
    return rows


def build_site(cfg: SiteConfig) -> None:
    here = Path(__file__).resolve()
    ui_dir = here.parents[1]  # .../ui
    templates_dir = ui_dir / "templates"
    static_dir = ui_dir / "static"
    dist_dir = ui_dir / "dist"

    leaderboard_out_dir = dist_dir / "leaderboard"
    team_out_dir = dist_dir / "team"
    elo_out_dir = dist_dir / "elo"

    dist_dir.mkdir(parents=True, exist_ok=True)
    leaderboard_out_dir.mkdir(parents=True, exist_ok=True)
    team_out_dir.mkdir(parents=True, exist_ok=True)
    elo_out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["slug"] = slugify

    # Fetch analytics once
    elo_all_url = f"{cfg.analytics_api_base.rstrip('/')}/elo/all"
    elo_all = http_get_json(elo_all_url, timeout_s=cfg.timeout_s)

    season = elo_all.get("season")
    baseline = elo_all.get("baseline")
    k_factor = elo_all.get("k_factor")

    weeks = parse_weeks_from_elo_all(elo_all)
    if not weeks:
        raise RuntimeError(f"No weeks found in {elo_all_url}. Got keys: {list(elo_all.keys())}")

    latest_week = max(weeks)

    # Render index.html as "latest week"
    index_tpl = env.get_template("index.html")
    latest_rows = leaderboard_rows_for_week(elo_all, latest_week)
    index_html = index_tpl.render(
        week=latest_week,
        season=season,
        baseline=baseline,
        k_factor=k_factor,
        available_weeks=weeks,
        rows=latest_rows,
    )
    (dist_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Render about + contact pages at dist root
    about_tpl = env.get_template("about.html")
    about_html = about_tpl.render(
        season=season,
        baseline=baseline,
        k_factor=k_factor,
        current_week=latest_week,
    )
    (dist_dir / "about.html").write_text(about_html, encoding="utf-8")

    contact_tpl = env.get_template("contact.html")
    contact_html = contact_tpl.render(
        season=season,
        baseline=baseline,
        k_factor=k_factor,
        current_week=latest_week,
    )
    (dist_dir / "contact.html").write_text(contact_html, encoding="utf-8")

    # Build TEAM pages (dist/team/<slug>.html)
    team_tpl = env.get_template("team.html")

    failures = []
    for team, _elo, _delta in latest_rows:
        try:
            payload = fetch_team_timeline(cfg.analytics_api_base, team, timeout_s=cfg.timeout_s)
            weeks_data = enrich_weeks(payload)
            rank, current_elo = compute_rank_and_elo(latest_rows, team)

            html = team_tpl.render(
                team=team,
                season=payload.get("season"),
                current_week=latest_week,
                rank=rank,
                current_elo=current_elo,
                weeks=weeks_data,
                baseline=baseline,
                k_factor=k_factor,
            )
            (team_out_dir / f"{slugify(team)}.html").write_text(html, encoding="utf-8")

        except requests.exceptions.RequestException as e:
            failures.append((team, repr(e)))
            print(f"Team page skipped: {team} ({e})")

        time.sleep(0.15)

    if failures:
        print("\n=== Team page failures ===")
        for team, err in failures:
            print(f"- {team}: {err}")

    # Loads division rivals mapping (repo-root /elo/division_rivals.json)
    repo_root = here.parents[2]  # .../ui/build/build_site.py -> parents[2] is repo root
    rivals_path = repo_root / "elo" / "division_rivals.json"

    division_rivals: Dict[str, List[str]] = {}
    if rivals_path.exists():
        division_rivals = json.loads(rivals_path.read_text(encoding="utf-8"))
    else:
        print(f"division_rivals.json not found at: {rivals_path} (charts will be single-line)")

    # Build Elo CHART pages (dist/elo/<slug>.html)
    teams = [team for team, _elo, _delta in latest_rows]
    build_elo_chart_pages(
        env=env,
        dist_dir=dist_dir,
        elo_all=elo_all,
        teams=teams,
        slugify=slugify,
        division_rivals=division_rivals,
    )

    # Render each week page (dist/leaderboard/week-<w>.html)
    week_tpl = env.get_template("leaderboard_week.html")
    for w in weeks:
        rows = leaderboard_rows_for_week(elo_all, w)
        html = week_tpl.render(
            week=w,
            season=season,
            baseline=baseline,
            k_factor=k_factor,
            available_weeks=weeks,
            rows=rows,
        )
        (leaderboard_out_dir / f"week-{w}.html").write_text(html, encoding="utf-8")

    # Copy static assets into dist/static
    out_static_dir = dist_dir / "static"
    if out_static_dir.exists():
        shutil.rmtree(out_static_dir)
    shutil.copytree(static_dir, out_static_dir)

    print("Site built")
    print(f"- index: {dist_dir / 'index.html'} (week {latest_week})")
    print(f"- leaderboard: {leaderboard_out_dir} ({len(weeks)} pages)")
    print(f"- teams: {team_out_dir} ({len(latest_rows)} pages)")
    print(f"- elo charts: {elo_out_dir} ({len(teams)} pages)")
    print(f"- static: {out_static_dir}")


def main() -> None:
    cfg = SiteConfig(
        analytics_api_base=os.getenv("ANALYTICS_API_BASE", DEFAULT_ANALYTICS_API),
        timeout_s=int(os.getenv("ANALYTICS_API_TIMEOUT_S", "15")),
    )
    build_site(cfg)



if __name__ == "__main__":
    main()

#ROOT python ui\build\build_site.py