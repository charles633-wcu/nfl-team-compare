"""Tests for the season updater: loader/feed.py rules and update_season.py orchestration.

Unit tests use small hand-built rows (no network). Orchestration tests inject a
fake pipeline or fake server commands. One end-to-end test runs the real
servers against a saved feed snapshot, with every output in a temp folder.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "loader", ROOT / "ui" / "build"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import loader  # noqa: E402
import feed  # noqa: E402


def _feed_game(match, week, date_utc, hs=None, as_=None,
               home="Buffalo Bills", away="Miami Dolphins"):
    """One game in fixturedownload's JSON shape."""
    return {"MatchNumber": match, "RoundNumber": week, "DateUtc": date_utc,
            "Location": "Stadium", "HomeTeam": home, "AwayTeam": away, "Group": None,
            "HomeTeamScore": hs, "AwayTeamScore": as_, "Winner": ""}


class _Resp:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Loader: feed normalization -------------------------------------------

def test_feed_date_is_the_us_local_game_day():
    # A Thursday 8:15pm ET kickoff is 01:15 UTC on Friday.
    assert loader.to_date_only("2026-11-06 01:15:00Z") == "2026-11-05"
    assert loader.to_date_only("2026-11-01 18:00:00Z") == "2026-11-01"


def test_rows_from_feed_matches_the_hand_made_csv_date():
    rows = loader.rows_from_feed([_feed_game(1, 1, "2026-09-10 00:20:00Z", 13, 10,
                                             "Seattle Seahawks", "New England Patriots")], 2026)
    assert rows[0]["game_date"] == "2026-09-09"  # same as nfl-season-2026.csv row 1


def test_fetch_games_uses_a_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return _Resp(b"[]")

    monkeypatch.setattr(loader, "urlopen", fake_urlopen)
    assert loader.fetch_games("http://example.invalid", timeout=7) == []
    assert seen["timeout"] == 7


TEAMS = set(json.loads((ROOT / "elo" / "division_rivals.json").read_text(encoding="utf-8")))


def _row(match, week, hs=None, as_=None, home="Buffalo Bills", away="Miami Dolphins",
         date="2026-09-13"):
    """One normalized row, the shape rows_from_feed / rows_from_csv produce."""
    return {"season": 2026, "match_number": match, "week": week, "game_date": date,
            "home_team": home, "away_team": away, "home_score": hs, "away_score": as_}


# --- feed.validate_rows: malformed data is refused ------------------------

def test_valid_rows_have_no_refusals():
    assert feed.validate_rows([_row(1, 1, 20, 10), _row(2, 2)], TEAMS) == []


def test_empty_feed_is_refused():
    assert any("empty" in p for p in feed.validate_rows([], TEAMS))


def test_unknown_team_is_refused():
    problems = feed.validate_rows([_row(1, 1, home="Buffalo Bils")], TEAMS)
    assert any("Buffalo Bils" in p for p in problems)


@pytest.mark.parametrize("hs, as_", [(-3, 10), ("24", 10), (1.5, 10), (True, 0)])
def test_non_integer_or_negative_score_is_refused(hs, as_):
    assert feed.validate_rows([_row(1, 1, hs, as_)], TEAMS) != []


def test_one_sided_score_is_refused():
    problems = feed.validate_rows([_row(1, 1, 20, None)], TEAMS)
    assert any("one side" in p for p in problems)


def test_week_zero_is_refused():
    assert feed.validate_rows([_row(1, 0, 20, 10)], TEAMS) != []


def test_duplicate_match_number_is_refused():
    problems = feed.validate_rows([_row(1, 1, 20, 10), _row(1, 1, 20, 10)], TEAMS)
    assert any("Duplicate" in p for p in problems)


def test_postseason_rows_are_ignored_and_dropped():
    playoff = _row(273, 19, home="To be announced", away="To be announced")
    rows = [_row(1, 1, 20, 10), playoff]
    assert feed.validate_rows(rows, TEAMS) == []
    assert feed.regular_season(rows) == [rows[0]]


# --- feed.complete_through_week: only fully-scored weeks count ------------

def test_cut_keeps_complete_weeks_and_blanks_later_scores():
    rows = [_row(1, 1, 20, 10), _row(2, 1, 7, 3), _row(3, 2, 14, 13), _row(4, 2)]
    cut = feed.complete_through_week(rows)
    assert cut.week == 1
    assert [(r["home_score"], r["away_score"]) for r in cut.rows] == [
        (20, 10), (7, 3), (None, None), (None, None)]
    assert rows[2]["home_score"] == 14  # input is not mutated


def test_bye_week_does_not_block_completion():
    # Week 2 schedules only one game (everyone else on bye) and it is scored.
    rows = [_row(1, 1, 20, 10), _row(2, 1, 7, 3), _row(3, 2, 14, 13)]
    assert feed.complete_through_week(rows).week == 2


def test_postponed_game_blocks_its_week_and_is_named():
    late = _row(4, 2, home="New York Jets", away="New England Patriots", date="2026-09-20")
    rows = [_row(1, 1, 20, 10), _row(3, 2, 14, 13), late, _row(5, 3, 21, 17)]
    cut = feed.complete_through_week(rows)
    assert cut.week == 1
    assert cut.blocked == [late]
    assert cut.rows[3]["home_score"] is None  # week 3 waits behind week 2


def test_unstarted_next_week_is_not_reported_as_blocked():
    cut = feed.complete_through_week([_row(1, 1, 20, 10), _row(2, 2)])
    assert cut.week == 1 and cut.blocked == []


def test_nothing_played_is_week_zero():
    cut = feed.complete_through_week([_row(1, 1), _row(2, 2)])
    assert cut.week == 0 and cut.blocked == []
