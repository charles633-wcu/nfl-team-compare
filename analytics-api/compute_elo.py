from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
import hashlib
import sqlite3
from datetime import datetime, timezone


import requests


@dataclass(frozen=True)
class EloConfig:
    season: int = 2024
    baseline: int = 1500
    k_factor: int = 25
    weeks: int = 18


def expected_score(r_a: float, r_b: float) -> float:
    # E_A = 1 / (1 + 10^((R_B - R_A)/400))
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))


def actual_score(home_score: int, away_score: int) -> Tuple[float, float]:
    if home_score > away_score:
        return 1.0, 0.0
    if home_score < away_score:
        return 0.0, 1.0
    return 0.5, 0.5


def mov_multiplier(point_diff: int, winner_elo: float, loser_elo: float) -> float:
    """
    FiveThirtyEight-style NFL Elo MOV multiplier:
      M = ln(|PD| + 1) * 2.2 / (0.001*(ELO_W - ELO_L) + 2.2)
    """
    return math.log(abs(point_diff) + 1.0) * (2.2 / (0.001 * (winner_elo - loser_elo) + 2.2))


def fit_ols(x: List[float], y: List[float]) -> Tuple[float, float]:
    """
    Fits y = a + b*x using closed-form OLS.
    Returns (a, b).
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0, 0.0

    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)

    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)

    if den == 0:
        return y_mean, 0.0

    b = num / den
    a = y_mean - b * x_mean
    return a, b


def predict_margin(intercept: float, slope: float, elo_diff: float) -> float:
    return intercept + slope * elo_diff


def fetch_played_games(api_base: str) -> List[Dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/games"
    params = {"played": "true", "limit": 5000}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    return payload.get("games", [])


def collect_teams(games: List[Dict[str, Any]]) -> List[str]:
    teams = set()
    for g in games:
        teams.add(g["home_team"])
        teams.add(g["away_team"])
    return sorted(teams)


def compute_weekly_elo(games: List[Dict[str, Any]], teams: List[str], cfg: EloConfig) -> Dict[str, Any]:
    # Group games by week
    games_by_week: Dict[int, List[Dict[str, Any]]] = {w: [] for w in range(1, cfg.weeks + 1)}
    for g in games:
        w = int(g["week"])
        if 1 <= w <= cfg.weeks:
            games_by_week[w].append(g)

    # floats internally, round only at end-of-week for stored Elo
    current: Dict[str, float] = {t: float(cfg.baseline) for t in teams}

    # Artifact output
    out: Dict[str, Any] = {
        "season": cfg.season,
        "baseline": cfg.baseline,
        "k_factor": cfg.k_factor,
        "weeks": cfg.weeks,
        "elo": {},
        "teams": {t: {} for t in teams},
    }

    # Training data for margin model (home-perspective per game)
    x_elo_diff: List[float] = []
    y_margin: List[float] = []

    # Week 0 snapshot
    out["elo"]["0"] = {t: int(cfg.baseline) for t in teams}
    for t in teams:
        out["teams"][t]["0"] = {"games": [], "final_elo": int(cfg.baseline)}

    # Weeks 1..18
    for week in range(1, cfg.weeks + 1):
        # deterministic ordering within week
        week_games = sorted(
            games_by_week.get(week, []),
            key=lambda g: (g.get("game_date", ""), int(g.get("match_number", 0))),
        )

        # init weekly structures for all teams (so bye weeks exist)
        for t in teams:
            out["teams"][t].setdefault(str(week), {"games": [], "final_elo": None})

        for g in week_games:
            home = g["home_team"]
            away = g["away_team"]
            hs = int(g["home_score"])
            aws = int(g["away_score"])

            # Pregame elos (floats)
            home_pre = current[home]
            away_pre = current[away]

            # Collect regression training sample (home perspective)
            x_elo_diff.append(home_pre - away_pre)
            y_margin.append(hs - aws)

            # Expected + actual
            e_home = expected_score(home_pre, away_pre)
            s_home, _ = actual_score(hs, aws)

            # Margin from each perspective
            home_margin = hs - aws
            away_margin = aws - hs

            # MOV multiplier (ties: use 1.0)
            if s_home == 0.5:
                mult = 1.0
            else:
                # Winner/loser pregame elos
                if s_home == 1.0:
                    winner_elo, loser_elo = home_pre, away_pre
                    pd = abs(home_margin)
                else:
                    winner_elo, loser_elo = away_pre, home_pre
                    pd = abs(home_margin)
                mult = mov_multiplier(pd, winner_elo, loser_elo)

            # Apply update (mirror update)
            delta_home = cfg.k_factor * mult * (s_home - e_home)
            delta_away = -delta_home

            current[home] = home_pre + delta_home
            current[away] = away_pre + delta_away

            # Store per-team game record for THIS week
            home_pre_int = int(round(home_pre))
            away_pre_int = int(round(away_pre))

            out["teams"][home][str(week)]["games"].append(
                {
                    "week": week,
                    "game_date": g.get("game_date"),
                    "opponent": away,
                    "home": True,
                    "points_for": hs,
                    "points_against": aws,
                    "margin": home_margin,
                    "team_elo_pre": home_pre_int,
                    "opponent_elo_pre": away_pre_int,
                    "elo_diff_pre": home_pre_int - away_pre_int,
                    "elo_after_game": int(round(current[home])),
                }
            )

            out["teams"][away][str(week)]["games"].append(
                {
                    "week": week,
                    "game_date": g.get("game_date"),
                    "opponent": home,
                    "home": False,
                    "points_for": aws,
                    "points_against": hs,
                    "margin": away_margin,
                    "team_elo_pre": away_pre_int,
                    "opponent_elo_pre": home_pre_int,
                    "elo_diff_pre": away_pre_int - home_pre_int,
                    "elo_after_game": int(round(current[away])),
                }
            )

        # End-of-week snapshot (integers)
        out["elo"][str(week)] = {t: int(round(current[t])) for t in teams}

        # Attach end-of-week Elo to each team week record
        for t in teams:
            out["teams"][t][str(week)]["final_elo"] = int(out["elo"][str(week)][t])

    # Fit the margin model once after Elo is computed (using pregame Elo diffs)
    a, b = fit_ols(x_elo_diff, y_margin)
    out["margin_model"] = {
        "type": "ols",
        "feature": "elo_diff_pre",
        "target": "margin",
        "intercept": a,
        "slope": b,
        "n_samples": len(x_elo_diff),
    }

    # OPTIONAL: inject predicted margin into every stored game record
    for team, weeks_blob in out["teams"].items():
        for wk, wk_obj in weeks_blob.items():
            for game in wk_obj.get("games", []):
                game["predicted_margin_pre"] = round(
                    predict_margin(a, b, float(game["elo_diff_pre"])),
                    1
                )

    return out

def persist_elo_to_sqlite(
    result: Dict[str, Any],
    cfg: EloConfig,
    db_path: Path,
) -> None:
    """
    Persist the Elo artifact into SQLite in both:
      1) raw form (a single JSON blob row)
      2) normalized tables for easy querying (weekly elos + per-team game logs)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Canonical JSON for hashing + storage
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    created_utc = (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()

        # Meta table (one row per season)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS elo_meta (
                season INTEGER PRIMARY KEY,
                created_utc TEXT NOT NULL,
                weeks INTEGER NOT NULL,
                baseline INTEGER NOT NULL,
                k_factor INTEGER NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                artifact_json TEXT NOT NULL
            )
            """
        )

        # Weekly snapshot table (team Elo by week)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS elo_weekly (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team TEXT NOT NULL,
                elo INTEGER NOT NULL,
                PRIMARY KEY (season, week, team)
            )
            """
        )

        # Per-team game logs (mirrors what you already embed under teams[team][week]["games"])
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS elo_games (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team TEXT NOT NULL,
                game_date TEXT,
                opponent TEXT NOT NULL,
                home INTEGER NOT NULL,
                points_for INTEGER NOT NULL,
                points_against INTEGER NOT NULL,
                margin INTEGER NOT NULL,
                team_elo_pre INTEGER NOT NULL,
                opponent_elo_pre INTEGER NOT NULL,
                elo_diff_pre INTEGER NOT NULL,
                elo_after_game INTEGER NOT NULL,
                predicted_margin_pre REAL,
                PRIMARY KEY (
                    season, week, team, opponent, home, points_for, points_against, team_elo_pre, opponent_elo_pre
                )
            )
            """
        )

        # Replace season data (idempotent runs)
        cur.execute("DELETE FROM elo_meta   WHERE season = ?", (cfg.season,))
        cur.execute("DELETE FROM elo_weekly WHERE season = ?", (cfg.season,))
        cur.execute("DELETE FROM elo_games  WHERE season = ?", (cfg.season,))

        # Insert meta
        cur.execute(
            """
            INSERT INTO elo_meta (
                season, created_utc, weeks, baseline, k_factor, artifact_sha256, artifact_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cfg.season, created_utc, cfg.weeks, cfg.baseline, cfg.k_factor, sha, canonical),
        )

        # Insert weekly elos
        elo_blob = result.get("elo") or {}
        for wk_str, team_map in elo_blob.items():
            try:
                wk = int(wk_str)
            except ValueError:
                continue
            if not isinstance(team_map, dict):
                continue
            for team, elo_val in team_map.items():
                cur.execute(
                    "INSERT OR REPLACE INTO elo_weekly (season, week, team, elo) VALUES (?, ?, ?, ?)",
                    (cfg.season, wk, str(team), int(elo_val)),
                )

        # Insert games
        teams_blob = result.get("teams") or {}
        for team, weeks_obj in teams_blob.items():
            if not isinstance(weeks_obj, dict):
                continue
            for wk_str, wk_obj in weeks_obj.items():
                try:
                    wk = int(wk_str)
                except ValueError:
                    continue
                games = (wk_obj or {}).get("games") or []
                for g in games:
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO elo_games (
                            season, week, team, game_date, opponent, home,
                            points_for, points_against, margin,
                            team_elo_pre, opponent_elo_pre, elo_diff_pre,
                            elo_after_game, predicted_margin_pre
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cfg.season,
                            wk,
                            str(team),
                            g.get("game_date"),
                            str(g.get("opponent")),
                            1 if bool(g.get("home")) else 0,
                            int(g.get("points_for")),
                            int(g.get("points_against")),
                            int(g.get("margin")),
                            int(g.get("team_elo_pre")),
                            int(g.get("opponent_elo_pre")),
                            int(g.get("elo_diff_pre")),
                            int(g.get("elo_after_game")),
                            (float(g["predicted_margin_pre"]) if "predicted_margin_pre" in g else None),
                        ),
                    )

        conn.commit()
    finally:
        conn.close()



def main() -> None:
    cfg = EloConfig()
    api_base = os.getenv("ELO_API_BASE", "http://127.0.0.1:8000")
    out_dir = Path(os.getenv("ELO_OUT_DIR", "elo"))
    out_dir.mkdir(parents=True, exist_ok=True)

    games = fetch_played_games(api_base)
    if not games:
        raise RuntimeError(f"No games returned from {api_base}/games?played=true")

    teams = collect_teams(games)
    result = compute_weekly_elo(games, teams, cfg)

    out_path = out_dir / f"elo_{cfg.season}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote Elo JSON -> {out_path.resolve()}")

    db_dir = Path(os.getenv("ELO_DB_DIR", "database"))
    db_path = Path(os.getenv("ELO_DB_PATH", str(db_dir / f"elo_{cfg.season}.db")))
    persist_elo_to_sqlite(result=result, cfg=cfg, db_path=db_path)
    print(f"Wrote Elo SQLite -> {db_path.resolve()}")


if __name__ == "__main__":
    main()
