"""
Playoff bracket Monte Carlo simulation.
Ports the exact JS logic from ui/dist/matchup.html and runs N simulations
to check if Super Bowl win rates by seed match historical NFL data.
"""

import math
import random
from collections import defaultdict

from playoff_score_logic import simulate_playoff_score


MARGIN_MODEL = {"intercept": 1.835194679917717, "slope": 0.049295544913558274}
K_FACTOR = 25
HOME_FIELD_ADV = 65  # Elo points added to home team in non-neutral playoff games

PLAYOFF_SEEDS = {
    "AFC": [
        {"seed": 1, "team": "Kansas City Chiefs",    "bye": True},
        {"seed": 2, "team": "Buffalo Bills",          "bye": False},
        {"seed": 3, "team": "Baltimore Ravens",       "bye": False},
        {"seed": 4, "team": "Houston Texans",         "bye": False},
        {"seed": 5, "team": "Los Angeles Chargers",   "bye": False},
        {"seed": 6, "team": "Pittsburgh Steelers",    "bye": False},
        {"seed": 7, "team": "Denver Broncos",         "bye": False},
    ],
    "NFC": [
        {"seed": 1, "team": "Detroit Lions",          "bye": True},
        {"seed": 2, "team": "Philadelphia Eagles",    "bye": False},
        {"seed": 3, "team": "Los Angeles Rams",       "bye": False},
        {"seed": 4, "team": "Tampa Bay Buccaneers",   "bye": False},
        {"seed": 5, "team": "Washington Commanders",  "bye": False},
        {"seed": 6, "team": "Minnesota Vikings",      "bye": False},
        {"seed": 7, "team": "Green Bay Packers",      "bye": False},
    ],
}

# exact ELO scores for week 18

W18_ELOS = {
    "Arizona Cardinals": 1482, "Atlanta Falcons": 1422, "Baltimore Ravens": 1684,
    "Buffalo Bills": 1643, "Carolina Panthers": 1374, "Chicago Bears": 1384,
    "Cincinnati Bengals": 1569, "Cleveland Browns": 1316, "Dallas Cowboys": 1442,
    "Denver Broncos": 1616, "Detroit Lions": 1711, "Green Bay Packers": 1624,
    "Houston Texans": 1511, "Indianapolis Colts": 1424, "Jacksonville Jaguars": 1355,
    "Kansas City Chiefs": 1631, "Las Vegas Raiders": 1347, "Los Angeles Chargers": 1594,
    "Los Angeles Rams": 1548, "Miami Dolphins": 1472, "Minnesota Vikings": 1683,
    "New England Patriots": 1372, "New Orleans Saints": 1363, "New York Giants": 1329,
    "New York Jets": 1436, "Philadelphia Eagles": 1707, "Pittsburgh Steelers": 1521,
    "San Francisco 49ers": 1401, "Seattle Seahawks": 1557, "Tampa Bay Buccaneers": 1586,
    "Tennessee Titans": 1292, "Washington Commanders": 1604,
}

#  Engine (mirrors JS exactly) 

def compute_win_prob(elo_a, elo_b):
    return 1 / (1 + math.pow(10, (elo_b - elo_a) / 400))

def compute_margin(elo_a, elo_b):
    return MARGIN_MODEL["intercept"] + MARGIN_MODEL["slope"] * (elo_a - elo_b)

def simulate_game(elo_a, elo_b):
    """Returns playoff-safe scores and winner using the shared score model."""
    return simulate_playoff_score(
        elo_a,
        elo_b,
        intercept=MARGIN_MODEL["intercept"],
        slope=MARGIN_MODEL["slope"],
        rng=random,
    )

def update_elo(winner_elo, loser_elo):
    p_win = compute_win_prob(winner_elo, loser_elo)
    return (
        round(winner_elo + K_FACTOR * (1 - p_win)),
        round(loser_elo  + K_FACTOR * (0 - (1 - p_win))),
    )

#  Bracket simulation 

def run_one_bracket():
    """
    Simulates one full playoff bracket.
    Returns (champion_team, original_seed).
    """
    # Build per-team state
    elos = {}
    original_seeds = {}
    for conf in ("AFC", "NFC"):
        for s in PLAYOFF_SEEDS[conf]:
            team = s["team"]
            elos[team] = W18_ELOS.get(team, 1500)
            original_seeds[team] = s["seed"]

    bye_teams = {
        "AFC": next(s["team"] for s in PLAYOFF_SEEDS["AFC"] if s["bye"]),
        "NFC": next(s["team"] for s in PLAYOFF_SEEDS["NFC"] if s["bye"]),
    }

    def seed_map(conf):
        return {s["seed"]: s["team"] for s in PLAYOFF_SEEDS[conf]}

    def play(home, away, neutral=False):
        """Simulate one game with optional HFA, update Elos in place, return winner."""
        hfa = 0 if neutral else HOME_FIELD_ADV
        result = simulate_game(elos[home] + hfa, elos[away])
        winner, loser = (home, away) if result["winner"] == "A" else (away, home)
        elos[winner], elos[loser] = update_elo(elos[winner], elos[loser])
        return winner

    #  Wild Card
    wc_winners = {"AFC": [], "NFC": []}
    for conf in ("AFC", "NFC"):
        sm = seed_map(conf)
        for home_seed, away_seed in [(2, 7), (3, 6), (4, 5)]:
            w = play(sm[home_seed], sm[away_seed])
            wc_winners[conf].append(w)

    #  Divisional 
    div_winners = {"AFC": [], "NFC": []}
    for conf in ("AFC", "NFC"):
        # 3 WC winners + 1 bye team, re-sorted by original seed (best = lowest)
        survivors = sorted(
            wc_winners[conf] + [bye_teams[conf]],
            key=lambda t: original_seeds[t],
        )
        # pair lo vs hi (1v4, 2v3) — highest seed = home
        lo, hi = 0, len(survivors) - 1
        while lo < hi:
            w = play(survivors[lo], survivors[hi])
            div_winners[conf].append(w)
            lo += 1
            hi -= 1

    #  Conference Championship 
    conf_winners = {}
    for conf in ("AFC", "NFC"):
        survivors = sorted(div_winners[conf], key=lambda t: original_seeds[t])
        w = play(survivors[0], survivors[1])
        conf_winners[conf] = w

    #  Super Bowl 
    afc_rep = conf_winners["AFC"]
    nfc_rep = conf_winners["NFC"]
    # Super Bowl is a neutral site — no HFA
    champion = play(afc_rep, nfc_rep, neutral=True)
    return champion, original_seeds[champion]


#  Monte Carlo 

def run_simulation(n=100_000):
    wins_by_seed = defaultdict(int)
    wins_by_team = defaultdict(int)

    for _ in range(n):
        team, seed = run_one_bracket()
        wins_by_seed[seed] += 1
        wins_by_team[team] += 1

    print(f"\nSuper Bowl win rates over {n:,} simulations")
    print(f"{'Seed':<6} {'Wins':>8} {'Win %':>8}  {'Historical %':>14}")
    historical = {1: "~35–40%", 2: "~20–25%", 3: "~10–15%",
                  4: "~8–10%",  5: "~5–8%",   6: "~3–5%",   7: "~1–2%"}
    for seed in range(1, 8):
        wins = wins_by_seed[seed]
        pct  = wins / n * 100
        hist = historical.get(seed, "—")
        print(f"  {seed:<4} {wins:>8,} {pct:>7.2f}%  {hist:>14}")

    print(f"\nPer-team breakdown:")
    # Build lookup: team -> (conf, seed)
    team_meta = {}
    for conf in ("AFC", "NFC"):
        for s in PLAYOFF_SEEDS[conf]:
            team_meta[s["team"]] = (conf, s["seed"])
    all_teams = sorted(wins_by_team.keys(), key=lambda t: (team_meta[t][0], team_meta[t][1]))
    for team in all_teams:
        conf, seed = team_meta[team]
        wins = wins_by_team[team]
        pct  = wins / n * 100
        print(f"  [{conf} #{seed}] {team:<28} {wins:>7,}  ({pct:.2f}%)")


if __name__ == "__main__":
    random.seed(42)
    run_simulation(100_000)
