# Spec — MATCH-UP Simulator Page

**Date:** 2026-04-23
**Status:** Approved, pending implementation
**Author:** Claude (claude-sonnet-4-6)

---

## Overview

A new `/matchup.html` page with two tab-based sections: a general Matchup Simulator and a Playoff Bracket Simulator. All data is embedded at build time; all logic runs client-side. No runtime server or database required — the page deploys as a static file to S3.

This feature repositions the project from a read-only analytics dashboard to an interactive analytics platform with forecasting and simulation.

---

## Architecture

### Deployment

Fully static. `build_site.py` generates `ui/dist/matchup.html`. The page is self-contained — no API calls at runtime.

### Data embedded at build time

All data originates from the existing `elo_all` artifact fetched once in `build_site.py`.

| Variable | Source | Approx size |
|---|---|---|
| `weekly_elos` | `elo_all["elo"]` | ~5 KB |
| `games_by_team` | `elo_all["teams"]` | ~80–100 KB |
| `margin_model` | `elo_all["margin_model"]` | 2 numbers |
| `playoff_seeds` | Hardcoded constant in `build_site.py` | <1 KB |

### In-browser JS engine

No framework. Four pure functions plus a bracket state machine:

- `computeWinProb(eloA, eloB)` — `1 / (1 + 10^((eloB - eloA) / 400))`
- `computeMargin(intercept, slope, eloDiff)` — OLS predicted margin
- `simulateGame(eloA, eloB)` — `Math.random() < computeWinProb(eloA, eloB)`; returns winner/loser
- `updateElo(winnerElo, loserElo, kFactor)` — standard Elo update, no MOV multiplier (no real score in simulated games)
- Bracket state machine — tracks current Elo per team, round number, slot assignments; reseeds after each round

---

## Page Structure

Single `matchup.html` page. Two tabs at the top: **Matchup Simulator** and **Playoff Bracket**. Only one tab is visible at a time. Tab state managed via JS class toggle.

`active_page = "matchup"` for nav highlighting in `_base.html`.

---

## Tab 1 — Matchup Simulator

### Controls

- **Week selector** (dropdown or slider, weeks 1–18): filters all data to games played up to and including the selected week. Elo ratings, recent form, H2H, and prediction all recompute on change.

### Team cards (two, side by side)

Each card contains:
- Team logo
- Team name (dropdown to select any team)
- Elo rating as of selected week
- Recent form: last 3 games up to selected week — opponent, W/L indicator, margin (e.g. `W +14`, `L −3`)
- Average margin of victory/defeat over the season to that week

### H2H strip

Sits between the two cards. If the selected teams played each other before the week cutoff: shows result (score, week, location, winner). If not: shows "No matchup this season."

### Prediction output

Below the cards:
- Probability bar (same visual style as the leaderboard widget)
- Win % for each team
- Predicted margin (OLS model)
- Strength label: Toss-up / Slight edge / Moderate favorite / Heavy favorite
- Neutral-site assumption (no home/away adjustment)

All values update reactively when either team or the week changes.

---

## Tab 2 — Playoff Bracket

### Initial state

Page loads with the real 2024 NFL playoff seeds pre-slotted. Wild Card matchups are pre-set. Each slot shows team logo, name, and Week 18 Elo.

**2024 NFL Playoff Seeds (to be hardcoded as `PLAYOFF_SEEDS_2024` in `build_site.py`):**

AFC:
- Seed 1: Kansas City Chiefs (bye)
- Seed 2: Buffalo Bills
- Seed 3: Baltimore Ravens
- Seed 4: Houston Texans
- Seed 5: Los Angeles Chargers
- Seed 6: Pittsburgh Steelers
- Seed 7: Denver Broncos

NFC:
- Seed 1: Detroit Lions (bye)
- Seed 2: Philadelphia Eagles
- Seed 3: Los Angeles Rams
- Seed 4: Minnesota Vikings
- Seed 5: Washington Commanders
- Seed 6: Green Bay Packers
- Seed 7: Tampa Bay Buccaneers

Wild Card matchups (seed 1 gets bye; 2 vs 7, 3 vs 6, 4 vs 5 per conference):

AFC Wild Card:
- (2) Buffalo Bills vs (7) Denver Broncos
- (3) Baltimore Ravens vs (6) Pittsburgh Steelers
- (4) Houston Texans vs (5) Los Angeles Chargers

NFC Wild Card:
- (2) Philadelphia Eagles vs (7) Tampa Bay Buccaneers
- (3) Los Angeles Rams vs (6) Green Bay Packers
- (4) Minnesota Vikings vs (5) Washington Commanders

### Bracket layout

Horizontal bracket, AFC on the left half, NFC on the right half, Super Bowl in the center. Columns: Wild Card → Divisional → Conference Championship → Super Bowl.

Each matchup slot shows:
- Team logo + name
- Current Elo (updates after each simulated round)

### Simulate Round button

Runs all games in the current round simultaneously using `simulateGame()`. Winners advance. Loser slots dim. Next round matchups are set using NFL reseed rules: **highest remaining seed always hosts lowest remaining seed.**

Elo updates after every round — by the Super Bowl, teams carry Elo shaped by their entire simulated playoff run (effectively weeks 19, 20, 21).

### Upset override

Each matchup has a flip control. Toggling it swaps the winner before or after simulation. The bracket recomputes downstream — slots, Elo, and next-round matchups all update. This lets the user answer "what if the 6-seed runs the table?"

### Reset button

Restores the bracket to the Week 18 initial state, clearing all simulated results and Elo changes.

### Super Bowl

When the two conference champions are determined, simulating the final produces a champion card showing the winner, final Elo, and win probability summary.

---

## Files Changed

| File | Change |
|---|---|
| `ui/build/build_site.py` | Add `PLAYOFF_SEEDS_2024` constant; add matchup page render block |
| `ui/templates/_base.html` | Add "Matchup" nav link between Leaderboard and Teams |
| `ui/templates/matchup.html` | New template — tab UI, simulator, bracket, JS engine |
| `ui/dist/matchup.html` | Generated output |

No changes to `compute_elo.py`, the analytics API, or any other existing file.

---

## Data Flow

```
build_site.py
  └─ fetches elo_all once (existing behavior)
  └─ extracts weekly_elos, games_by_team, margin_model
  └─ reads PLAYOFF_SEEDS_2024 (hardcoded constant)
  └─ renders matchup.html template → dist/matchup.html

dist/matchup.html (runtime)
  └─ JS reads embedded JSON blobs
  └─ Tab 1: week selector triggers recompute of cards + prediction
  └─ Tab 2: Simulate Round → simulateGame() → updateElo() → bracket state machine → DOM update
```

---

## Out of Scope

- Home/away advantage adjustment in win probability
- Monte Carlo multi-run aggregation (single-run simulation is sufficient)
- Saving or sharing bracket results
- Any server-side computation at runtime
