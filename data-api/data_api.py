# app/main.py
#
# FastAPI API layer for your SQLite DB:
#   app/data/nfl-season-2024.db
#
# Endpoints:
#   GET /health
#   GET /games
#     - optional query params: week, team, played (true/false)
#   GET /teams
#   GET /teams/{team_name}/summary
#
# Run (from project root):
#   pip install fastapi uvicorn
#   uvicorn app.main:app --reload
#
# Notes:
# - This assumes a table named `games` with columns:
#   match_number, week, game_date, home_team, away_team, home_score, away_score

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NFL Season 2024 API", version="1.0.0")

# If you have a separate UI dev server, CORS helps.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Relative path so it works on any machine / Docker later
from pathlib import Path


DB_PATH = Path(os.getenv("DB_PATH", "/data/nfl-season-2024.db"))


CUTOFF_DATE = "2025-01-06"


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found at: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # lets us convert rows -> dict easily
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1;").fetchone()
        return {"status": "ok", "db_path": DB_PATH}
    except Exception as e:
        return {"status": "error", "db_path": str(DB_PATH), "error": str(e)}


@app.get("/teams")
def list_teams() -> Dict[str, Any]:
    """
    Returns a deduplicated list of team names from both home_team and away_team.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT home_team AS team FROM games
            UNION
            SELECT DISTINCT away_team AS team FROM games
            ORDER BY team;
            """
        ).fetchall()

    teams = [r["team"] for r in rows if r["team"] is not None]
    return {"count": len(teams), "teams": teams}


@app.get("/games")
def list_games(
    week: Optional[int] = Query(default=None, ge=1, description="Filter by week number"),
    team: Optional[str] = Query(default=None, description="Filter games where team is home or away"),
    played: Optional[bool] = Query(
        default=None,
        description="If true, only games with scores; if false, only games without scores",
    ),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """
    Returns games as JSON rows from the DB.
    Optional filters:
      - week
      - team (matches home_team OR away_team)
      - played:
          true  => home_score and away_score NOT NULL
          false => either score is NULL
    """
    where: List[str] = []
    params: List[Any] = []

    if week is not None:
        where.append("week = ?")
        params.append(week)

    if team is not None:
        where.append("(home_team = ? OR away_team = ?)")
        params.extend([team, team])

    if played is True:
        where.append("(home_score IS NOT NULL AND away_score IS NOT NULL)")
    elif played is False:
        where.append("(home_score IS NULL OR away_score IS NULL)")

    # Always exclude postseason games
    where.append("game_date < ?")
    params.append(CUTOFF_DATE)

    where_sql = f"WHERE {' AND '.join(where)}"
    sql = f"""
        SELECT
            match_number,
            week,
            game_date,
            home_team,
            away_team,
            home_score,
            away_score
        FROM games
        {where_sql}
        ORDER BY week ASC, game_date ASC, match_number ASC
        LIMIT ? OFFSET ?;
    """
    params.extend([limit, offset])

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    games = [row_to_dict(r) for r in rows]
    return {"count": len(games), "games": games}


@app.get("/teams/{team_name}/summary")
def team_summary(team_name: str) -> Dict[str, Any]:
    """
    Computes:
      - points_for (PF)
      - points_against (PA)
      - games_played (only counted when both scores exist)
    Correctly handles team appearing as home or away.
    """
    with get_conn() as conn:
        # Ensure the team exists at least once
        exists = conn.execute(
            "SELECT 1 FROM games WHERE home_team = ? OR away_team = ? LIMIT 1;",
            (team_name, team_name),
        ).fetchone()

        if not exists:
            raise HTTPException(status_code=404, detail=f"Team not found: {team_name}")

        row = conn.execute(
            """
            SELECT
                COUNT(*) AS games_played,
                COALESCE(SUM(
                    CASE
                        WHEN home_team = ? THEN home_score
                        WHEN away_team = ? THEN away_score
                        ELSE 0
                    END
                ), 0) AS points_for,
                COALESCE(SUM(
                    CASE
                        WHEN home_team = ? THEN away_score
                        WHEN away_team = ? THEN home_score
                        ELSE 0
                    END
                ), 0) AS points_against
            FROM games
            WHERE
                (home_team = ? OR away_team = ?)
                AND game_date < ?
                AND home_score IS NOT NULL
                AND away_score IS NOT NULL;
            """,
            (
                team_name,
                team_name,
                team_name,
                team_name,
                team_name,
                team_name,
                CUTOFF_DATE,
            ),
        ).fetchone()

    return {
        "team": team_name,
        "games_played": int(row["games_played"]),
        "points_for": int(row["points_for"]),
        "points_against": int(row["points_against"]),
        "point_diff": int(row["points_for"]) - int(row["points_against"]),
    }

#python -m uvicorn data-api.data_api:app --reload



#http://127.0.0.1:8000/health

#http://127.0.0.1:8000/games?limit=5

#http://127.0.0.1:8000/teams

#http://127.0.0.1:8000/teams/Kansas%20City%20Chiefs/summary

#http://127.0.0.1:8000/games?team=Kansas%20City%20Chiefs&played=true