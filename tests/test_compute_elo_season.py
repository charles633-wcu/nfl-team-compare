"""Tests for season-aware Elo computation (compute_elo).

The committed 2024 baseline was built from 271 games due to an off-by-one date
cutoff that dropped the Lions-Vikings Week 18 game (2025-01-06). The master-DB
pipeline includes all 272 regular-season games, so these tests assert
correctness rather than byte-equality with the old (buggy) artifact.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("analytics-api", "loader"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_elo as ce  # noqa: E402
import loader  # noqa: E402


def _build_master(tmp_path):
    db = tmp_path / "nfl-games.db"
    loader.build_master(
        db,
        ROOT / "loader" / "data" / "nfl-season-2025.csv",
        ROOT / "loader" / "data" / "nfl-season-2024.db",
    )
    return str(db)


def _played_games(db_path: str, season: int):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT match_number, week, game_date, home_team, away_team, home_score, away_score "
        "FROM games WHERE season=? AND home_score IS NOT NULL "
        "ORDER BY week, game_date, match_number",
        (season,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_2024_elo_uses_all_272_games(tmp_path):
    games = _played_games(_build_master(tmp_path), 2024)
    cfg = ce.EloConfig(season=2024)
    result = ce.compute_weekly_elo(games, ce.collect_teams(games), cfg)
    assert result["margin_model"]["n_samples"] == 272
    assert len(result["teams"]) == 32
    assert all(str(w) in result["elo"] for w in range(0, 19))


def test_2024_includes_previously_dropped_week18_game(tmp_path):
    games = _played_games(_build_master(tmp_path), 2024)
    cfg = ce.EloConfig(season=2024)
    result = ce.compute_weekly_elo(games, ce.collect_teams(games), cfg)
    lions_wk18 = result["teams"]["Detroit Lions"]["18"]["games"]
    opponents = {g["opponent"] for g in lions_wk18}
    assert "Minnesota Vikings" in opponents


def test_2025_elo_has_all_18_weeks(tmp_path):
    games = _played_games(_build_master(tmp_path), 2025)
    cfg = ce.EloConfig(season=2025)
    result = ce.compute_weekly_elo(games, ce.collect_teams(games), cfg)
    assert result["season"] == 2025
    assert all(str(w) in result["elo"] for w in range(0, 19))
    assert len(result["teams"]) == 32
    assert result["margin_model"]["n_samples"] == 272


def test_score_model_uses_season_average_total_points(tmp_path):
    games = _played_games(_build_master(tmp_path), 2025)
    cfg = ce.EloConfig(season=2025)
    result = ce.compute_weekly_elo(games, ce.collect_teams(games), cfg)

    score_model = result["score_model"]
    assert score_model["total_points_mean"] == 46.025735294117645
    assert score_model["total_points_std_dev"] == 10
    assert score_model["margin_std_dev"] == 13.45
    assert score_model["n_samples"] == 272
