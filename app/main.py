from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api_sports import APISportsClient, APISportsError
from app.settings import settings
from fastapi.staticfiles import StaticFiles


#uvicorn app.main:app --reload

app = FastAPI(title="NFL Regular Season Comparisons", version="0.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


templates = Jinja2Templates(directory="app/templates")
client = APISportsClient()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        teams = await client.list_teams(settings.nfl_league_id, settings.season)
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "teams": teams, "season": settings.season, "error": None},
        )
    except APISportsError as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "teams": [], "season": settings.season, "error": str(e)},
        )


@app.get("/compare", response_class=HTMLResponse)
async def compare(request: Request, team_a: int, team_b: int):
    try:
        a = await client.get_standings_stats(settings.nfl_league_id, settings.season, team_a)
        b = await client.get_standings_stats(settings.nfl_league_id, settings.season, team_b)

        # Basic “keys to the matchup” text (rule-based, quick and portfolio-friendly)
        summary = []
        if a.wins is not None and b.wins is not None:
            if a.wins > b.wins:
                summary.append(f"{a.team.name} had a stronger record in {settings.season}.")
            elif b.wins > a.wins:
                summary.append(f"{b.team.name} had a stronger record in {settings.season}.")
            else:
                summary.append("These teams had similar records this season.")

        return templates.TemplateResponse(
            "compare.html",
            {"request": request, "a": a, "b": b, "season": settings.season, "summary": summary, "error": None},
        )
    except APISportsError as e:
        return templates.TemplateResponse(
            "compare.html",
            {"request": request, "a": None, "b": None, "season": settings.season, "summary": [], "error": str(e)},
        )


@app.get("/health")
async def health():
    return {"ok": True, "season": settings.season}


from fastapi.responses import JSONResponse

@app.get("/debug/teams")
async def debug_teams():
    data = await client._get("/teams", params={"league": settings.nfl_league_id, "season": settings.season})
    return JSONResponse(content=data)

@app.get("/debug/leagues")
async def debug_leagues():
    data = await client._get("/leagues")
    return JSONResponse(content=data)

from fastapi.responses import JSONResponse

@app.get("/debug/games")
async def debug_games(team_id: int):
    data = await client._get(
        "/games",
        params={
            "league": settings.nfl_league_id,
            "season": settings.season,
            "team": team_id,
        },
    )

    # Return only the first 2 games so it's readable
    games = data.get("response", [])
    return JSONResponse(content=games[:2])


from fastapi.responses import JSONResponse

@app.get("/debug/games_raw")
async def debug_games_raw(team_id: int):
    data = await client._get(
        "/games",
        params={"league": settings.nfl_league_id, "season": settings.season, "team": team_id, "page": 1},
    )
    return JSONResponse(content=data)
