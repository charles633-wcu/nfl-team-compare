"""
simple_nfl_loader.py

Downloads NFL 2024 fixtures and stores a simplified games table.
No API key required.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

URL = "https://fixturedownload.com/feed/json/nfl-2024"

# Path to nfl-team-compare/loader/data/nfl-season-2024.db
BASE_DIR = Path(__file__).resolve().parent          # .../loader
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "nfl-season-2024.db"


def fetch_games(url: str):
    req = Request(url, headers={"User-Agent": "nfl-loader"})
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_date_only(date_utc: str) -> str:
    return datetime.strptime(date_utc, "%Y-%m-%d %H:%M:%SZ").date().isoformat()


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            match_number INTEGER PRIMARY KEY,
            week INTEGER,
            game_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER
        );
    """)
    conn.commit()


def load_games(conn: sqlite3.Connection, games):
    inserted = 0
    for g in games:
        conn.execute("""
            INSERT OR REPLACE INTO games (
                match_number,
                week,
                game_date,
                home_team,
                away_team,
                home_score,
                away_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            g["MatchNumber"],
            g["RoundNumber"],                 # Week
            to_date_only(g["DateUtc"]),
            g["HomeTeam"],
            g["AwayTeam"],
            g["HomeTeamScore"],
            g["AwayTeamScore"]
        ))
        inserted += 1

    conn.commit()
    print(f"Loaded {inserted} games.")


def main():
    games = fetch_games(URL)
    conn = sqlite3.connect(str(DB_PATH))  # ✅ use DB_PATH
    try:
        init_db(conn)
        load_games(conn, games)

        count = conn.execute("SELECT COUNT(*) FROM games;").fetchone()[0]
        print(f"DB ready: {DB_PATH} ({count} games)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
