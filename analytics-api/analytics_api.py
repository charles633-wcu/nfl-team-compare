from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import hashlib
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query

from compute_elo import EloConfig, collect_teams, compute_weekly_elo, fetch_played_games, persist_elo_to_sqlite

# This service accepts both the current and older local env names so the
# analytics layer can talk to the data API in direct or gateway-style runs.
app = FastAPI(title="NFL Elo Analytics API", version="1.2.0")

CFG = EloConfig()

# OLD env name kept for reference and compatibility:
# API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
API_BASE = os.getenv("ELO_API_BASE") or os.getenv("API_BASE", "http://127.0.0.1:8000")
ELO_JSON_PATH = Path(os.getenv("ELO_JSON_PATH", f"elo/elo_{CFG.season}.json"))
ELO_DB_DIR = Path(os.getenv("ELO_DB_DIR", "database"))
ELO_DB_PATH = Path(os.getenv("ELO_DB_PATH", str(ELO_DB_DIR / "nfl-elo.db")))

# Multi-season serving: each season is broadcast from its own elo_{season}.json
# under ELO_DIR (defaults to the directory of ELO_JSON_PATH, i.e. ./elo).
LATEST_SEASON = 2025
ELO_DIR = Path(os.getenv("ELO_DIR", str(ELO_JSON_PATH.parent)))


def resolve_elo_json_path(season: int) -> Path:
    return ELO_DIR / f"elo_{season}.json"


def read_elo(season: int) -> Dict[str, Any]:
    """Load a season's Elo broadcast; 404 if that season isn't available."""
    p = resolve_elo_json_path(season)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Elo not available for season {season} at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_elo_json() -> Dict[str, Any]:
    if not ELO_JSON_PATH.exists():
        raise FileNotFoundError(
            f"Elo JSON not found at {ELO_JSON_PATH}. Run compute_elo.py or call POST /elo/recompute."
        )
    return json.loads(ELO_JSON_PATH.read_text(encoding="utf-8"))


def ensure_elo_json(force: bool = False) -> Dict[str, Any]:
    if force or (not ELO_JSON_PATH.exists()):
        games = fetch_played_games(API_BASE)
        teams = collect_teams(games)
        result = compute_weekly_elo(games, teams, CFG)
        ELO_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        ELO_JSON_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
        persist_elo_to_sqlite(result=result, cfg=CFG, db_path=ELO_DB_PATH)
        return result
    return load_elo_json()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "elo_json_path": str(ELO_JSON_PATH),
        "api_base": API_BASE,
        "season": CFG.season,
        "weeks": CFG.weeks,
        "k_factor": CFG.k_factor,
        "baseline": CFG.baseline,
    }

@app.get("/elo/meta")
def elo_meta(
    sha256: bool = Query(default=False, description="If true, include sha256 of the elo json file"),
) -> Dict[str, Any]:

    p = ELO_JSON_PATH

    meta: Dict[str, Any] = {
        "status": "ok",
        "elo_json_path": str(p),
        "api_base": API_BASE,
        "season": CFG.season,
        "exists": p.exists(),
    }

    if not p.exists():
        meta["status"] = "missing"
        meta["message"] = "Elo JSON not found. Call POST /elo/recompute to generate it."
        return meta

    try:
        st = p.stat()
        meta["bytes"] = int(st.st_size)
        meta["modified_utc"] = (
            datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)

        meta["weeks_present"] = len((data.get("elo") or {}).keys())
        meta["teams_present"] = len((data.get("teams") or {}).keys())

        if sha256:
            meta["sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        return meta

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Elo JSON exists but is not valid JSON: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read Elo JSON meta: {e}",
        )


@app.post("/elo/recompute")
def recompute() -> Dict[str, Any]:
    data = ensure_elo_json(force=True)
    return {
        "status": "recomputed",
        "elo_json_path": str(ELO_JSON_PATH),
        "weeks_present": len(data.get("elo", {})),
    }


@app.get("/elo/all")
def elo_all(
    season: int = Query(default=LATEST_SEASON, description="Season to serve"),
) -> Dict[str, Any]:
    # Full artifact for the requested season
    return read_elo(season)


@app.get("/elo")
def get_elo(
    season: int = Query(default=LATEST_SEASON, description="Season to serve"),
    week: Optional[int] = Query(default=None, ge=0, le=18),
) -> Dict[str, Any]:
    """
    Leaderboard-only:
      - if week provided: returns team -> elo for that week
      - else: returns whole artifact
    """
    data = read_elo(season)
    if week is None:
        return data

    wk = str(week)
    if wk not in data.get("elo", {}):
        raise HTTPException(status_code=404, detail=f"Week not found: {week}")

    return {"season": data["season"], "week": week, "elo": data["elo"][wk]}


@app.get("/elo/{week}")
def get_elo_week(
    week: int,
    season: int = Query(default=LATEST_SEASON, description="Season to serve"),
) -> Dict[str, Any]:
    return get_elo(season=season, week=week)


@app.get("/teams/{team_name}/elo")
def team_elo(
    team_name: str,
    season: int = Query(default=LATEST_SEASON, description="Season to serve"),
) -> Dict[str, Any]:
    """
    Team page:
      Returns weeks 0..18, and for each week includes:
        - final_elo (end-of-week int)
        - games: opponent, opponent_elo_pre, PF/PA, margin, elo_after_game
    """
    data = read_elo(season)

    teams_blob = data.get("teams", {})
    if team_name not in teams_blob:
        raise HTTPException(status_code=404, detail=f"Team not found: {team_name}")

    weeks_out = []
    for w in range(0, CFG.weeks + 1):
        wk = str(w)
        wk_obj = teams_blob[team_name].get(wk)
        if wk_obj is None:
            # should not happen with our compute_elo output; fail loudly
            raise HTTPException(status_code=500, detail=f"Missing team/week in artifact: {team_name} week {w}")

        weeks_out.append(
            {
                "week": w,
                "final_elo": int(wk_obj["final_elo"]),
                "games": wk_obj["games"],
            }
        )

    return {"season": data["season"], "team": team_name, "weeks": weeks_out}


