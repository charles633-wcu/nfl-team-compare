# NFL Elo Analytics Platform (2024 + 2025 Seasons)

Live demo: https://nflelodashboard.com/

## Overview

This project is a full-stack analytics tool covering recent NFL seasons. It takes and stores in game data, exposes it through an API which allows computation of Elo ratings (based weekly) through a separate analytics pipeline, and generates a website to visualize the analytics. It is hosted on AWS.

The project demonstrates the full path from data ingestion to analytics modeling and finally to production-style delivery:

- **ETL pipeline** that normalizes NFL game data into a single master SQLite database keyed by season.
- **Data API** built with FastAPI over the game database, with a season selector.
- **Analytics API** built with FastAPI that computes various analytics figures.
- **Batch Elo engine** with home-field advantage, margin-of-victory scaling, OLS margin prediction, and per-game Elo history.
- **Multi-season frontend**: a season picker at the root plus a complete, self-contained site for each season.
- **Matchup simulator** to compare any two teams at any week of a given season.
- **Playoff bracket simulator** using real playoff seed rules, game probabilities using ELO based score simulation, which updates itself round-by-round.
- **Trend Pages** comparing each team against division rivals.
- **Docker Compose + APISIX** for local multi-service orchestration.
- **AWS** using EC2 for APIs and S3/CloudFront for the static site.

### Runtime architecture: the deployed site is static only

TO save on costs, the APIs are used locally in the generation of websites, but are not live on an EC2. The APIs are a build-time and local-development concern. `build_site.py` calls the Analytics API during the build and bakes the results directly into the HTML as inline JavaScript constants, so the browser makes zero runtime requests. S3 and CloudFront serve website files.


---

## Repo Layout

- `loader/` - ETL job that normalizes NFL game data into the master database.
- `loader/data/nfl-games.db` - master games database (gitignored): one `games` table with a `season` column, primary key `(season, match_number)`, index `(season, week)`. Regular season only (weeks 1-18), enforced at load time.
- `data-api/` - FastAPI service over SQLite for teams, games, and team summaries.
- `analytics-api/` - FastAPI service over Elo artifacts, plus recompute/meta endpoints.
- `analytics-api/compute_elo.py` - batch Elo computation and artifact persistence.
- `elo/` - generated per-season Elo JSON artifacts (`elo_2024.json`, `elo_2025.json`) and division rival mapping.
- `playoff_score_logic.py` - shared playoff score simulation helpers used by tests and validation.
- `simulate_bracket.py` - Monte Carlo playoff simulation script.
- `ui/build/` - Jinja2 static site build pipeline.
- `ui/templates/` - site templates for home, leaderboard, teams, charts, matchup, about, and contact pages.
- `ui/static/` - CSS, JavaScript, logos, and homepage imagery.
- `ui/dist/` - generated static site output. This is deployable output, not source.
- `tests/` - smoke and compatibility tests for the builder, simulator, score logic, and API wiring.
- `conf/` - APISIX gateway configuration.
- `docker-compose.yml` - local orchestration for Data API, Analytics API, APISIX, etcd, and route init.
- `ARTIFACT_SCHEMA.md` - schema notes for the Elo artifacts.

---

## Multi-Season Structure

The site is built as a root **season picker** plus a complete, self-contained site for each season:

```text
ui/dist/
├── index.html        <- season picker (rendered from templates/home_intro.html)
├── static/           <- CSS, JS, logos, imagery
├── 2025/             <- full site for the 2025 season
└── 2024/             <- full site for the 2024 season
```


### Updating an in-progress season

A season that is still being played (2026) is refreshed with one command from the repo root:

```bash
python update_season.py 2026 --dry-run   # show what would change; write nothing
python update_season.py 2026             # update the CSV and rebuild the site
```

It downloads the fixturedownload feed, keeps only **complete** weeks (every scheduled game scored), compares the result with `loader/data/nfl-season-2026.csv`, then runs the whole pipeline (loader, Data API, `compute_elo.py`, Analytics API, `build_site.py`) on real local servers using free ports. The servers are always shut down. Nothing is deployed to S3.

| Situation | What happens | Exit code |
|---|---|---|
| New complete week(s) | CSV saved, Elo recomputed, site rebuilt, top 5 printed | 0 |
| Nothing new | "Already up to date through Week N", no rebuild | 0 |
| A final score changed, a score vanished, or a game was added/removed/changed | Lists the changes, saves nothing; rerun with `--accept-changes` if they are real corrections | 1 |
| Malformed feed (unknown team, bad score, empty or non-JSON feed) | Refused, even with `--accept-changes` | 2 |
| Feed unreachable | Suggests retrying or `--from-file saved-feed.json` | 2 |
| A server, Elo or the build fails | Previous CSV restored, `ui/dist` untouched, log tail printed | 2 |

A postponed game holds the site at the previous week, and the report names the game. The new site is built in a staging folder and swapped into `ui/dist` only on success. A preview server started from *inside* `ui/dist` blocks that swap on Windows, so serve with `--directory` (below).

---

## What is on the site

- **Season Picker** - root landing page; choose a season and enter its site.
- **Season Homepage** - per-season landing page with summary cards, feature previews, and links into that season.
- **Weekly Leaderboards** - week-by-week Elo rankings from Week 0 through Week 18.
- **Team Directory** - all teams with links to profile and trend chart pages.
- **Team Profiles** - rank, final Elo, week-by-week games, predicted margin, Elo delta, and post-game Elo.
- **Elo Trend Charts** - Chart.js line charts with the focus team, division rivals, and league baseline.
- **Matchup Simulator** - choose any two teams and any week, then view win probability, Elo edge, predicted margin, recent form, head-to-head history, and a simulated score.
- **Playoff Bracket Simulator** - run that season's playoff bracket round by round using real seeds, Elo probabilities, home-field advantage, simulated final scores, and Elo updates after each game.
- **Methodology Page** - formulas and modeling notes for Elo, HFA, margin-of-victory scaling, OLS margin prediction, score simulation, and Monte Carlo validation.


---

## Architecture

| Tier / Role | Module / Component | Port(s) | Description |
|-------------|--------------------|---------|-------------|
| Data Loader | `loader/loader.py` | pre-processing | Normalizes NFL fixtures/results into the master `games` table, tagged by season. |
| SQLite Data Store | `loader/data/nfl-games.db` | file | Master game database, keyed `(season, match_number)`. Mounted into the Data API container. |
| Data API | `data-api/data_api.py` | 8000 internal, 9080 `/api/*` via APISIX | Serves teams, games, and team summaries over SQLite, filtered by `season`. |
| Elo Batch Pipeline | `analytics-api/compute_elo.py` | batch job | Computes weekly Elo ratings, per-game Elo records, OLS margin model, season score model, and persisted artifacts for one season per run. |
| Elo Artifact Store | `elo/elo_<SEASON>.json` | file | Per-season JSON artifact consumed by the Analytics API and static site builder. |
| Analytics API | `analytics-api/analytics_api.py` | 8001 internal, 9080 `/analytics/*` via APISIX | Serves Elo data, metadata, team timelines, and a manual recompute hook, per season. |
| UI Static Builder | `ui/build/build_site.py` | build time | Pulls analytics data for every season in `BUILD_SEASONS` and renders all HTML pages into `ui/dist/`. |
| Static Site | `ui/dist/` | static files | Deployable output for S3/CloudFront or local static serving. |
| Gateway | APISIX + etcd | 9080 public, 9180 admin | Routes `/api/*` to Data API and `/analytics/*` to Analytics API. |


### Flow of data

```text
Fixture feed / CSV
  -> loader/loader.py
  -> master SQLite games table (season, match_number)
  -> data-api FastAPI service            (?season=)
  -> analytics-api/compute_elo.py        (ELO_SEASON)
  -> elo/elo_<SEASON>.json + Elo SQLite artifact
  -> analytics-api read endpoints        (?season=)
  -> ui/build/build_site.py              (BUILD_SEASONS)
  -> ui/dist multi-season static website
  -> S3 + CloudFront
```

The static site embeds the data needed for the interactive tools at build time. For example, each season's `matchup.html` receives weekly Elo snapshots, team game histories, margin model parameters, score-simulation parameters, playoff seeds, and the K-factor as inline JSON. That lets the browser run the simulator with no runtime API calls.

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
total  ~ Normal(season_average_combined_score, 10)
```

The total-points mean is stored in each season's `score_model` and is computed from that season's regular-season games.

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

The playoff bracket starts from that season's real playoff seeds, registered in `SEASON_PLAYOFFS`.

**2024** (champion: Philadelphia Eagles):

- AFC: Chiefs, Bills, Ravens, Texans, Chargers, Steelers, Broncos.
- NFC: Lions, Eagles, Rams, Buccaneers, Commanders, Vikings, Packers.

**2025** (champion: Seattle Seahawks):

- AFC: Broncos, Patriots, Jaguars, Steelers, Texans, Bills, Chargers.
- NFC: Seahawks, Eagles, Bears, Panthers, Rams, Packers, 49ers.

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

If `loader/data/nfl-games.db` is already present, you can skip this step. To rebuild it:

```bash
py loader/loader.py
```

This builds the master `games` table for every configured season. Only regular-season games (weeks 1-18) are written — postseason is excluded at load time, so the database is self-describing and the API filters on `season` rather than a date cutoff.

### Compute Elo

Elo is computed one season per run, selected by `ELO_SEASON`:

```bash
ELO_SEASON=2025 py analytics-api/compute_elo.py
```

In Windows PowerShell, set the variable separately:

```powershell
$env:ELO_SEASON="2025"; py analytics-api/compute_elo.py
```

This writes `elo/elo_2025.json` and updates the season-keyed Elo SQLite artifact.

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

If you are not running the Docker stack, point the builder at a directly-run Analytics API instead:

```bash
ELO_DIR="$PWD/elo" py -m uvicorn analytics_api:app --host 127.0.0.1 --port 8001 --app-dir analytics-api
ANALYTICS_API_BASE="http://127.0.0.1:8001" py ui/build/build_site.py
```

Output is written to:

```text
ui/dist/index.html          <- season picker
ui/dist/<SEASON>/index.html <- per-season site
```

For each season in `BUILD_SEASONS`, the build generates:

- season homepage
- about/contact pages
- matchup simulator
- team directory
- 32 team profile pages
- 32 Elo trend chart pages
- weekly leaderboard pages for Week 0 through Week 18
- copied static assets

plus the root season picker and a root copy of the static assets.

### Build Output Location and Worktrees

`resolve_dist_dir()` writes to `ui/dist/` in the main repository. When the builder is run from inside a git worktree it deliberately still targets the **main** repo's `ui/dist/`. To build somewhere else — a preview directory, for example — set `UI_DIST_DIR`:

```bash
UI_DIST_DIR=/tmp/preview-dist py ui/build/build_site.py
```

### Preview the Static Site Locally

Serve from the generated output folder. **Do not open `ui/dist/index.html` directly as a `file://` URL** — the season picker references `/static/css/app.css` with an absolute path, which resolves against the filesystem root under `file://` and renders the page unstyled. Over HTTP from the dist root it is correct, which is also how S3/CloudFront serves it.

Option 1: use the included Node static server:

```bash
node ui/serve-dist.mjs
```

Option 2: use Python's built-in server from the repo root:

```bash
py -m http.server 8080 --directory ui/dist
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

The suite currently reports **29 passed**.

Useful targeted runs:

```bash
py -m pytest tests/test_playoff_score_logic.py
py -m pytest tests/test_build_matchup.py
py -m pytest tests/test_ui_build.py
py -m pytest tests/test_homepage_build.py
py -m pytest tests/test_api_compat.py
py -m pytest tests/test_loader_master_db.py
py -m pytest tests/test_data_api_season.py
py -m pytest tests/test_compute_elo_season.py
py -m pytest tests/test_analytics_api_season.py
```

The tests check things like:

- playoff scores never produce impossible NFL scores or ties
- matchup page receives valid embedded simulation helpers
- generated site has the multi-season shape: root picker plus `dist/<season>/` subtrees
- generated site contains core routes and UI markers
- builder works across direct service and APISIX gateway setups
- worktree builds resolve output paths correctly
- master DB schema and season ingest are correct, and seasons are disjoint
- both APIs honor `?season=` and default to the latest season
- score simulation parameters are season-specific and reach the rendered matchup page
- **2024 Elo output still matches the committed baseline exactly** (regression guard)

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

After building the UI, upload the **contents** of `ui/dist/` to the S3 bucket root — not the `ui/dist` folder itself. Step-by-step instructions, including the exact target bucket layout and upload order, are in [`DEPLOY_S3.txt`](DEPLOY_S3.txt).

```bash
aws s3 sync ui/dist s3://YOUR-BUCKET --delete --dryrun   # review first
aws s3 sync ui/dist s3://YOUR-BUCKET --delete            # then execute
aws cloudfront create-invalidation --distribution-id YOUR-DIST-ID --paths "/*"
```

### CloudFront

CloudFront sits in front of the S3 bucket for HTTPS and CDN caching. The default root object is `index.html`.

---

## Future Improvements

Possible improvements include: 

- **Backtest/evaluation harness** — Brier score and log-loss for the model against de-vigged closing lines, plus a calibration curve. Measuring the model honestly matters more than squeezing out raw accuracy.
- Multi-season Elo carry-forward instead of resetting all teams to 1500.
- Recent-form weighting so late-season performance matters more near playoff time.
- QB adjustment using starter data and replacement-level estimates.
- CI workflow for tests and static build verification.
- Shareable playoff bracket states through URL encoding.
- Automated scheduled data refresh and Elo recompute.
- Reconcile the two home-field-advantage values (+55 regular season vs +65 playoffs) and fit HFA empirically rather than using the inherited default.
- Make the season picker's asset paths relative so the site also works under `file://` and non-root deploy prefixes.
