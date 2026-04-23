# Spec — Playoff Bracket Redesign

**Date:** 2026-04-23
**Status:** Approved, pending implementation
**Author:** Claude (claude-sonnet-4-6)

---

## Overview

Redesign the Playoff Bracket tab inside `matchup.html` to show the entire 4-round bracket simultaneously, ESPN ScoreCenter-style matchup cards, sequential spotlight animations per game, projected score display, and a Super Bowl confetti celebration. The Matchup Simulator tab is unchanged.

---

## Layout — Left-to-Right with AFC/NFC Stacked

Four columns rendered as a CSS grid: **Wild Card → Divisional → Conference Championship → Super Bowl**. Each column is split into an AFC section (top) and NFC section (bottom) separated by a thin horizontal rule. The Super Bowl column spans both halves and shows a single centered matchup.

All four rounds are visible from page load. Future rounds render as dimmed TBD placeholder slots — they fill in as rounds are simulated. A gold `CURRENT ROUND` eyebrow label marks the active column.

Below 768 px the bracket grid scrolls horizontally (`overflow-x: auto` on the container). No column rearrangement is required.

**Column matchup counts:**

| Column | AFC | NFC |
|--------|-----|-----|
| Wild Card | 3 matchups + 1 bye slot | 3 matchups + 1 bye slot |
| Divisional | 2 matchups | 2 matchups |
| Conference Championship | 1 matchup | 1 matchup |
| Super Bowl | — | 1 matchup spanning both |

**Connector lines:** Each matchup card has a decorative right-side stub only — a 1 px `--border` coloured right-border on the card wrapper that visually points toward the next column. No full elbow or vertical join is required. The bye slot has the same stub. Connectors do not change colour when the slot resolves.

---

## Matchup Card — ESPN ScoreCenter Style

Each matchup is a card with `--panel-strong` background, 1 px `--border` border, `--radius-md` corners. Layout:

```
┌─────────────────────────────────────────────────┐
│ WILD CARD · AFC            [Proj. +7.4 pts]  [↺] │  ← header row (upset btn right-aligned here)
├─────────────────────────────────────────────────┤
│ 2  [logo]  Buffalo Bills      Elo 1582   27  68% │  ← home row
│ 7  [logo]  Denver Broncos     Elo 1441   14  32% │  ← away row
│ ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │  ← winner gold bar (2px, bottom of card)
└─────────────────────────────────────────────────┘
```

The `↺ Upset` button sits **inline in the header row**, right-aligned, so it never overlaps team rows or the projected margin text. The projected margin and upset button share the right side of the header: `margin · [↺ Upset]` in a flex row with `gap: 8px`. The Super Bowl champion card uses `--radius-lg` corners.

**Per-row fields:** seed · team logo (24 px) · team name (Barlow Condensed 700) · Elo rating (muted) · projected score (Barlow Condensed 800, 1.4 rem) · win probability (small, muted)

**States:**
- **Pending:** scores shown in `--muted` color as projected, no gold bar, `↺ Upset` button visible in header
- **Winner row:** white name, `--accent` score + win-prob, 2 px gold sweep bar across card bottom
- **Loser row:** 40% opacity, strikethrough on name
- **TBD slot:** all fields show `—`, border dashed, no upset button, no header projected margin
- **Bye slot:** single row "Kansas City Chiefs — BYE", 45% opacity, italic, no button, `--radius-md`

**Header row:** round name left-aligned, projected margin + upset button right-aligned, all small caps `--muted` text.

---

## Projected Score Derivation

`computeMargin(eloA, eloB)` returns the predicted point margin for team A. Scores are derived as:

```js
const margin = Math.abs(computeMargin(eloA, eloB));
const loserScore  = 17;                          // fixed baseline
const winnerScore = Math.round(loserScore + margin);
```

The winner/loser assignment determines which team gets `winnerScore`. Scores are integers. The animation counts up to these values during the spotlight sequence.

---

## Upset Button

- Renders inline in the header row of every **pending** (unresolved) matchup card, right-aligned
- Label: `↺ Upset` (muted border, muted text)
- **On click:** toggles forced state — underdog (lower win probability) is locked as winner. Button turns `--danger` border + `--danger` text, label changes to `Forced ✕`
- **On second click:** clears the lock, restores `↺ Upset` styling
- When "Run Round" fires, forced matchups skip `simulateGame()` and use the locked winner directly
- Upset button is removed when card enters resolved state
- `forceUpset(matchupId)` is called via `onclick` inline in the JS-generated card HTML, matching the existing calling convention in `renderSlot()`

---

## Sequential Spotlight Animation

Triggered by "Run Round" button. Button disables immediately. `bracketState.animating = true` is set to block re-entrant calls.

Each card completes all four phases before the next card's spotlight begins. For Wild Card (6 games) total animation is approximately **8 seconds** before the advance step.

For each pending matchup in the current round, in order:

1. **Spotlight (100 ms):** card border transitions to `--accent`, card `transform: scale(1.02)`, `z-index` elevates above siblings
2. **Count-up (600 ms):** home and away scores count up from `0` to their derived values using `requestAnimationFrame`; scores render in `--accent` color during count
3. **Reveal (200 ms):** winner row turns gold + name white; loser row dims to 40% opacity + name strikethrough; 2 px gold bar CSS `width` transitions from `0` to `100%` across card bottom
4. **Rest (300 ms):** card settles to `scale(1.0)`, border settles to `--accent` (winner card) or `--border` (loser card)
5. Move to next matchup

After all matchups in the round resolve, winners' names **fade + slide into** the corresponding TBD slots in the next column (150 ms staggered per slot: `opacity 0→1` + `translateX(-8px → 0)`).

The "Run Round" button re-enables and `bracketState.animating = false` after the last advance animation completes. During animation, all upset buttons are `pointer-events: none`.

---

## Super Bowl Celebration

When `runRound()` resolves the Super Bowl matchup:

1. **Confetti burst:** 120 particles are JS-created `div.confetti-particle` nodes, appended to the bracket section, positioned absolute at random x within the section width, animated with `@keyframes confettiFall` (2.5 s, `translateY` top → section bottom + random `rotate` + `translateX` drift). Removed on `animationend`. Colors cycle through: `#FFB347`, `#ffffff`, `#9ab8c8`, `#7ec8e3`, `#f97316`, `#a3e635`.
2. **Champion card:** the Super Bowl slot re-renders as `.bracket-sb-card` (`--radius-lg`) showing:
   - `🏆 SUPER BOWL CHAMPION` eyebrow in `--accent` Barlow Condensed 700, `@keyframes pulse` glow (2 s loop)
   - Team logo at 72 px
   - Team name in Barlow Condensed 800 at 2 rem, white
   - Final simulated Elo and win probability vs opponent (muted)
   - Gold shimmer overlay: `@keyframes shimmer` — a `linear-gradient` pseudo-element sweeps left-to-right
3. **"Run Round" button** stays disabled. **"Reset"** clears all results, restores Week 18 Elos, re-enables Run Round.

---

## State Machine — New Shape

The existing `bracketState` object is replaced with this shape:

```js
bracketState = {
  // allRounds[0] (Wild Card) is fully pre-built and never mutated.
  // allRounds[1–3] slots start with home/away as null and are mutated in-place
  // by populateNextRound() after each round resolves (advance animation step).
  allRounds: [
    // round 0 — Wild Card (fully pre-built)
    [
      { id: 'AFC-wc-0', conf: 'AFC', type: 'bye',  team: 'Kansas City Chiefs', seed: 1 },
      { id: 'AFC-wc-1', conf: 'AFC', type: 'game', home: 'Buffalo Bills',    homeSeed: 2, away: 'Denver Broncos',     awaySeed: 7 },
      { id: 'AFC-wc-2', conf: 'AFC', type: 'game', home: 'Baltimore Ravens', homeSeed: 3, away: 'Pittsburgh Steelers',awaySeed: 6 },
      { id: 'AFC-wc-3', conf: 'AFC', type: 'game', home: 'Houston Texans',   homeSeed: 4, away: 'LA Chargers',        awaySeed: 5 },
      { id: 'NFC-wc-0', conf: 'NFC', type: 'bye',  team: 'Detroit Lions',    seed: 1 },
      // ... NFC WC matchups (same pattern)
    ],
    // round 1 — Divisional: home/away start null, filled after round 0
    [
      { id: 'AFC-div-0', conf: 'AFC', type: 'game', home: null, homeSeed: null, away: null, awaySeed: null },
      { id: 'AFC-div-1', conf: 'AFC', type: 'game', home: null, homeSeed: null, away: null, awaySeed: null },
      { id: 'NFC-div-0', conf: 'NFC', type: 'game', home: null, homeSeed: null, away: null, awaySeed: null },
      { id: 'NFC-div-1', conf: 'NFC', type: 'game', home: null, homeSeed: null, away: null, awaySeed: null },
    ],
    // round 2 — Conference Championship: 2 slots, home/away null until after round 1
    [ /* same pattern, 2 entries */ ],
    // round 3 — Super Bowl: 1 slot, home/away null until after round 2
    [ /* 1 entry */ ],
  ],

  // results[i] is undefined until round i completes.
  // A populated results[i] is an array of resolved game objects, one per game slot:
  // { id: 'AFC-wc-1', winner: 'Buffalo Bills', loser: 'Denver Broncos',
  //   winnerScore: 24, loserScore: 17 }
  // Bye slots are never added to results[].
  results: [undefined, undefined, undefined, undefined],

  // Elo per team — updated after each round simulation
  teamElos: { 'Kansas City Chiefs': 1601, 'Buffalo Bills': 1582, /* ... */ },

  // Original seeds for reseed logic
  originalSeeds: { 'Kansas City Chiefs': 1, 'Buffalo Bills': 2, /* ... */ },

  // Bye teams per conference
  byeTeams: { AFC: 'Kansas City Chiefs', NFC: 'Detroit Lions' },

  // Forced upsets: matchupId → underdog team name (root-level dict, no slot-level field)
  forced: {},

  // Active round index (0–3)
  round: 0,

  // Animation guard
  animating: false,

  // Champion (null until SB resolves)
  champion: null,
};
```

`renderBracket()` iterates all four `allRounds` entries every call. For each game slot it checks `results[roundIndex]` (if defined) to find a matching `{ id }` entry and reads `winner`/`loser`/scores from it. Slots with no matching result entry render as pending (or TBD if `home === null`). Bye slots always render as bye — they are never in `results[]`.

The advance animation step calls `populateNextRound(roundIndex, results)` which writes the reseeded `home`/`away`/`homeSeed`/`awaySeed` values into the `allRounds[roundIndex + 1]` slot objects in-place.

**Animation timing:** 6 Wild Card games × 1,200 ms = 7.2 seconds of sequential game animation. The advance animation (6 slots × 150 ms stagger) adds ~0.9 seconds. "Run Round" re-enables after the final advance animation completes — total elapsed ≈ 8.1 seconds from button click to re-enable. The spec's "approximately 8 seconds" refers to this full end-to-end duration including advance.

---

## CSS Changes

All new styles appended to `ui/static/css/app.css` in a `/* Bracket Redesign */` section. Existing `.bracket-*` classes are removed entirely to avoid conflicts.

New classes:
- `.bracket-grid` — 4-column CSS grid, `overflow-x: auto`
- `.bracket-col` — single round column (flex column, `min-width: 220px`)
- `.bracket-col-header` — round label + current-round gold eyebrow indicator
- `.bracket-matchup` — ScoreCenter card (`--panel-strong`, `--border`, `--radius-md`)
- `.bracket-matchup.pending / .resolved / .tbd / .bye`
- `.bracket-matchup-header` — header row with round name + projected margin + upset button
- `.bracket-team-row.winner / .loser`
- `.bracket-winner-bar` — 2 px `--accent` bottom bar, `width` transitions `0→100%`
- `.bracket-connector` — right-side 1 px `--border` stub on each card wrapper
- `.bracket-sb-card` — expanded Super Bowl champion card (`--radius-lg`)
- `.confetti-particle` — JS-injected confetti DOM nodes
- `@keyframes spotlight, winnerBarSweep, shimmer, confettiFall, pulse`

---

## Files Changed

| File | Change |
|------|--------|
| `ui/templates/matchup.html` | Replace bracket HTML structure + JS state machine + animation engine |
| `ui/static/css/app.css` | Remove old `.bracket-*` styles; append new ScoreCenter + animation styles |

No changes to `build_site.py`, `compute_elo.py`, the analytics API, or the Matchup Simulator tab.

---

## Out of Scope

- Rewind-on-post-simulation override (upset lock only works before a round runs)
- Mobile-optimised bracket layout (bracket scrolls horizontally below 768 px)
- Saving or sharing bracket state
- Real NFL scores or live data
