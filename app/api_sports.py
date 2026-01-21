from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.cache import cache
from app.schemas import Team, TeamCompareStats
from app.settings import settings


class APISportsError(RuntimeError):
    pass


class APISportsClient:
    def __init__(self) -> None:
        self.base_url = settings.apisports_base_url.rstrip("/")
        self.headers = {"x-apisports-key": settings.apisports_key}

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers=self.headers, params=params)
        except httpx.HTTPError as e:
            raise APISportsError(f"Network error calling API-Sports: {e}") from e

        if resp.status_code >= 400:
            raise APISportsError(f"API-Sports error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # API-Sports responses typically have 'errors'/'response' keys; keep it flexible.
        return data

    async def get_all_games(self, league_id: int, season: int, team_id: int) -> list[dict]:
        all_games: list[dict] = []
        page = 1

        while True:
            payload = await self._get(
                "/games",
                params={
                    "league": league_id,
                    "season": season,
                    "team": team_id,
                    "page": page,
                },
            )

            batch = payload.get("response", [])
            all_games.extend(batch)

            paging = payload.get("paging", {}) or {}
            current = int(paging.get("current", page))
            total = int(paging.get("total", current))

            if current >= total:
                break

            page += 1

        return all_games

    async def list_teams(self, league_id: int, season: int) -> List[Team]:
        """
        Docs indicate endpoints like Teams / Standings exist for NFL & NCAA. :contentReference[oaicite:1]{index=1}
        We'll implement teams listing and map to our Team model.
        """
        cache_key = f"teams:{league_id}:{season}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Common pattern in API-Sports: GET /teams?league=...&season=...
        payload = await self._get("/teams", params={"league": league_id, "season": season})
        raw = payload.get("response", [])

        teams: List[Team] = []
        for item in raw:
            # Depending on API response shape, 'team' may be nested.
            t = item.get("team", item)
            teams.append(
                Team(
                    id=int(t.get("id")),
                    name=str(t.get("name")),
                    abbreviation=t.get("code") or t.get("abbreviation"),
                    logo=t.get("logo"),
                )
            )
        teams = [team for team in teams if team.name.strip().upper() not in {"AFC", "NFC"}]

        teams.sort(key=lambda x: x.name)
        cache.set(cache_key, teams, ttl_seconds=60 * 60)  # teams list doesn't change often
        return teams

    async def get_standings_stats(self, league_id: int, season: int, team_id: int) -> TeamCompareStats:
        """
        Fetch standings for league+season and extract one team's record.
        PF/PA are computed from completed games instead of standings.
        """
        # --- standings (W/L/T) ---
        cache_key = f"standings:{league_id}:{season}"
        standings = cache.get(cache_key)
        if standings is None:
            payload = await self._get("/standings", params={"league": league_id, "season": season})
            standings = payload.get("response", [])
            cache.set(cache_key, standings, ttl_seconds=10 * 60)

        record = _find_team_in_standings(standings, team_id)

        team_obj = record.get("team", {}) if isinstance(record, dict) else {}
        team = Team(
            id=team_id,
            name=str(team_obj.get("name") or team_obj.get("displayName") or f"Team {team_id}"),
            abbreviation=team_obj.get("code") or team_obj.get("abbreviation"),
            logo=team_obj.get("logo"),
        )

        wins = _safe_int(record, ["won", "wins", "w"])
        losses = _safe_int(record, ["lost", "losses", "l"])
        ties = _safe_int(record, ["ties", "t", "draw"])

        points_for, points_against = await self.get_points_for_against(league_id, season, team_id)

        return TeamCompareStats(
            team=team,
            wins=wins,
            losses=losses,
            ties=ties,
            points_for=points_for,
            points_against=points_against,
        )

    async def get_points_for_against(
            self, league_id: int, season: int, team_id: int
    ) -> tuple[float | None, float | None]:
        """
        Compute season PF/PA by summing finished games.
        NOTE: This endpoint does NOT support pagination on your plan, so we do a single request.
        """
        cache_key = f"pfpa:{league_id}:{season}:{team_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        payload = await self._get(
            "/games",
            params={"league": league_id, "season": season, "team": team_id},
        )
        games = payload.get("response", [])

        pf = 0
        pa = 0
        count = 0

        for g in games:
            stage = ((g.get("game") or {}).get("stage") or "").strip().lower()
            if stage != "regular season":
                continue

            scores = g.get("scores") or {}
            home_total = (scores.get("home") or {}).get("total")
            away_total = (scores.get("away") or {}).get("total")
            if home_total is None or away_total is None:
                continue

            teams = g.get("teams") or {}
            home_id = (teams.get("home") or {}).get("id")
            away_id = (teams.get("away") or {}).get("id")

            try:
                home_total = int(home_total)
                away_total = int(away_total)
            except (TypeError, ValueError):
                continue

            if str(home_id) == str(team_id):
                pf += home_total
                pa += away_total
                count += 1
            elif str(away_id) == str(team_id):
                pf += away_total
                pa += home_total
                count += 1

        result = (float(pf), float(pa)) if count > 0 else (None, None)
        cache.set(cache_key, result, ttl_seconds=10 * 60)
        return result


def _safe_int(obj: dict, keys: list[str]) -> int | None:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _safe_float(obj: dict, keys: list[str]) -> float | None:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def _find_team_in_standings(standings: Any, team_id: int) -> dict:
    """
    Standings response nesting differs by sport/provider.
    We'll walk lists/dicts until we find a dict with team.id == team_id.
    """
    if isinstance(standings, dict):
        t = standings.get("team") or {}
        if isinstance(t, dict) and str(t.get("id")) == str(team_id):
            return standings
        for v in standings.values():
            found = _find_team_in_standings(v, team_id)
            if found:
                return found
    elif isinstance(standings, list):
        for item in standings:
            found = _find_team_in_standings(item, team_id)
            if found:
                return found
    return {}
