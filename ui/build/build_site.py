from __future__ import annotations

import json
import os
import random
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


# This module builds the static site against whichever local analytics endpoint
# is actually reachable, so the UI works with either direct uvicorn or gateway-based runs.

# OLD local-only default kept for reference:
# DEFAULT_ANALYTICS_API = "http://127.0.0.1:8001"
DEFAULT_ANALYTICS_API = "http://localhost:9080/analytics"

HOMEPAGE_FEATURES = [
    {
        "eyebrow": "Rankings",
        "title": "Weekly Leaderboards",
        "description": "Track weekly risers, fallers, and every shift in the season's power structure.",
        "href": "leaderboard/week-{latest_week}.html",
        "image": "static/img/homepage/leaderboard.png",
        "accent": "Power index",
    },
    {
        "eyebrow": "Directory",
        "title": "Teams Hub",
        "description": "Move through every franchise and jump straight into profile or Elo chart views.",
        "href": "teams/index.html",
        "image": "static/img/homepage/teams.png",
        "accent": "Browse all teams",
    },
    {
        "eyebrow": "Profiles",
        "title": "Team Profiles",
        "description": "Follow each week, each game, and the rating changes that shaped the year.",
        "href": "team/philadelphia-eagles.html",
        "image": "static/img/homepage/team-profile.png",
        "accent": "Game-by-game lens",
    },
    {
        "eyebrow": "Trends",
        "title": "Elo Trend Charts",
        "description": "See full-season movement and compare each team against division rivals over time.",
        "href": "elo/philadelphia-eagles.html",
        "image": "static/img/homepage/elo-chart.png",
        "accent": "Season trajectory",
    },
    {
        "eyebrow": "Simulation",
        "title": "Matchup Simulator",
        "description": "Compare any two teams with win probabilities, expected margin, and playoff views.",
        "href": "matchup.html",
        "image": "static/img/homepage/matchup.png",
        "accent": "Forecast engine",
    },
]


@dataclass(frozen=True)
class SiteConfig:
    analytics_api_base: str
    timeout_s: int = 15


def resolve_dist_dir(script_path: Path) -> Path:
    """Resolve the dist output directory, preferring the main repo when building from a worktree."""
    env_dist = os.getenv("UI_DIST_DIR")
    if env_dist:
        return Path(env_dist).resolve()

    ui_dir = script_path.resolve().parents[1]

    # OLD behavior kept for reference:
    # dist_dir = ui_dir / "dist"
    if len(script_path.resolve().parents) >= 5 and script_path.resolve().parents[3].name == ".worktrees":
        return script_path.resolve().parents[4] / "ui" / "dist"

    return ui_dir / "dist"


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


def compute_matchup_matrix(elo_all: Dict[str, Any]) -> Dict[str, Any]:
    """Build a win-probability matrix from the Elo artifact.

    Uses the pre-computed matrix if present; otherwise derives it from
    the final-week Elo ratings and the margin OLS model.
    """
    if "matchup_matrix" in elo_all:
        return elo_all["matchup_matrix"]

    elo_blob = elo_all.get("elo", {})
    margin_model = elo_all.get("margin_model", {})
    weeks = [int(w) for w in elo_blob if w.isdigit()]
    if not weeks:
        return {}

    final_elos = elo_blob[str(max(weeks))]
    intercept = float(margin_model.get("intercept", 0.0))
    slope = float(margin_model.get("slope", 0.0))

    teams = sorted(final_elos.keys())
    matrix: Dict[str, Any] = {}
    for team_a in teams:
        matrix[team_a] = {}
        for team_b in teams:
            if team_a == team_b:
                continue
            elo_a = float(final_elos[team_a])
            elo_b = float(final_elos[team_b])
            win_prob = round(1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0)), 3)
            margin = round(intercept + slope * (elo_a - elo_b), 1)
            matrix[team_a][team_b] = {"win_prob": win_prob, "predicted_margin": margin}
    return matrix


def score_model_for_site(elo_all: Dict[str, Any]) -> Dict[str, float]:
    sm = elo_all.get("score_model", {})
    return {
        "totalPointsMean": float(sm.get("total_points_mean", 43.5)),
        "totalPointsStdDev": float(sm.get("total_points_std_dev", 10.0)),
        "marginStdDev": float(sm.get("margin_std_dev", PLAYOFF_MARGIN_STD_DEV)),
    }


PLAYOFF_SEEDS_2024 = {
    "AFC": [
        {"seed": 1, "team": "Kansas City Chiefs",      "bye": True},
        {"seed": 2, "team": "Buffalo Bills",            "bye": False},
        {"seed": 3, "team": "Baltimore Ravens",         "bye": False},
        {"seed": 4, "team": "Houston Texans",           "bye": False},
        {"seed": 5, "team": "Los Angeles Chargers",     "bye": False},
        {"seed": 6, "team": "Pittsburgh Steelers",      "bye": False},
        {"seed": 7, "team": "Denver Broncos",           "bye": False},
    ],
    "NFC": [
        {"seed": 1, "team": "Detroit Lions",            "bye": True},
        {"seed": 2, "team": "Philadelphia Eagles",      "bye": False},
        {"seed": 3, "team": "Los Angeles Rams",         "bye": False},
        {"seed": 4, "team": "Tampa Bay Buccaneers",     "bye": False},
        {"seed": 5, "team": "Washington Commanders",    "bye": False},
        {"seed": 6, "team": "Minnesota Vikings",        "bye": False},
        {"seed": 7, "team": "Green Bay Packers",        "bye": False},
    ],
}

PLAYOFF_OUTCOME_2024 = {
    "champion": "Philadelphia Eagles",
    "runner_up": "Kansas City Chiefs",
    "conference_championship_runners_up": ["Buffalo Bills", "Washington Commanders"],
}

PLAYOFF_HOME_FIELD_ADV = 65
PLAYOFF_MARGIN_STD_DEV = 13.45
PLAYOFF_SIMULATION_COUNT = 100_000
PLAYOFF_SIMULATION_SEED = 42

# Real 2025 playoffs (hardcoded, like 2024). Seeds reconstructed from the 2025
# standings + the actual playoff host pattern; outcome from the postseason results
# (Seattle beat New England in the Super Bowl).
PLAYOFF_SEEDS_2025 = {
    "AFC": [
        {"seed": 1, "team": "Denver Broncos",           "bye": True},
        {"seed": 2, "team": "New England Patriots",      "bye": False},
        {"seed": 3, "team": "Jacksonville Jaguars",      "bye": False},
        {"seed": 4, "team": "Pittsburgh Steelers",       "bye": False},
        {"seed": 5, "team": "Houston Texans",            "bye": False},
        {"seed": 6, "team": "Buffalo Bills",             "bye": False},
        {"seed": 7, "team": "Los Angeles Chargers",      "bye": False},
    ],
    "NFC": [
        {"seed": 1, "team": "Seattle Seahawks",          "bye": True},
        {"seed": 2, "team": "Philadelphia Eagles",       "bye": False},
        {"seed": 3, "team": "Chicago Bears",             "bye": False},
        {"seed": 4, "team": "Carolina Panthers",         "bye": False},
        {"seed": 5, "team": "Los Angeles Rams",          "bye": False},
        {"seed": 6, "team": "Green Bay Packers",         "bye": False},
        {"seed": 7, "team": "San Francisco 49ers",       "bye": False},
    ],
}

PLAYOFF_OUTCOME_2025 = {
    "champion": "Seattle Seahawks",
    "runner_up": "New England Patriots",
    "conference_championship_runners_up": ["Denver Broncos", "Los Angeles Rams"],
}

# Per-season playoff registry. Build order is latest-first (drives picker order).
SEASON_PLAYOFFS: Dict[int, Dict[str, Any]] = {
    2024: {"seeds": PLAYOFF_SEEDS_2024, "outcome": PLAYOFF_OUTCOME_2024},
    2025: {"seeds": PLAYOFF_SEEDS_2025, "outcome": PLAYOFF_OUTCOME_2025},
}
BUILD_SEASONS: List[int] = [2025, 2024]
_PLAYOFF_SIM_CACHE: Dict[Tuple[Tuple[str, int], int, int, float, float, int], Dict[str, Any]] = {}


def build_matchup_page(
    env,
    elo_all: Dict[str, Any],
    dist_dir: Path,
    season: Any,
    playoff_seeds: Dict[str, Any],
) -> None:
    """Render matchup.html with all simulator data embedded as JSON."""
    weekly_elos = elo_all.get("elo", {})
    games_by_team = elo_all.get("teams", {})
    mm = elo_all.get("margin_model", {})
    margin_model = {
        "intercept": float(mm.get("intercept", 0.0)),
        "slope": float(mm.get("slope", 0.0)),
    }
    score_model = score_model_for_site(elo_all)
    k_factor = int(elo_all.get("k_factor", 25))

    tpl = env.get_template("matchup.html")
    html = tpl.render(
        season=season,
        weekly_elos_json=json.dumps(weekly_elos, separators=(",", ":")),
        games_by_team_json=json.dumps(games_by_team, separators=(",", ":")),
        margin_model_json=json.dumps(margin_model, separators=(",", ":")),
        score_model_json=json.dumps(score_model, separators=(",", ":")),
        playoff_seeds_json=json.dumps(playoff_seeds, separators=(",", ":")),
        k_factor=k_factor,
    )
    (dist_dir / "matchup.html").write_text(html, encoding="utf-8")


def resolve_analytics_api_base(configured_base: str, timeout_s: int) -> str:
    """Choose the first reachable analytics endpoint from the supported local variants."""
    candidates: List[str] = []

    def add_candidate(value: str | None) -> None:
        if not value:
            return
        cleaned = value.rstrip("/")
        if cleaned not in candidates:
            candidates.append(cleaned)

    add_candidate(configured_base)
    add_candidate(os.getenv("ANALYTICS_API_BASE"))

    # OLD direct local service default kept in the candidate list for compatibility.
    add_candidate("http://localhost:9080/analytics")
    add_candidate("http://127.0.0.1:9080/analytics")
    add_candidate("http://localhost:8001")
    add_candidate("http://127.0.0.1:8001")

    for candidate in candidates:
        try:
            http_get_json(f"{candidate}/health", timeout_s=timeout_s)
            return candidate
        except Exception:
            continue

    return configured_base.rstrip("/")


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


def latest_elo_map(elo_all: Dict[str, Any]) -> Dict[str, int]:
    weeks = parse_weeks_from_elo_all(elo_all)
    if not weeks:
        return {}

    latest = elo_all["elo"][str(max(weeks))]
    result: Dict[str, int] = {}
    for team, elo_val in latest.items():
        try:
            result[team] = int(elo_val)
        except Exception:
            result[team] = int(float(elo_val))
    return result


def playoff_win_probability(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def update_playoff_elo(winner_elo: int, loser_elo: int, k_factor: int) -> Tuple[int, int]:
    p_win = playoff_win_probability(winner_elo, loser_elo)
    return (
        round(winner_elo + k_factor * (1 - p_win)),
        round(loser_elo + k_factor * (0 - (1 - p_win))),
    )


def simulate_playoff_bracket(
    initial_elos: Dict[str, int],
    margin_model: Dict[str, float],
    k_factor: int,
    rng: random.Random,
    playoff_seeds: Dict[str, Any],
) -> str:
    elos = {
        seed["team"]: initial_elos.get(seed["team"], 1500)
        for seeds in playoff_seeds.values()
        for seed in seeds
    }
    original_seeds = {
        seed["team"]: seed["seed"]
        for seeds in playoff_seeds.values()
        for seed in seeds
    }
    bye_teams = {
        conf: next(seed["team"] for seed in seeds if seed["bye"])
        for conf, seeds in playoff_seeds.items()
    }

    def seed_map(conf: str) -> Dict[int, str]:
        return {seed["seed"]: seed["team"] for seed in playoff_seeds[conf]}

    def play(home: str, away: str, neutral: bool = False) -> str:
        hfa = 0 if neutral else PLAYOFF_HOME_FIELD_ADV
        expected_margin = margin_model["intercept"] + margin_model["slope"] * (
            elos[home] + hfa - elos[away]
        )
        winner, loser = (home, away) if rng.gauss(expected_margin, PLAYOFF_MARGIN_STD_DEV) >= 0 else (away, home)
        elos[winner], elos[loser] = update_playoff_elo(elos[winner], elos[loser], k_factor)
        return winner

    wild_card_winners: Dict[str, List[str]] = {"AFC": [], "NFC": []}
    for conf in ("AFC", "NFC"):
        seeds = seed_map(conf)
        for home_seed, away_seed in [(2, 7), (3, 6), (4, 5)]:
            wild_card_winners[conf].append(play(seeds[home_seed], seeds[away_seed]))

    divisional_winners: Dict[str, List[str]] = {"AFC": [], "NFC": []}
    for conf in ("AFC", "NFC"):
        survivors = sorted(
            wild_card_winners[conf] + [bye_teams[conf]],
            key=lambda team: original_seeds[team],
        )
        divisional_winners[conf].append(play(survivors[0], survivors[3]))
        divisional_winners[conf].append(play(survivors[1], survivors[2]))

    conference_winners = {}
    for conf in ("AFC", "NFC"):
        survivors = sorted(divisional_winners[conf], key=lambda team: original_seeds[team])
        conference_winners[conf] = play(survivors[0], survivors[1])

    return play(conference_winners["AFC"], conference_winners["NFC"], neutral=True)


def run_playoff_monte_carlo(
    initial_elos: Dict[str, int],
    margin_model: Dict[str, float],
    k_factor: int,
    playoff_seeds: Dict[str, Any],
    simulation_count: int = PLAYOFF_SIMULATION_COUNT,
    seed: int = PLAYOFF_SIMULATION_SEED,
) -> Dict[str, Any]:
    seeds_sig = tuple(
        (conf, tuple(s["team"] for s in seeds)) for conf, seeds in sorted(playoff_seeds.items())
    )
    cache_key = (
        tuple(sorted(initial_elos.items())),
        k_factor,
        simulation_count,
        margin_model["intercept"],
        margin_model["slope"],
        seed,
        seeds_sig,
    )
    if cache_key in _PLAYOFF_SIM_CACHE:
        return _PLAYOFF_SIM_CACHE[cache_key]

    rng = random.Random(seed)
    wins_by_team: Dict[str, int] = {}
    for _ in range(simulation_count):
        champion = simulate_playoff_bracket(initial_elos, margin_model, k_factor, rng, playoff_seeds)
        wins_by_team[champion] = wins_by_team.get(champion, 0) + 1

    result = {"simulation_count": simulation_count, "wins_by_team": wins_by_team}
    _PLAYOFF_SIM_CACHE[cache_key] = result
    return result


def build_season_pulse(
    elo_all: Dict[str, Any], outcome: Dict[str, Any], playoff_seeds: Dict[str, Any]
) -> Dict[str, Any]:
    elos = latest_elo_map(elo_all)
    mm = elo_all.get("margin_model", {})
    margin_model = {
        "intercept": float(mm.get("intercept", 0.0)),
        "slope": float(mm.get("slope", 0.0)),
    }
    k_factor = int(elo_all.get("k_factor", 25))
    simulation = run_playoff_monte_carlo(elos, margin_model, k_factor, playoff_seeds)

    champion = outcome["champion"]
    runner_up = outcome["runner_up"]
    third_place = max(
        outcome["conference_championship_runners_up"],
        key=lambda team: elos.get(team, 0),
    )
    champion_wins = simulation["wins_by_team"].get(champion, 0)
    champion_odds = champion_wins / simulation["simulation_count"] * 100

    def card(rank: str, team: str, label: str) -> Dict[str, Any]:
        return {
            "rank": rank,
            "team": team,
            "label": label,
            "elo": elos.get(team, 1500),
            "logo": f"static/img/logos/{slugify(team)}.png",
        }

    return {
        "cards": [
            card("Champion", champion, "Super Bowl champion"),
            card("Runner-up", runner_up, "Super Bowl runner-up"),
            card("Third", third_place, "Highest-Elo conference championship runner-up"),
        ],
        "champion": champion,
        "odds_label": f"{champion_odds:.1f}%",
        "simulation_label": f"{simulation['simulation_count']:,} Elo playoff simulations",
    }


def resolve_homepage_features(latest_week: int) -> List[Dict[str, str]]:
    features: List[Dict[str, str]] = []
    for feature in HOMEPAGE_FEATURES:
        resolved = dict(feature)
        resolved["href"] = resolved["href"].format(latest_week=latest_week)
        features.append(resolved)
    return features


def build_one_season(
    env: "Environment",
    analytics_api_base: str,
    season: int,
    season_dist_dir: Path,
    base_path: str,
    playoff: Dict[str, Any],
    all_seasons: List[Dict[str, Any]],
    static_dir: Path,
    repo_root: Path,
    cfg: SiteConfig,
) -> Dict[str, Any]:
    """Build a complete site for one season into season_dist_dir.

    base_path (e.g. "/2025/") is exposed to every template as a Jinja global so
    nav/asset links resolve within this season's subtree. Returns a small summary
    (champion, top team) for the season-picker landing.
    """
    leaderboard_out_dir = season_dist_dir / "leaderboard"
    teams_out_dir = season_dist_dir / "teams"
    team_out_dir = season_dist_dir / "team"
    elo_out_dir = season_dist_dir / "elo"
    for d in (season_dist_dir, leaderboard_out_dir, teams_out_dir, team_out_dir, elo_out_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Season-scoped template context shared by every render (nav toggle + links).
    env.globals["base_path"] = base_path
    env.globals["current_season"] = season
    env.globals["all_seasons"] = all_seasons

    # Fetch this season's analytics broadcast.
    elo_all_url = f"{analytics_api_base.rstrip('/')}/elo/all?season={season}"
    elo_all = http_get_json(elo_all_url, timeout_s=cfg.timeout_s)

    api_season = elo_all.get("season")
    baseline = elo_all.get("baseline")
    k_factor = elo_all.get("k_factor")

    weeks = parse_weeks_from_elo_all(elo_all)
    if not weeks:
        raise RuntimeError(f"No weeks found in {elo_all_url}. Got keys: {list(elo_all.keys())}")
    latest_week = max(weeks)
    score_model = score_model_for_site(elo_all)

    # Homepage
    index_tpl = env.get_template("index.html")
    latest_rows = leaderboard_rows_for_week(elo_all, latest_week)
    homepage_features = resolve_homepage_features(latest_week)
    season_pulse = build_season_pulse(elo_all, playoff["outcome"], playoff["seeds"])
    index_html = index_tpl.render(
        season=api_season,
        baseline=baseline,
        k_factor=k_factor,
        current_week=latest_week,
        active_page="home",
        page_name="home",
        homepage_features=homepage_features,
        season_pulse=season_pulse,
        primary_cta_href="teams/index.html",
        secondary_cta_href="matchup.html",
        rankings_cta_href=f"leaderboard/week-{latest_week}.html",
    )
    (season_dist_dir / "index.html").write_text(index_html, encoding="utf-8")

    # About + contact
    for name in ("about", "contact"):
        tpl = env.get_template(f"{name}.html")
        (season_dist_dir / f"{name}.html").write_text(
            tpl.render(
                season=api_season,
                baseline=baseline,
                k_factor=k_factor,
                current_week=latest_week,
                score_model=score_model,
            ),
            encoding="utf-8",
        )

    # Matchup simulator (season-specific playoff seeds)
    build_matchup_page(env, elo_all, season_dist_dir, api_season, playoff["seeds"])

    # Teams index
    teams_tpl = env.get_template("teams.html")
    (teams_out_dir / "index.html").write_text(
        teams_tpl.render(
            season=api_season, baseline=baseline, k_factor=k_factor, current_week=latest_week,
            teams=sorted((team for team, _e, _d in latest_rows), key=str.lower),
        ),
        encoding="utf-8",
    )

    # Team pages
    team_tpl = env.get_template("team.html")
    failures = []
    for team, _elo, _delta in latest_rows:
        try:
            payload = fetch_team_timeline(analytics_api_base, team, timeout_s=cfg.timeout_s, season=season)
            weeks_data = enrich_weeks(payload)
            rank, current_elo = compute_rank_and_elo(latest_rows, team)
            html = team_tpl.render(
                team=team, season=payload.get("season"), current_week=latest_week,
                rank=rank, current_elo=current_elo, weeks=weeks_data,
                baseline=baseline, k_factor=k_factor,
            )
            (team_out_dir / f"{slugify(team)}.html").write_text(html, encoding="utf-8")
        except requests.exceptions.RequestException as e:
            failures.append((team, repr(e)))
            print(f"Team page skipped: {team} ({e})")
        time.sleep(0.05)

    if failures:
        print(f"\n=== Team page failures (season {season}) ===")
        for team, err in failures:
            print(f"- {team}: {err}")

    # Elo charts
    rivals_path = repo_root / "elo" / "division_rivals.json"
    division_rivals: Dict[str, List[str]] = {}
    if rivals_path.exists():
        division_rivals = json.loads(rivals_path.read_text(encoding="utf-8"))
    teams = [team for team, _e, _d in latest_rows]
    build_elo_chart_pages(
        env=env, dist_dir=season_dist_dir, elo_all=elo_all, teams=teams,
        slugify=slugify, division_rivals=division_rivals,
    )

    # Leaderboard week pages
    week_tpl = env.get_template("leaderboard_week.html")
    for w in weeks:
        rows = leaderboard_rows_for_week(elo_all, w)
        (leaderboard_out_dir / f"week-{w}.html").write_text(
            week_tpl.render(week=w, season=api_season, baseline=baseline, k_factor=k_factor,
                            available_weeks=weeks, rows=rows),
            encoding="utf-8",
        )

    # Static assets (copied per season so base_path-relative refs resolve)
    out_static_dir = season_dist_dir / "static"
    if out_static_dir.exists():
        shutil.rmtree(out_static_dir)
    shutil.copytree(static_dir, out_static_dir)

    print(f"Season {season}: built {len(weeks)} weeks, {len(teams)} teams -> {season_dist_dir}")

    # Summary for the picker card
    elos = latest_elo_map(elo_all)
    top_team = max(elos, key=lambda t: elos.get(t, 0)) if elos else None
    return {
        "season": season,
        "base_path": base_path,
        "champion": playoff["outcome"]["champion"],
        "runner_up": playoff["outcome"]["runner_up"],
        "top_team": top_team,
        "top_elo": elos.get(top_team, 0) if top_team else 0,
    }


def build_site(cfg: SiteConfig) -> None:
    here = Path(__file__).resolve()
    ui_dir = here.parents[1]  # .../ui
    templates_dir = ui_dir / "templates"
    static_dir = ui_dir / "static"
    repo_root = here.parents[2]
    dist_dir = resolve_dist_dir(here)
    dist_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["slug"] = slugify

    analytics_api_base = resolve_analytics_api_base(cfg.analytics_api_base, timeout_s=cfg.timeout_s)

    # Nav season-toggle metadata (shared across every page of every season).
    all_seasons = [{"season": s, "base_path": f"/{s}/", "label": str(s)} for s in BUILD_SEASONS]

    summaries: List[Dict[str, Any]] = []
    for s in BUILD_SEASONS:
        playoff = SEASON_PLAYOFFS[s]
        summaries.append(
            build_one_season(
                env=env, analytics_api_base=analytics_api_base, season=s,
                season_dist_dir=dist_dir / str(s), base_path=f"/{s}/", playoff=playoff,
                all_seasons=all_seasons, static_dir=static_dir, repo_root=repo_root, cfg=cfg,
            )
        )

    # Root intro/home at dist/index.html: season-agnostic feature guide (funnels
    # to the picker) + a "choose a season" scroller. Feature cards deep-link to
    # the #seasons scroller rather than any one season.
    env.globals["base_path"] = "/"
    env.globals["current_season"] = None
    env.globals["all_seasons"] = all_seasons
    intro_features = [dict(f, href="#seasons") for f in HOMEPAGE_FEATURES]
    intro_tpl = env.get_template("home_intro.html")
    (dist_dir / "index.html").write_text(
        intro_tpl.render(seasons=summaries, features=intro_features), encoding="utf-8"
    )

    # Static at root for the picker page
    root_static = dist_dir / "static"
    if root_static.exists():
        shutil.rmtree(root_static)
    shutil.copytree(static_dir, root_static)

    print("\nMulti-season site built")
    print(f"- picker: {dist_dir / 'index.html'}")
    for s in BUILD_SEASONS:
        print(f"- season {s}: {dist_dir / str(s) / 'index.html'}")


def main() -> None:
    cfg = SiteConfig(
        analytics_api_base=os.getenv("ANALYTICS_API_BASE", DEFAULT_ANALYTICS_API),
        timeout_s=int(os.getenv("ANALYTICS_API_TIMEOUT_S", "15")),
    )
    build_site(cfg)



if __name__ == "__main__":
    main()

#ROOT python ui\build\build_site.py
