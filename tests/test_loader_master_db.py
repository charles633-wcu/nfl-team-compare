"""Tests for the multi-season master games DB build in loader.loader."""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

LOADER_DIR = Path(__file__).resolve().parents[1] / "loader"
if str(LOADER_DIR) not in sys.path:
    sys.path.insert(0, str(LOADER_DIR))

import loader  # noqa: E402

CSV_2025 = LOADER_DIR / "data" / "nfl-season-2025.csv"


def _build_2025(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "nfl-games.db"
    conn = sqlite3.connect(db)
    loader.init_db(conn)
    loader.write_games(conn, loader.rows_from_csv(CSV_2025, season=2025))
    conn.commit()
    return conn


def test_schema_has_season_column(tmp_path) -> None:
    conn = _build_2025(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(games)")}
    assert "season" in cols


def test_2025_csv_loads_272_regular_season_games(tmp_path) -> None:
    conn = _build_2025(tmp_path)
    n = conn.execute("SELECT COUNT(*) FROM games WHERE season=2025").fetchone()[0]
    assert n == 272


def test_every_2025_team_plays_17_games(tmp_path) -> None:
    conn = _build_2025(tmp_path)
    rows = conn.execute(
        "SELECT home_team AS t FROM games WHERE season=2025 "
        "UNION ALL SELECT away_team FROM games WHERE season=2025"
    ).fetchall()
    counts = Counter(r[0] for r in rows)
    assert len(counts) == 32
    assert all(v == 17 for v in counts.values())
