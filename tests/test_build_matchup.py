import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "ui" / "build"))

from build_site import build_matchup_page, PLAYOFF_SEEDS_2024
from jinja2 import Environment, BaseLoader, FileSystemLoader


def _make_test_dir(name: str) -> Path:
    root = Path(__file__).parents[1] / "ui" / ".test-build-matchup"
    path = root / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path

MINIMAL_ELO_ALL = {
    "season": 2024,
    "k_factor": 25,
    "elo": {
        "0": {"Buffalo Bills": 1500, "Kansas City Chiefs": 1500},
        "1": {"Buffalo Bills": 1512, "Kansas City Chiefs": 1488},
    },
    "teams": {
        "Buffalo Bills": {
            "0": {"games": [], "final_elo": 1500},
            "1": {
                "games": [{
                    "week": 1, "opponent": "Kansas City Chiefs",
                    "home": True, "margin": 7,
                    "team_elo_pre": 1500, "opponent_elo_pre": 1500,
                    "elo_after_game": 1512,
                }],
                "final_elo": 1512,
            },
        },
        "Kansas City Chiefs": {
            "0": {"games": [], "final_elo": 1500},
            "1": {
                "games": [{
                    "week": 1, "opponent": "Buffalo Bills",
                    "home": False, "margin": -7,
                    "team_elo_pre": 1500, "opponent_elo_pre": 1500,
                    "elo_after_game": 1488,
                }],
                "final_elo": 1488,
            },
        },
    },
    "margin_model": {"intercept": 1.835, "slope": 0.049, "type": "ols"},
    "score_model": {
        "total_points_mean": 46.025735294117645,
        "total_points_std_dev": 10,
        "margin_std_dev": 13.45,
        "n_samples": 272,
    },
}


def test_build_matchup_page_writes_file():
    """build_matchup_page should write matchup.html to dist_dir."""
    env = Environment(loader=BaseLoader())
    env.get_template = lambda name: type(
        "T", (), {"render": lambda self, **kw: "<html/>"}
    )()
    dist = _make_test_dir("writes-file")
    try:
        build_matchup_page(env, MINIMAL_ELO_ALL, dist, season=2024, playoff_seeds=PLAYOFF_SEEDS_2024)
        assert (dist / "matchup.html").exists()
    finally:
        shutil.rmtree(dist)


def test_playoff_seeds_structure():
    """PLAYOFF_SEEDS_2024 should have AFC and NFC with 7 seeds each."""
    assert set(PLAYOFF_SEEDS_2024.keys()) == {"AFC", "NFC"}
    for conf in ("AFC", "NFC"):
        seeds = PLAYOFF_SEEDS_2024[conf]
        assert len(seeds) == 7
        assert seeds[0]["seed"] == 1
        assert seeds[0]["bye"] is True
        for s in seeds[1:]:
            assert s["bye"] is False


def test_margin_model_extracted_correctly():
    """build_matchup_page should extract only intercept and slope."""
    captured = {}

    class FakeTemplate:
        def render(self, **kw):
            captured.update(kw)
            return "<html/>"

    env = type("E", (), {"get_template": lambda self, n: FakeTemplate()})()
    dist = _make_test_dir("margin-model")
    try:
        build_matchup_page(env, MINIMAL_ELO_ALL, dist, season=2024, playoff_seeds=PLAYOFF_SEEDS_2024)
    finally:
        shutil.rmtree(dist)
    mm = json.loads(captured["margin_model_json"])
    assert set(mm.keys()) == {"intercept", "slope"}
    assert mm["intercept"] == 1.835
    assert mm["slope"] == 0.049


def test_score_model_extracted_correctly():
    """build_matchup_page should pass season-specific score simulation parameters."""
    captured = {}

    class FakeTemplate:
        def render(self, **kw):
            captured.update(kw)
            return "<html/>"

    env = type("E", (), {"get_template": lambda self, n: FakeTemplate()})()
    dist = _make_test_dir("score-model")
    try:
        build_matchup_page(env, MINIMAL_ELO_ALL, dist, season=2025, playoff_seeds=PLAYOFF_SEEDS_2024)
    finally:
        shutil.rmtree(dist)

    score_model = json.loads(captured["score_model_json"])
    assert score_model == {
        "totalPointsMean": 46.025735294117645,
        "totalPointsStdDev": 10.0,
        "marginStdDev": 13.45,
    }


def test_matchup_page_embeds_valid_score_simulation_helpers():
    templates_dir = Path(__file__).parents[1] / "ui" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    dist = _make_test_dir("score-helpers")
    try:
        build_matchup_page(env, MINIMAL_ELO_ALL, dist, season=2024, playoff_seeds=PLAYOFF_SEEDS_2024)
        rendered = (dist / "matchup.html").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(dist)

    assert "VALID_NFL_SCORES" in rendered
    assert "chooseScorePair" in rendered
    assert "const SCORE_MODEL" in rendered
    assert "normalRandom(SCORE_MODEL.totalPointsMean, SCORE_MODEL.totalPointsStdDev)" in rendered
