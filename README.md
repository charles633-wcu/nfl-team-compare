# NFL Elo Analytics Platform (2024 Season)

Live demo: https://d2dlhuu2z9gv8p.cloudfront.net

## Overview

This project is a full-stack NFL analytics platform for the 2024 season. It ingests game data, stores it in SQLite, exposes raw data through a FastAPI service, computes weekly Elo ratings through a separate analytics pipeline, and generates a static website that can be deployed to S3 and CloudFront.

The project is designed to show the full path from data ingestion to analytics modeling to production-style delivery:

- **ETL pipeline** that downloads and normalizes 2024 NFL game data into SQLite.
- **Data API** built with FastAPI over the game database.
- **Analytics API** built with FastAPI over computed Elo artifacts.
- **Batch Elo engine** with home-field advantage, margin-of-victory scaling, OLS margin prediction, and per-game Elo history.
- **Interactive static frontend** generated with Jinja2 and powered by embedded analytics data.
- **Matchup simulator** for any two teams at any week of the season.
- **Playoff bracket simulator** using 2024 playoff seeds, Elo probabilities, score simulation, and round-by-round Elo updates.
- **Chart.js trend pages** comparing each team against division rivals.
- **Docker Compose + APISIX** for local multi-service orchestration.
- **AWS deployment path** using EC2 for APIs and S3/CloudFront for the static site.

## Why This Project Matters

This is not a CRUD app with a chart on top. The core engineering work is the separation of concerns:

1. Raw NFL game data is loaded and stored once.
2. A data service exposes normalized game records.
3. A batch analytics service computes reusable Elo artifacts.
4. A static site generator turns those artifacts into a deployable web experience.
5. The browser runs interactive simulations without needing a live backend at runtime.

That architecture lets the site behave like an interactive analytics product while still being cheap and simple to host as static files.

---

## Repo Layout

- `loader/` - ETL job that downloads and normalizes NFL game data.
- `loader/data/` - local SQLite database location, for example `nfl-season-2024.db`.
- `data-api/` - FastAPI service over SQLite for teams, games, and team summaries.
- `analytics-api/` - FastAPI service over Elo artifacts, plus recompute/meta endpoints.
- `analytics-api/compute_elo.py` - batch Elo computation and artifact persistence.
- `elo/` - generated Elo JSON artifact and division rival mapping.
- `playoff_score_logic.py` - shared playoff score simulation helpers used by tests and validation.
- `simulate_bracket.py` - Monte Carlo playoff simulation script.
- `ui/build/` - Jinja2 static site build pipeline.
- `ui/templates/` - site templates for home, leaderboard, teams, charts, matchup, about, and contact pages.
- `ui/static/` - CSS, JavaScript, logos, and homepage imagery.
- `ui/dist/` - generated static site output. This is deployable output, not source.
- `tests/` - smoke and compatibility tests for the builder, simulator, score logic, and API wiring.
- `conf/` - APISIX gateway configuration.
- `docker-compose.yml` - local orchestration for Data API, Analytics API, APISIX, etcd, and route init.
- `ARTIFACT_SCHEMA.md` - schema notes for `elo/elo_2024.json`.

---

## What the Site Shows

- **Homepage** - landing page with season summary cards, feature previews, and links into the product.
- **Weekly Leaderboards** - week-by-week Elo rankings from Week 0 through Week 18.
- **Team Directory** - all teams with links to profile and trend chart pages.
- **Team Profiles** - rank, final Elo, week-by-week games, predicted margin, Elo delta, and post-game Elo.
- **Elo Trend Charts** - Chart.js line charts with the focus team, division rivals, and league baseline.
- **Matchup Simulator** - choose any two teams and any week, then view win probability, Elo edge, predicted margin, recent form, head-to-head history, and a simulated score.
- **Playoff Bracket Simulator** - run the 2024 playoff bracket round by round using real seeds, Elo probabilities, home-field advantage, simulated final scores, and Elo updates after each game.
- **Methodology Page** - formulas and modeling notes for Elo, HFA, margin-of-victory scaling, OLS margin prediction, score simulation, and Monte Carlo validation.

---

## Available Pages

| Page | Local/generated path | Purpose |
|------|----------------------|---------|
| Homepage | `ui/dist/index.html` | Product landing page and feature hub. |
| Weekly Leaderboard | `ui/dist/leaderboard/week-<WEEK>.html` | Elo rankings for a specific week. |
| Team Directory | `ui/dist/teams/index.html` | Browse every team and jump to profile or chart views. |
| Team Profile | `ui/dist/team/<TEAM>.html` | Team overview, weekly game history, Elo movement, and predicted margins. |
| Elo Trend Page | `ui/dist/elo/<TEAM>.html` | Chart.js Elo trend with division rival overlays. |
| Matchup Simulator | `ui/dist/matchup.html` | Head-to-head team comparison and playoff bracket simulator. |
| About / Methodology | `ui/dist/about.html` | Project explanation, architecture, and formulas. |
| Contact | `ui/dist/contact.html` | Source code, GitHub, LinkedIn, and email links. |

---

## Architecture

| Tier / Role | Module / Component | Port(s) | Description |
|-------------|--------------------|---------|-------------|
| Data Loader | `loader/loader.py` | pre-processing | Downloads 2024 NFL fixtures/results and writes a normalized `games` table to SQLite. |
| SQLite Data Store | `loader/data/*.db` | file | Runtime game database mounted into the Data API container. |
| Data API | `data-api/data_api.py` | 8000 internal, 9080 `/api/*` via APISIX | Serves teams, games, and team summaries over SQLite. |
| Elo Batch Pipeline | `analytics-api/compute_elo.py` | batch job | Computes weekly Elo ratings, per-game Elo records, OLS margin model, and persisted artifacts. |
| Elo Artifact Store | `elo/elo_2024.json` | file | JSON artifact consumed by the Analytics API and static site builder. |
| Analytics API | `analytics-api/analytics_api.py` | 8001 internal, 9080 `/analytics/*` via APISIX | Serves Elo data, metadata, team timelines, and a manual recompute hook. |
| UI Static Builder | `ui/build/build_site.py` | build time | Pulls analytics data and renders all HTML pages into `ui/dist/`. |
| Static Site | `ui/dist/` | static files | Deployable output for S3/CloudFront or local static serving. |
| Gateway | APISIX + etcd | 9080 public, 9180 admin | Routes `/api/*` to Data API and `/analytics/*` to Analytics API. |

### Data Flow

```text
Fixture feed
  -> loader/loader.py
  -> SQLite games table
  -> data-api FastAPI service
  -> analytics-api/compute_elo.py
  -> elo/elo_2024.json + optional Elo SQLite artifact
  -> analytics-api read endpoints
  -> ui/build/build_site.py
  -> ui/dist static website
  -> S3 + CloudFront
```

The static site embeds the data needed for the interactive tools at build time. For example, `matchup.html` receives weekly Elo snapshots, team game histories, margin model parameters, playoff seeds, and the K-factor as inline JSON. That lets the browser run the simulator with no runtime API calls.

---

## Analytics Methodology

### Elo Win Probability

The project uses the standard Elo expected score formula:

```text
E_A = 1 / (1 + 10^((R_B - R_A) / 400))
```

Where:

- `R_A` is Team A's Elo.
- `R_B` is Team B's Elo.
- `E_A` is Team A's expected win probability.

### Home-Field Advantage

Home-field advantage is applied as a temporary Elo boost before computing expected score. It is not stored in the team's rating.

```text
E_home = 1 / (1 + 10^((R_away - (R_home + HFA)) / 400))
```

This project uses context-specific values:

- `+55 Elo` during regular-season Elo computation in `analytics-api/compute_elo.py`.
- `+65 Elo` during playoff bracket simulation for non-neutral playoff games.
- `0 Elo` for the Super Bowl because it is a neutral-site game.

### Elo Update Rule

After each game, the home team's Elo change is:

```text
Delta_home = K * M * (S_home - E_home)
```

Where:

- `K = 25`
- `S_home` is actual result: win `1`, tie `0.5`, loss `0`
- `E_home` is expected score from the Elo formula
- `M` is the margin-of-victory multiplier

The away team receives the opposite change:

```text
Delta_away = -Delta_home
```

### Margin-of-Victory Multiplier

The model uses a FiveThirtyEight-style NFL margin-of-victory adjustment:

```text
M = ln(|PD| + 1) * 2.2 / (0.001 * (ELO_W - ELO_L) + 2.2)
```

Where:

- `PD` is point differential.
- `ELO_W` is the winner's pregame Elo.
- `ELO_L` is the loser's pregame Elo.

This makes blowouts worth more than narrow wins while dampening rating inflation when a strong favorite wins big.

### OLS Margin Model

After computing regular-season Elo ratings, the analytics pipeline fits a simple ordinary least squares model:

```text
predicted_margin = alpha + beta * (ELO_A - ELO_B)
```

The generated artifact stores the fitted model in `margin_model`. The UI uses it to show expected margins and to drive simulated scores.

### Score Simulation

The matchup and playoff tools simulate final scores by sampling margin and total points:

```text
margin ~ Normal(predicted_margin, 13.45)
total  ~ Normal(43.5, 10)
```

Then scores are derived from:

```text
winner_score = round((total + |margin|) / 2)
loser_score  = total - winner_score
```

The JavaScript simulator uses the Box-Muller transform to generate normally distributed samples:

```text
Z = sqrt(-2 * ln(u1)) * cos(2 * pi * u2)
```

Where `u1` and `u2` are uniform random values from `Math.random()`.

### Playoff Simulation

The playoff bracket starts from the real 2024 playoff seeds:

- AFC: Chiefs, Bills, Ravens, Texans, Chargers, Steelers, Broncos.
- NFC: Lions, Eagles, Rams, Buccaneers, Commanders, Vikings, Packers.

The bracket follows NFL reseeding rules:

- Top seed gets a bye.
- Wild Card matchups are `2 vs 7`, `3 vs 6`, and `4 vs 5`.
- After each round, the highest remaining seed plays the lowest remaining seed.
- Higher seed gets home-field advantage except in the Super Bowl.
- Winner and loser Elo ratings update after each simulated game.

The repository also includes `simulate_bracket.py`, which runs 100,000 Monte Carlo brackets for validation and comparison against historical seed expectations.

---

## Local Dev: Run the Full Backend Stack

### 0. Prerequisites

- Docker Desktop
- Python 3.11+
- PowerShell on Windows, or an equivalent shell
- Optional: Node.js if you want to use `ui/serve-dist.mjs` for local static serving

### 1. Clone This Repository

```bash
git clone https://github.com/charles633-wcu/nfl-team-compare.git
cd nfl-team-compare
```

### 2. Install Python Dependencies

```bash
py -m pip install -r requirements.txt
```

On macOS/Linux, use `python` or `python3` instead of `py` if needed.

If you plan to run the test suite, install `pytest` as well:

```bash
py -m pip install pytest
```

### 3. Prepare the SQLite Data

If `loader/data/nfl-season-2024.db` is already present, you can skip this step. To rebuild it:

```bash
py loader/loader.py
```

This downloads the 2024 NFL fixture feed and writes the normalized `games` table.

### 4. Start the Docker Stack

```bash
docker compose up --build
```

The stack starts:

- `data-api`
- `analytics-api`
- `etcd`
- `apisix`
- route initialization
- Elo recompute initialization

### 5. Access the APIs

When running with APISIX, use the gateway as the single entrypoint:

- Data API: `http://localhost:9080/api/*`
- Analytics API: `http://localhost:9080/analytics/*`

| Service | Example Endpoint | Description |
|---------|------------------|-------------|
| Data API | `http://localhost:9080/api/health` | Health check for the Data API. |
| Data API | `http://localhost:9080/api/teams` | Returns all teams in the selected season. |
| Data API | `http://localhost:9080/api/games?week=1` | Returns regular-season games for Week 1. |
| Data API | `http://localhost:9080/api/games?played=true&limit=5000` | Returns all played regular-season games used by Elo. |
| Data API | `http://localhost:9080/api/teams/Philadelphia%20Eagles/summary` | Returns points for, points against, games played, and point differential. |
| Analytics API | `http://localhost:9080/analytics/health` | Health check with Elo config details. |
| Analytics API | `http://localhost:9080/analytics/elo/meta?sha256=true` | Metadata for the Elo artifact, optionally including SHA-256. |
| Analytics API | `http://localhost:9080/analytics/elo/all` | Full Elo artifact. |
| Analytics API | `http://localhost:9080/analytics/elo/18` | Week 18 Elo leaderboard snapshot. |
| Analytics API | `http://localhost:9080/analytics/teams/Philadelphia%20Eagles/elo` | Team Elo timeline and per-game records. |
| Analytics API | `POST http://localhost:9080/analytics/elo/recompute` | Recomputes Elo and rewrites the artifact. |

### API Base Notes

The analytics service supports both current and older local environment names:

- `ELO_API_BASE=http://data-api:8000` in Docker Compose.
- `API_BASE=http://localhost:9080/api` for legacy/direct compatibility.

The UI builder also searches for reachable analytics endpoints, preferring the APISIX gateway when available.

---

## Build the Static Site

The website is generated at build time from the Analytics API and written to `ui/dist/`.

Run the backend stack first so the Analytics API is reachable.

From repo root in Windows PowerShell:

```powershell
cd ui
$env:ANALYTICS_API_BASE="http://localhost:9080/analytics"
py .\build\build_site.py
```

Output is written to:

```text
ui/dist/index.html
```

The build generates:

- homepage
- about/contact pages
- matchup simulator
- team directory
- 32 team profile pages
- 32 Elo trend chart pages
- weekly leaderboard pages for Week 0 through Week 18
- copied static assets

### Preview the Static Site Locally

Option 1: use the included Node static server:

```bash
node ui/serve-dist.mjs
```

Then open:

```text
http://127.0.0.1:8080/
```

Option 2: use Python from the generated output folder:

```bash
cd ui/dist
py -m http.server 8080
```

Then open:

```text
http://127.0.0.1:8080/
```

---

## Testing

The repository includes tests for the static builder, matchup page rendering, score validity, API wiring, and homepage output.

Run the full test suite:

```bash
py -m pytest
```

Useful targeted runs:

```bash
py -m pytest tests/test_playoff_score_logic.py
py -m pytest tests/test_build_matchup.py
py -m pytest tests/test_ui_build.py
py -m pytest tests/test_homepage_build.py
py -m pytest tests/test_api_compat.py
```

The tests check things like:

- playoff scores never produce impossible NFL scores or ties
- matchup page receives valid embedded simulation helpers
- generated homepage contains the new landing-page structure
- generated site contains core routes and UI markers
- builder works across direct service and APISIX gateway setups
- worktree builds resolve output paths correctly

---

## Tech Stack

### Backend

- Python 3.11
- FastAPI
- Pydantic
- Uvicorn
- SQLite
- Requests

### Analytics

- Elo rating model
- Home-field advantage adjustment
- Margin-of-victory multiplier
- OLS margin prediction
- Monte Carlo playoff simulation
- JSON and SQLite artifact persistence

### Frontend

- Jinja2 static site generation
- HTML/CSS
- Vanilla JavaScript
- Chart.js
- MathJax on the methodology page
- Embedded JSON for static interactive tools

### Infrastructure

- Docker
- Docker Compose
- APISIX
- etcd
- AWS EC2
- AWS S3
- AWS CloudFront

---

## Deployment

### Backend on EC2

The Docker Compose stack can run on an EC2 instance:

- Data API reads the SQLite game database.
- Analytics API reads and recomputes Elo artifacts.
- APISIX exposes stable `/api/*` and `/analytics/*` prefixes from one gateway port.

### Static Site on S3

After building the UI, upload `ui/dist/` to an S3 bucket configured for static hosting.

### CloudFront

CloudFront sits in front of the S3 bucket for HTTPS and CDN caching. The default root object is `index.html`.

This split keeps the public website static and cheap to serve while the backend remains available for rebuilds, recomputes, and API inspection.

---

## Interview Talking Points

If you are reviewing this project, the strongest engineering pieces are:

- **Multi-service design:** raw data access and derived analytics are separate FastAPI services.
- **Batch analytics pipeline:** Elo is computed once into reusable artifacts instead of recalculated ad hoc in the UI.
- **Static interactive architecture:** the browser can simulate matchups and playoff brackets because data is embedded at build time.
- **Model transparency:** the equations for Elo, HFA, MOV, OLS margin prediction, and score simulation are documented and visible in code.
- **Deployment realism:** Docker/APISIX supports local and EC2 backend deployment, while S3/CloudFront serves the static frontend.
- **Testing:** tests cover builder behavior, compatibility wiring, matchup rendering, and score validity.

Good questions to ask about the project:

- Why split the Data API and Analytics API?
- Why use static site generation instead of a live frontend app?
- How does home-field advantage affect Elo without polluting team ratings?
- How does the margin-of-victory multiplier avoid over-rewarding favorites?
- Why use Box-Muller for score simulation?
- What would change if this supported multiple seasons or QB-adjusted Elo?

---

## Future Improvements

The next improvements that would add the most value:

- Multi-season Elo carry-forward instead of resetting all teams to 1500.
- Recent-form weighting so late-season performance matters more near playoff time.
- QB adjustment using starter data and replacement-level estimates.
- CI workflow for tests and static build verification.
- Shareable playoff bracket states through URL encoding.
- Automated scheduled data refresh and Elo recompute.
