"""
loader.py

Builds the master NFL games database (multi-season).

Sources, in order of trust:
  - 2024: migrated offline from the existing single-season DB (loader/data/nfl-season-2024.db)
  - 2025: the cleaned CSV (loader/data/nfl-season-2025.csv), already in games-column shape

Every row is tagged with a `season`. Only regular-season games (weeks 1-18) are
stored; postseason is excluded here so downstream services never have to filter it.
The original fixturedownload JSON-feed path is preserved (fetch_games/to_date_only)
for future seasons that ship as a live feed.
"""

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

URL = "https://fixturedownload.com/feed/json/nfl-2024"

# Path to nfl-team-compare/loader/data/
BASE_DIR = Path(__file__).resolve().parent          # .../loader
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Master games DB (gitignored build artifact) + per-season source paths.
MASTER_DB_PATH = DATA_DIR / "nfl-games.db"
LEGACY_2024_DB = DATA_DIR / "nfl-season-2024.db"
CSV_2025 = DATA_DIR / "nfl-season-2025.csv"

# Regular season only — postseason is intentionally not ingested.
REGULAR_SEASON_WEEKS = range(1, 19)


# --- Source: fixturedownload JSON feed (kept for future live-feed seasons) ---

def fetch_games(url: str):
    req = Request(url, headers={"User-Agent": "nfl-loader"})
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_date_only(date_utc: str) -> str:
    return datetime.strptime(date_utc, "%Y-%m-%d %H:%M:%SZ").date().isoformat()


def rows_from_feed(games, season: int):
    """Normalize fixturedownload feed records into master-DB row dicts."""
    out = []
    for g in games:
        out.append({
            "season": season,
            "match_number": g["MatchNumber"],
            "week": g["RoundNumber"],
            "game_date": to_date_only(g["DateUtc"]),
            "home_team": g["HomeTeam"],
            "away_team": g["AwayTeam"],
            "home_score": g["HomeTeamScore"],
            "away_score": g["AwayTeamScore"],
        })
    return out


# --- Schema ---

def init_db(conn: sqlite3.Connection) -> None:
    """Create the multi-season games table + season/week index (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            season       INTEGER NOT NULL,
            match_number INTEGER NOT NULL,
            week         INTEGER,
            game_date    TEXT,
            home_team    TEXT,
            away_team    TEXT,
            home_score   INTEGER,
            away_score   INTEGER,
            PRIMARY KEY (season, match_number)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_games_season_week ON games (season, week);"
    )
    conn.commit()


# --- Sources: CSV and legacy single-season SQLite ---

def rows_from_csv(csv_path, season: int):
    """Read the cleaned per-season CSV (games-column shape) into row dicts."""
    out = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({
                "season": season,
                "match_number": int(r["match_number"]),
                "week": int(r["week"]),
                "game_date": r["game_date"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "home_score": int(r["home_score"]) if r["home_score"] != "" else None,
                "away_score": int(r["away_score"]) if r["away_score"] != "" else None,
            })
    return out


def rows_from_sqlite(src_db_path, season: int):
    """Migrate an existing single-season games DB into season-tagged row dicts."""
    src = sqlite3.connect(str(src_db_path))
    src.row_factory = sqlite3.Row
    try:
        out = []
        for r in src.execute(
            "SELECT match_number, week, game_date, home_team, away_team, "
            "home_score, away_score FROM games"
        ):
            out.append({
                "season": season,
                "match_number": r["match_number"],
                "week": r["week"],
                "game_date": r["game_date"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "home_score": r["home_score"],
                "away_score": r["away_score"],
            })
        return out
    finally:
        src.close()


# --- Write ---

def write_games(conn: sqlite3.Connection, rows) -> int:
    """Upsert rows into the master games table; skip non-regular-season weeks."""
    inserted = 0
    for g in rows:
        wk = g["week"]
        if wk is None or int(wk) not in REGULAR_SEASON_WEEKS:
            continue  # regular season only
        conn.execute(
            """
            INSERT OR REPLACE INTO games (
                season, match_number, week, game_date,
                home_team, away_team, home_score, away_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                g["season"], g["match_number"], wk, g["game_date"],
                g["home_team"], g["away_team"], g["home_score"], g["away_score"],
            ),
        )
        inserted += 1
    return inserted


# --- Orchestration ---

def build_master(master_path, csv_2025, legacy_2024_db) -> None:
    """Build the master games DB: migrate 2024 offline, ingest 2025 from CSV."""
    master_path = Path(master_path)
    master_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(master_path))
    try:
        init_db(conn)
        if legacy_2024_db and Path(legacy_2024_db).exists():
            write_games(conn, rows_from_sqlite(legacy_2024_db, season=2024))
        write_games(conn, rows_from_csv(csv_2025, season=2025))
        conn.commit()
        for s in (2024, 2025):
            n = conn.execute(
                "SELECT COUNT(*) FROM games WHERE season=?", (s,)
            ).fetchone()[0]
            print(f"season {s}: {n} games")
    finally:
        conn.close()


def main() -> None:
    build_master(MASTER_DB_PATH, CSV_2025, LEGACY_2024_DB)
    print(f"DB ready: {MASTER_DB_PATH}")


if __name__ == "__main__":
    main()
