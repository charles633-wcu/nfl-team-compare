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
