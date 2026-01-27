# NFL Elo Dashboard (2024 Season)

Live demo: https://d2dlhuu2z9gv8p.cloudfront.net

## Overview
A small, scalable, production-style sports analytics project that shows the basics of a real full-stack workflow including:
- **Python 3** and **FastAPI** for two backend services (**Data API** + **Analytics API**)  
- **SQLite** for persistent storage of season games (`games` table)  
- A **batch Elo pipeline** (`analytics-api/compute_elo.py`) that writes a versioned artifact (`elo/elo_2024.json`)  
- **Jinja2** for static site generation (renders to `ui/dist/` at build time)  
- **JavaScript + Chart.js** for Elo trend charts (baseline + division rival overlays)  
- **Apache APISIX + etcd** (optional) to route both services behind a single entrypoint (`/api/*` and `/analytics/*`)  
- **Docker Compose** to run the full stack locally and on **AWS EC2** (data-api, analytics-api, APISIX, etcd)  
- **AWS S3 + CloudFront** to host and deliver the generated static site over HTTPS  

---

## Repo layout 

- `loader/` — ETL job that downloads/normalizes games and populates SQLite
- `loader/data/` — SQLite DB lives here (example: `nfl-season-2024.db`)
- `data-api/` — **FastAPI service** over SQLite (teams, games, computed summaries)
- `analytics-api/` — **FastAPI service** over the Elo artifact + recompute hook
- `elo/` — persisted Elo artifact (`elo_2024.json`) + helpers (ex: `division_rivals.json`)
- `ui/`
  - `templates/` — Jinja templates
  - `static/` — CSS, assets
  - `build/` — static site builder scripts (renders `ui/dist/`)
  - `dist/` — generated static site output (deploy this)

---

## What the site shows
- **Leaderboard** (latest week + per-week Elo rankings)
- **Team pages** (rank, current Elo, week-by-week breakdown, link to chart)
- **Elo trend charts** A Chart.js powered plot of the team's Elo ranking over time compared to division rivals

---

### Available Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Homepage (Leaderboard)** | `ui/dist/index.html` (deployed: https://d2dlhuu2z9gv8p.cloudfront.net) | Landing page + links into the Elo leaderboard and team pages. |
| **Weekly Leaderboard** | `ui/dist/leaderboard/week-<WEEK>.html` | Elo rankings for a specific week (week-by-week snapshots). |
| **Team Page** | `ui/dist/team/<TEAM>.html` | Team overview (current Elo, weekly breakdown, season context). |
| **Elo Trend Page** | `ui/dist/elo/<TEAM>.html` | Elo time-series chart (Chart.js) with baseline + division rival overlays. |

---

## Architecture

| Tier / Role                          | Module / Component                 | Port(s)                                     | Description |
|--------------------------------------|------------------------------------|---------------------------------------------|-------------|
| **Data Loader (ETL)**                | `loader/`                          | (pre-processing)                             | Downloads/normalizes NFL game data and writes it into a local SQLite database (ex: `loader/data/nfl-season-2024.db`, `games` table). Run before APIs if you need to build/refresh the DB. |
| **SQLite Database**                  | `loader/data/*.db`                 | (mounted into containers)                    | Stores the season data used by the backend at runtime (games, teams metadata as needed). |
| **Data API (FastAPI)**               | `data-api/data_api.py`             | 8000 (internal), 9080 `/api/*` (via gateway) | Serves clean endpoints over SQLite (teams, games, per-team summaries). This is the source layer the analytics pipeline reads from. |
| **Elo Batch Pipeline**               | `analytics-api/compute_elo.py`     | (batch job)                                  | Computes weekly Elo ratings from played games (pulled via Data API) and writes the persisted artifact `elo/elo_2024.json` (single source of truth for analytics + UI). |
| **Elo Artifact Store**               | `elo/elo_2024.json`                | (file)                                       | Precomputed Elo timeline for all teams and weeks. Read-only during normal operation. |
| **Analytics API (FastAPI)**          | `analytics-api/analytics_api.py`   | 8001 (internal), 9080 `/analytics/*` (via gateway) | Serves Elo data from `elo_2024.json` with fast read-only endpoints. Uses `API_BASE` to talk to the Data API when needed, and exposes a manual recompute hook (`POST /analytics/elo/recompute`). |
| **UI Static Site Generator (Jinja)** | `ui/build/build_site.py`           | (static files)                               | Builds the website at **build time** by pulling from the Analytics API (ex: `GET {ANALYTICS_API_BASE}/elo/all`) and rendering templates into `ui/dist/`. |
| **Static Site Output**               | `ui/dist/`                         | (static files)                               | Generated deployable site (leaderboards, team pages, charts, assets). Upload this folder to S3/CloudFront. |
| **API Gateway (optional)**           | APISIX + etcd (`conf/`, docker)    | 9080 (public), 9180 (admin)                  | Single entrypoint that routes `/api/*` → Data API and `/analytics/*` → Analytics API so the stack has stable prefixes behind one port. |

---


## Local dev: run the full backend stack
### 0) Prerequisites 
* Install [Docker Desktop](https://www.docker.com/products/docker-desktop)
* Have a Python-compatible local IDE

### 1) Clone this repository
```bash
git clone https://github.com/charles633-wcu/nfl-team-compare.git
cd nfl-team-compare
```

### 2) Start the stack
```bash
docker compose up --build
```

### Access the APIs

> If you’re running the Docker stack with APISIX, **use the gateway** as the single entrypoint:  
> - Data API: `http://localhost:9080/api/*`  
> - Analytics API: `http://localhost:9080/analytics/*`

| Service             | Example Endpoint                                                            | Description |
|--------------------|-----------------------------------------------------------------------------|-------------|
| **Data API**        | `http://localhost:9080/api/health`                                          | Health check for the Data API. |
|                    | `http://localhost:9080/api/teams`                                           | Returns all teams available for the selected season. |
|                    | `http://localhost:9080/api/games?season=2024&week=1`                        | Returns all games for a given season + week (regular season only). |
|                    | `http://localhost:9080/api/teams/Philadelphia%20Eagles/summary?season=2024` | Returns computed season totals for a team (PF/PA/PD and related summary stats). |
| **Analytics API**   | `http://localhost:9080/analytics/health`                                    | Health check for the Analytics API (includes configured `api_base` + Elo artifact path). |
|                    | `http://localhost:9080/analytics/elo/all`                                   | Returns the full Elo artifact (all teams, all weeks). |
|                    | `http://localhost:9080/analytics/elo/1`                                     | Returns Elo leaderboard snapshot for a given week. |
|                    | `http://localhost:9080/analytics/teams/Philadelphia%20Eagles/elo`           | Returns a team’s Elo time series across the season. |
|                    | `http://localhost:9080/analytics/elo/recompute`                             | **POST**: recomputes Elo and rewrites the artifact JSON (explicit refresh hook). |

> Note on `API_BASE` (how analytics-api talks to data-api):
> - When running with Docker Compose, analytics-api usually talks to data-api over the Docker network using the service name:
>   `API_BASE=http://data-api:8000`
> - If you’re using the gateway as the *public* entrypoint, you’ll access endpoints at:
>   `http://localhost:9080/api/*` and `http://localhost:9080/analytics/*`

Build the static site (UI)
The UI is generated from the Analytics API at build time, then served as pure static files.

### Generate the static site
From repo root (Windows Powershell):

```
cd ui
$env:ANALYTICS_API_BASE="http://localhost:9080/analytics"
py .\build\build_site.py
```

Output is written to:

**nfl-team-compare/ui/dist/index.html**


## Tech stack

**Backend**
- Python (FastAPI, Pydantic)
- SQLite

**Infra / Deployment**
- Docker + Docker Compose
- AWS EC2 (backend hosting)
- AWS S3 (static site hosting)
- AWS CloudFront (CDN / HTTPS delivery)

**Gateway**
- APISIX + etcd (routing `/api/*` and `/analytics/*`)

**Frontend**
- Jinja2 (static site generation)
- HTML/CSS
- JavaScript (Chart.js)

## Deployment (AWS)

- **Backend (EC2):** The full Docker Compose stack runs on an EC2 instance (Data API + Analytics API + optional APISIX gateway). APISIX exposes stable prefixes like `/api/*` and `/analytics/*` from a single public port.
- **Static site (S3):** The generated site in `ui/dist/` is uploaded to an S3 bucket as static files.
- **Delivery (CloudFront):** CloudFront sits in front of the S3 bucket to provide HTTPS + CDN caching. The default root object is `index.html`.



