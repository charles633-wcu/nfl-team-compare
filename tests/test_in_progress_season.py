"""Tests for building a season that is still being played (2026).

A finished season has 18 weeks of scores, real playoff seeds and a champion.
An in-progress season has none of those, so the pipeline has to:
  - load a CSV whose unplayed games have blank scores,
  - stop Elo at the last week that actually has a final score,
  - project "if the season ended today" playoff seeds from records,
  - show projected title odds instead of a champion.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("analytics-api", "loader", "ui/build"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import build_site as bs  # noqa: E402
import compute_elo as ce  # noqa: E402
import loader  # noqa: E402

CSV_2026 = ROOT / "loader" / "data" / "nfl-season-2026.csv"
RIVALS = json.loads((ROOT / "elo" / "division_rivals.json").read_text(encoding="utf-8"))


def _game(week, home, away, hs, as_):
    return {"week": week, "game_date": f"2026-09-{week:02d}", "match_number": week,
            "home_team": home, "away_team": away, "home_score": hs, "away_score": as_}


# --- Loader ---------------------------------------------------------------

def test_2026_csv_loads_full_schedule_with_blank_scores(tmp_path):
    db = tmp_path / "nfl-games.db"
    loader.build_master(db, ROOT / "loader" / "data" / "nfl-season-2025.csv",
                        ROOT / "loader" / "data" / "nfl-season-2024.db", csv_2026=CSV_2026)
    conn = sqlite3.connect(db)
    total = conn.execute("SELECT COUNT(*) FROM games WHERE season=2026").fetchone()[0]
    played = conn.execute(
        "SELECT COUNT(*) FROM games WHERE season=2026 AND home_score IS NOT NULL").fetchone()[0]
    other = conn.execute("SELECT COUNT(*) FROM games WHERE season IN (2024, 2025)").fetchone()[0]
    conn.close()
    assert total == 272
    assert 0 < played < 272
    assert other == 544  # 2024 and 2025 untouched


def test_build_master_without_2026_is_unchanged(tmp_path):
    db = tmp_path / "nfl-games.db"
    loader.build_master(db, ROOT / "loader" / "data" / "nfl-season-2025.csv",
                        ROOT / "loader" / "data" / "nfl-season-2024.db")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM games WHERE season=2026").fetchone()[0] == 0
    conn.close()


# --- Elo: stop at the last played week ------------------------------------

def test_played_through_week_is_last_week_with_a_score():
    games = [_game(1, "A", "B", 10, 7), _game(6, "A", "B", 3, 0)]
    assert ce.played_through_week(games) == 6


def test_played_through_week_caps_at_18_and_ignores_postseason():
    games = [_game(18, "A", "B", 10, 7), _game(19, "A", "B", 3, 0)]
    assert ce.played_through_week(games) == 18


def test_played_through_week_rejects_no_games():
    with pytest.raises(ValueError):
        ce.played_through_week([])


# --- Standings and projected seeds ----------------------------------------

def _elo_all_from(games):
    teams = ce.collect_teams(games)
    cfg = ce.EloConfig(season=2026, weeks=ce.played_through_week(games))
    return ce.compute_weekly_elo(games, teams, cfg)


def test_team_records_count_wins_losses_and_ties():
    elo_all = _elo_all_from([
        _game(1, "Buffalo Bills", "Miami Dolphins", 20, 10),
        _game(2, "Miami Dolphins", "Buffalo Bills", 17, 17),
    ])
    recs = bs.team_records(elo_all)
    assert recs["Buffalo Bills"] == (1, 0, 1)
    assert recs["Miami Dolphins"] == (0, 1, 1)


def _real_2026_elo_all():
    import csv
    with open(CSV_2026, newline="", encoding="utf-8") as f:
        games = [
            {**r, "week": int(r["week"]), "match_number": int(r["match_number"]),
             "home_score": int(r["home_score"]), "away_score": int(r["away_score"])}
            for r in csv.DictReader(f) if r["home_score"] != ""
        ]
    return _elo_all_from(games)


def test_projected_seeds_have_seven_teams_per_conference_with_one_bye():
    seeds = bs.project_playoff_seeds(_real_2026_elo_all(), RIVALS)
    assert set(seeds) == {"AFC", "NFC"}
    for conf, rows in seeds.items():
        assert [r["seed"] for r in rows] == [1, 2, 3, 4, 5, 6, 7]
        assert [r["bye"] for r in rows] == [True] + [False] * 6
        teams = [r["team"] for r in rows]
        assert len(set(teams)) == 7
        assert all(bs.CONFERENCE_OF[t] == conf for t in teams)


def test_projected_seeds_1_to_4_are_division_leaders():
    elo_all = _real_2026_elo_all()
    recs = bs.team_records(elo_all)
    seeds = bs.project_playoff_seeds(elo_all, RIVALS)
    for rows in seeds.values():
        leaders = [r["team"] for r in rows[:4]]
        # No two seeds 1-4 share a division.
        divisions = {frozenset([t, *RIVALS[t]]) for t in leaders}
        assert len(divisions) == 4
        pct = lambda t: (recs[t][0] + 0.5 * recs[t][2]) / max(1, sum(recs[t]))
        # Seeds 1-4 and 5-7 are each ordered by record.
        for group in (rows[:4], rows[4:]):
            pcts = [pct(r["team"]) for r in group]
            assert pcts == sorted(pcts, reverse=True)


def test_conference_map_covers_all_32_teams():
    assert len(bs.CONFERENCE_OF) == 32
    assert set(bs.CONFERENCE_OF) == set(RIVALS)


# --- Season pulse without a champion --------------------------------------

def test_in_progress_pulse_shows_projected_favorites_not_a_champion():
    elo_all = _real_2026_elo_all()
    seeds = bs.project_playoff_seeds(elo_all, RIVALS)
    pulse = bs.build_season_pulse(elo_all, None, seeds)
    assert [c["rank"] for c in pulse["cards"]] == ["Favorite", "2nd", "3rd"]
    assert "champion" not in " ".join(c["label"].lower() for c in pulse["cards"])
    assert pulse["in_progress"] is True
    teams = [c["team"] for c in pulse["cards"]]
    assert len(set(teams)) == 3


def test_finished_season_pulse_is_unchanged():
    elo_all = json.loads((ROOT / "elo" / "elo_2025.json").read_text(encoding="utf-8"))
    p = bs.SEASON_PLAYOFFS[2025]
    pulse = bs.build_season_pulse(elo_all, p["outcome"], p["seeds"])
    assert pulse["cards"][0]["rank"] == "Champion"
    assert pulse["cards"][0]["team"] == "Seattle Seahawks"
    assert pulse.get("in_progress", False) is False


# --- Consumers must follow the artifact's week count, not a fixed 18 ------

def test_team_elo_endpoint_serves_only_played_weeks(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    elo_all = _elo_all_from([
        _game(1, "Buffalo Bills", "Miami Dolphins", 20, 10),
        _game(6, "Miami Dolphins", "Buffalo Bills", 17, 24),
    ])
    (tmp_path / "elo_2026.json").write_text(json.dumps(elo_all), encoding="utf-8")
    monkeypatch.setenv("ELO_DIR", str(tmp_path))
    sys.modules.pop("analytics_api", None)
    import analytics_api
    importlib.reload(analytics_api)

    r = TestClient(analytics_api.app).get("/teams/Buffalo Bills/elo", params={"season": 2026})
    assert r.status_code == 200, r.text
    assert [w["week"] for w in r.json()["weeks"]] == list(range(0, 7))


def test_nav_leaderboard_link_points_at_latest_built_week():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "ui" / "templates")))
    env.globals.update(base_path="/2026/", current_season=2026, all_seasons=[], latest_week=6)
    html = env.get_template("_base.html").render()
    assert "leaderboard/week-6.html" in html
    assert "leaderboard/week-18.html" not in html


# --- Season home page copy ------------------------------------------------

def _render_season_home(in_progress: bool, season: int) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "ui" / "templates")))
    env.filters["slug"] = bs.slugify
    env.globals.update(base_path=f"/{season}/", current_season=season, all_seasons=[],
                       latest_week=8)
    return env.get_template("index.html").render(
        season=season, current_week=8, features=[],
        season_pulse={"in_progress": in_progress, "cards": []})


SUBTITLE = ("Get the weekly scoop on who's hot, who's sliding, and how every single "
            "matchup shakes out all season long—right up to the final whistle!")


@pytest.mark.parametrize("in_progress, season", [(True, 2026), (False, 2025)])
def test_season_home_subtitle_is_the_same_for_every_season(in_progress, season):
    html = _render_season_home(in_progress, season)
    assert SUBTITLE in html
    assert "reshaped the picture" not in html


def test_in_progress_pulse_caption():
    html = _render_season_home(True, 2026)
    assert "Through Week 8. Here's who the model likes... so far." in html
    assert "likes —" not in html


def test_finished_pulse_caption():
    html = _render_season_home(False, 2025)
    assert "Here's how it ended. Let's see how they got there." in html
    assert "yours to unpack" not in html


def test_features_blurb_has_no_em_dash():
    html = _render_season_home(True, 2026)
    assert "replay the playoff picture, all for 2026." in html
    assert "picture —" not in html


@pytest.mark.parametrize("season", [2025, 2026])
def test_matchup_page_names_its_own_season(tmp_path, season):
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "ui" / "templates")))
    env.filters["slug"] = bs.slugify
    env.globals.update(base_path=f"/{season}/", current_season=season, all_seasons=[],
                       latest_week=8)
    elo_all = json.loads((ROOT / "elo" / f"elo_{season}.json").read_text(encoding="utf-8"))
    seeds = bs.SEASON_PLAYOFFS[season]["seeds"] or bs.project_playoff_seeds(elo_all, RIVALS)
    bs.build_matchup_page(env, elo_all, tmp_path, season, seeds)
    html = (tmp_path / "matchup.html").read_text(encoding="utf-8")
    assert f"simulate the full {season} playoff bracket." in html
    assert f"{season} playoffs</div>" in html
    assert "2024 playoff" not in html
