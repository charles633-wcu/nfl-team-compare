import math
import random
from functools import lru_cache


MARGIN_STD_DEV = 13.45
TOTAL_POINTS_MEAN = 43.5
TOTAL_POINTS_STD_DEV = 10
MIN_TOTAL_POINTS = 21
MAX_SCORE_SEARCH = 80
SCORING_PLAYS = (2, 3, 6, 7, 8)


def compute_margin(elo_a, elo_b, intercept, slope):
    return intercept + slope * (elo_a - elo_b)


@lru_cache(maxsize=1)
def _build_valid_scores():
    reachable = {0}
    for _ in range(MAX_SCORE_SEARCH):
        additions = {
            score + play
            for score in list(reachable)
            for play in SCORING_PLAYS
            if score + play <= MAX_SCORE_SEARCH
        }
        if additions.issubset(reachable):
            break
        reachable.update(additions)
    return tuple(sorted(reachable))


VALID_NFL_SCORES = _build_valid_scores()
VALID_SCORE_PAIRS = tuple(
    (winner_score, loser_score)
    for winner_score in VALID_NFL_SCORES
    for loser_score in VALID_NFL_SCORES
    if winner_score > loser_score
)


@lru_cache(maxsize=None)
def _choose_score_pair_cached(target_total, target_margin):
    target_total = max(MIN_TOTAL_POINTS, min(MAX_SCORE_SEARCH * 2, int(round(target_total))))
    target_margin = max(1, min(MAX_SCORE_SEARCH, int(round(abs(target_margin)))))

    return min(
        VALID_SCORE_PAIRS,
        key=lambda pair: (
            abs((pair[0] + pair[1]) - target_total),
            abs((pair[0] - pair[1]) - target_margin),
            abs(pair[0] - math.ceil((target_total + target_margin) / 2)),
            pair[0] + pair[1],
        ),
    )


def choose_score_pair(target_total, target_margin):
    return _choose_score_pair_cached(target_total, target_margin)


def simulate_playoff_score(
    elo_a,
    elo_b,
    *,
    intercept=1.835194679917717,
    slope=0.049295544913558274,
    rng=None,
):
    rng = rng or random
    expected_margin = compute_margin(elo_a, elo_b, intercept, slope)
    simulated_margin = rng.gauss(expected_margin, MARGIN_STD_DEV)
    simulated_total = max(MIN_TOTAL_POINTS, round(rng.gauss(TOTAL_POINTS_MEAN, TOTAL_POINTS_STD_DEV)))
    winner = "A" if simulated_margin >= 0 else "B"
    winner_score, loser_score = choose_score_pair(simulated_total, abs(simulated_margin))
    return {
        "winner": winner,
        "score_a": winner_score if winner == "A" else loser_score,
        "score_b": winner_score if winner == "B" else loser_score,
    }
