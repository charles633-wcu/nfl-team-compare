from dataclasses import dataclass
import requests
from urllib.parse import quote

@dataclass
class GameRow:
    opponent: str
    home: bool
    points_for: int | None
    points_against: int | None
    margin: int | None
    predicted_margin_pre: float | None
    team_elo_pre: int | None
    elo_after_game: int | None
    delta_elo: int | None

import time
import requests

def fetch_team_timeline(api_base: str, team: str, timeout_s: int = 20, retries: int = 3) -> dict:
    url = f"{api_base.rstrip('/')}/teams/{quote(team)}/elo"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout_s)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(0.4 * attempt)
    raise last_err

def compute_rank_and_elo(latest_rows: list[tuple[str, int, int | None]], team: str) -> tuple[int, int]:
    for i, (t, elo, _d) in enumerate(latest_rows, start=1):
        if t == team:
            return i, elo
    return 0, 0

def enrich_weeks(payload: dict) -> list[dict]:
    weeks = []
    for w in payload.get("weeks", []):
        games = []
        for g in w.get("games", []):
            pre = g.get("team_elo_pre")
            after = g.get("elo_after_game")
            delta = None
            if isinstance(pre, (int, float)) and isinstance(after, (int, float)):
                delta = int(round(after - pre))
            games.append({
                "opponent": g.get("opponent"),
                "home": bool(g.get("home")),
                "points_for": g.get("points_for"),
                "points_against": g.get("points_against"),
                "margin": g.get("margin"),
                "predicted_margin_pre": g.get("predicted_margin_pre"),
                "team_elo_pre": pre,
                "elo_after_game": after,
                "delta_elo": delta,
            })
        weeks.append({
            "week": int(w.get("week")),
            "final_elo": int(w.get("final_elo")),
            "games": games
        })
    # keep chronological
    weeks.sort(key=lambda x: x["week"])
    return weeks
