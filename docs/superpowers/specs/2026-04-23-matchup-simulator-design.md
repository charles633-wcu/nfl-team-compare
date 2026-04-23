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

| Variable | Source | Notes |
|---|---|---|
| `weekly_elos` | `elo_all["elo"]` | `{week_str: {team: elo_int}}` for weeks "0"–"18". ~5 KB. |
| `games_by_team` | `elo_all["teams"]` | `{team: {week_str: {games: [...], final_elo: int}}}`. Each game object contains: `opponent`, `home`, `points_for`, `points_against`, `margin`, `team_elo_pre`, `opponent_elo_pre`, `elo_diff_pre`, `elo_after_game`, `predicted_margin_pre`. ~80–100 KB. |
| `margin_model` | `elo_all["margin_model"]` | Full object: `{type, feature, target, intercept, slope, n_samples}`. JS reads `intercept` and `slope` by name. |
| `k_factor` | `elo_all["k_factor"]` | Integer (25 in production). Used by `updateElo()`. |
| `playoff_seeds` | `PLAYOFF_SEEDS_2024` constant | Hardcoded in `build_site.py`. See playoff section. |

The template render call passes `base_path=""` (matchup.html lives at the dist root, same level as index.html), along with `season` and `current_week` for the footer.

### In-browser JS engine

No framework. Four pure functions plus a bracket state machine:

- `computeWinProb(eloA, eloB)` — `1 / (1 + 10^((eloB - eloA) / 400))`
- `computeMargin(intercept, slope, eloDiff)` — OLS predicted margin
- `simulateGame(eloA, eloB)` — `Math.random() < computeWinProb(eloA, eloB)`; returns `{winner, loser}`
- `updateElo(winnerElo, loserElo, kFactor)` — base Elo update without MOV multiplier: `K * (1 - E_winner)` for winner, symmetric for loser. MOV multiplier is intentionally dropped because simulated games have no real score.
- Bracket state machine — tracks current Elo per team, round number, slot assignments; reseeds after each round

---

## Page Structure

Single `matchup.html` page. Two tabs at the top: **Matchup Simulator** and **Playoff Bracket**. Only one section is visible at a time — the active tab has a visible CSS class; the inactive section has `display: none`. Tab state toggled by JS on click.

**Nav integration:** `active_page = "matchup"` passed from `build_site.py`. In `_base.html`, the brand-title conditional already has an `{% else %}` branch that renders the brand as a link — no change needed there. A "Matchup" nav link is added between Leaderboard and Teams:
```html
<a href="{{ base_path }}matchup.html" class="navlink {% if active_page == 'matchup' %}active{% endif %}">Matchup</a>
```

---

## Tab 1 — Matchup Simulator

### Controls

- **Week selector** (dropdown, weeks 1–18, minimum 1 — week 0 is excluded): filters all data to games played up to and including the selected week. Elo ratings, recent form, H2H, and prediction all recompute on change. If week 1 is selected and a team has no games yet, recent form shows "No games played."

### Team cards (two, side by side)

Each card contains:
- Team logo
- Team name (dropdown to select any team)
- Elo rating as of selected week (read from `weekly_elos[week][team]`)
- Recent form: last 3 games played up to the selected week, drawn from `games_by_team[team]` across weeks 1–selected; shows opponent, W/L indicator, margin (e.g. `W +14`, `L −3`)
- Average margin of victory/defeat over the season to that week

**Same-team guard:** If both dropdowns select the same team, the prediction output shows "Select two different teams" and the simulate controls are disabled. No prediction is computed.

### H2H strip

Sits between the two cards. Searches `games_by_team[teamA]` across weeks 1–selected for any game where `opponent === teamB`. If found: shows result (score, week, location, winner). If not: shows "No matchup this season."

### Prediction output

Below the cards:
- Probability bar (same visual style as the leaderboard widget — CSS class `predictor-bar`)
- Win % for each team
- Predicted margin (OLS model using Elo as of selected week)
- Strength label: Toss-up (<10% delta) / Slight edge (10–19%) / Moderate favorite (20–34%) / Heavy favorite (35%+)
- Neutral-site assumption (no home/away adjustment)

All values update reactively when either team or the week changes.

---

## Tab 2 — Playoff Bracket

### Initial state

Page loads with the real 2024 NFL playoff seeds pre-slotted. Wild Card matchups are pre-set. Each slot shows team logo, name, and Week 18 Elo.

**2024 NFL Playoff Seeds — `PLAYOFF_SEEDS_2024` constant in `build_site.py`:**

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

Wild Card matchups (seed 1 gets bye; seeds 2–7 play: 2 vs 7, 3 vs 6, 4 vs 5 per conference):

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

Each matchup slot shows team logo + name + current Elo (updates after each simulated round).

### Simulate Round button

Runs all unresolved games in the current round simultaneously using `simulateGame()`. Winners advance; loser slots dim. Next round matchups are assigned using NFL reseed rules: **highest remaining seed always hosts the lowest remaining seed** within each conference. The "Simulate Round" button is **disabled** once the Super Bowl result is determined — the bracket has reached its terminal state.

Elo updates after every simulated round: `updateElo(winnerElo, loserElo, kFactor)` is called for each game. By the Super Bowl, teams carry Elo shaped by their entire simulated playoff run (effectively weeks 19, 20, 21).

### Upset override

Each matchup has a flip toggle that **pre-sets a locked winner before simulation runs**, bypassing `simulateGame()` for that matchup. When the round is simulated, locked matchups use the manually chosen winner rather than a random draw.

**Rewind on post-simulation override:** If the user toggles a flip on an already-simulated round, the bracket rewinds to that round's entry state and replays all subsequent rounds with fresh random draws (respecting any remaining locked overrides). To support rewinding, the bracket state machine **snapshots Elo values at the start of each round** before simulating it. A round snapshot is `{roundIndex, eloSnapshot: {team: elo}, results: [...]}`. Rewinding to round N restores `eloSnapshot[N]` and clears results for rounds N and later. Bracket slots, Elo values, and next-round matchup assignments all update accordingly.

### Reset button

Restores the bracket to the Week 18 initial state: all Elo values reset to Week 18 values, all results cleared, all locked overrides cleared, "Simulate Round" button re-enabled.

### Super Bowl

When the two conference champions are determined, simulating the final produces a champion card showing: winner logo + name, final simulated Elo, and win probability against the opponent. "Simulate Round" button disables — bracket is complete. Reset remains available.

---

## Files Changed

| File | Change |
|---|---|
| `ui/build/build_site.py` | Add `PLAYOFF_SEEDS_2024` constant; add matchup page render block passing `base_path=""`, `weekly_elos_json`, `games_by_team_json`, `margin_model_json`, `k_factor`, `playoff_seeds_json`, `season`, `current_week` |
| `ui/templates/_base.html` | Add "Matchup" nav link between Leaderboard and Teams; extend brand-title conditional to handle `active_page == "matchup"` |
| `ui/templates/matchup.html` | New template — tab UI, simulator, bracket, JS engine |
| `ui/dist/matchup.html` | Generated output |

No changes to `compute_elo.py`, the analytics API, or any other existing file.

---

## Data Flow

```
build_site.py
  └─ fetches elo_all once (existing behavior)
  └─ extracts weekly_elos, games_by_team, margin_model, k_factor
  └─ reads PLAYOFF_SEEDS_2024 (hardcoded constant)
  └─ renders matchup.html → dist/matchup.html
       template vars: base_path="", season, current_week,
                      weekly_elos_json, games_by_team_json,
                      margin_model_json, k_factor, playoff_seeds_json

dist/matchup.html (runtime, no network calls)
  └─ JS reads embedded JSON blobs
  └─ Tab 1: week selector + team dropdowns trigger recompute → cards + prediction update
  └─ Tab 2: Simulate Round → simulateGame()/override → updateElo() → bracket state machine → DOM update
       Terminal state: Super Bowl complete → button disabled
       Reset: restores Week 18 state
```

---

## Out of Scope

- Home/away advantage adjustment in win probability
- Monte Carlo multi-run aggregation (single-run simulation is sufficient)
- Saving or sharing bracket results
- Any server-side computation at runtime
- Week 0 in the week selector (excluded; baseline only, no games)
