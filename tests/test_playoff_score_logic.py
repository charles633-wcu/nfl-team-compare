from playoff_score_logic import (
    VALID_NFL_SCORES,
    choose_score_pair,
    simulate_playoff_score,
)


def test_valid_nfl_scores_exclude_impossible_one_point_total():
    assert 1 not in VALID_NFL_SCORES
    assert 0 in VALID_NFL_SCORES
    assert 2 in VALID_NFL_SCORES
    assert 7 in VALID_NFL_SCORES


def test_choose_score_pair_returns_non_tie_valid_scores():
    winner_score, loser_score = choose_score_pair(target_total=41, target_margin=0)

    assert winner_score > loser_score
    assert winner_score in VALID_NFL_SCORES
    assert loser_score in VALID_NFL_SCORES


def test_simulate_playoff_score_never_returns_ties_or_invalid_scores():
    for _ in range(2000):
        result = simulate_playoff_score(elo_a=1640, elo_b=1600)
        assert result["score_a"] != result["score_b"]
        assert result["score_a"] in VALID_NFL_SCORES
        assert result["score_b"] in VALID_NFL_SCORES
        assert result["winner"] in {"A", "B"}
