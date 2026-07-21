from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BUILD_DIR = Path(__file__).resolve().parents[1] / "ui" / "build"
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from build_site import SiteConfig, build_site  # noqa: E402


class HomepageBuildSmokeTests(unittest.TestCase):
    """Verifies the generated homepage is a landing page rather than a leaderboard shell."""

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.ui_dir = self.repo_root / "ui"
        self.dist_dir = self.ui_dir / ".test-dist-temp"
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)

    def test_build_outputs_story_first_homepage(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        local_elo = json.loads((repo_root / "elo" / "elo_2024.json").read_text(encoding="utf-8"))
        teams_blob = local_elo["teams"]

        def fake_fetch_team_timeline(_api_base: str, team: str, timeout_s: int = 20, season=None) -> dict:
            team_weeks = teams_blob[team]
            return {
                "season": local_elo["season"],
                "team": team,
                "weeks": [
                    {
                        "week": int(week_key),
                        "final_elo": week_value["final_elo"],
                        "games": week_value["games"],
                    }
                    for week_key, week_value in sorted(team_weeks.items(), key=lambda item: int(item[0]))
                ],
            }

        with (
            patch.dict(os.environ, {"UI_DIST_DIR": str(self.dist_dir)}),
            patch("build_site.http_get_json", return_value=local_elo),
            patch("build_site.fetch_team_timeline", side_effect=fake_fetch_team_timeline),
        ):
            build_site(SiteConfig(analytics_api_base="http://local-fixture"))

        # New IA: dist/index.html is the season-agnostic intro (feature guide +
        # season scroller); each season's story-first landing lives under
        # dist/<season>/. Mock returns 2024 data, so assert against 2024.
        picker_html = (self.dist_dir / "index.html").read_text(encoding="utf-8")
        index_html = (self.dist_dir / "2024" / "index.html").read_text(encoding="utf-8")

        # Intro carries the season-agnostic feature guide + the scroller
        self.assertIn("Discover every angle of every season", picker_html)
        self.assertIn("feature-card", picker_html)
        self.assertIn("Choose a season to explore", picker_html)

        # Season landing is a story-first pulse page, not a leaderboard shell
        self.assertIn("home-hero", index_html)
        self.assertIn("The 2024 season", index_html)
        self.assertIn("Super Bowl champion", index_html)
        self.assertIn("Super Bowl runner-up", index_html)
        self.assertIn("Highest-Elo conference championship runner-up", index_html)
        self.assertIn("Philadelphia Eagles", index_html)
        self.assertIn("Kansas City Chiefs", index_html)
        self.assertIn("Buffalo Bills", index_html)
        self.assertIn("static/img/logos/philadelphia-eagles.png", index_html)
        self.assertIn("static/img/logos/kansas-city-chiefs.png", index_html)
        self.assertIn("static/img/logos/buffalo-bills.png", index_html)
        self.assertIn("Champion title odds", index_html)
        self.assertIn("100,000 Elo playoff simulations", index_html)
        # The feature guide belongs on the intro, not the season landing
        self.assertNotIn("feature-card", index_html)
        self.assertNotIn("League leaderboard", index_html)
        self.assertNotIn("Matchup predictor", index_html)


if __name__ == "__main__":
    unittest.main()
