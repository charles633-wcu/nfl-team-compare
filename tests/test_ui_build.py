"""Smoke tests for the static UI build output."""

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


class UIBuildSmokeTests(unittest.TestCase):
    """Verifies the site generator still produces expected pages and UI markers."""

    def setUp(self) -> None:
        """Use an isolated dist directory so rebuild tests do not touch the live preview output."""
        self.repo_root = Path(__file__).resolve().parents[1]
        self.ui_dir = self.repo_root / "ui"
        self.dist_dir = self.ui_dir / ".test-dist-temp"
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        """Remove the temporary dist directory created for the test run."""
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)

    def test_build_outputs_broadcast_shell_and_core_pages(self) -> None:
        """Build output should include the shared shell and preserved page routes."""
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

        # Multi-season layout: dist/index.html is the season picker; each season's
        # site lives under dist/<season>/. The mock returns 2024 data for every
        # season, so we assert page content against the 2024 subtree.
        s = self.dist_dir / "2024"
        picker_html = (self.dist_dir / "index.html").read_text(encoding="utf-8")
        index_html = (s / "index.html").read_text(encoding="utf-8")
        week_html = (s / "leaderboard" / "week-18.html").read_text(encoding="utf-8")
        about_html = (s / "about.html").read_text(encoding="utf-8")
        contact_html = (s / "contact.html").read_text(encoding="utf-8")
        matchup_html = (s / "matchup.html").read_text(encoding="utf-8")
        teams_html = (s / "teams" / "index.html").read_text(encoding="utf-8")
        team_html = (s / "team" / "philadelphia-eagles.html").read_text(encoding="utf-8")
        chart_html = (s / "elo" / "philadelphia-eagles.html").read_text(encoding="utf-8")
        app_css = (s / "static" / "css" / "app.css").read_text(encoding="utf-8")

        # Root intro: season-agnostic feature guide + "choose a season" scroller
        self.assertIn("Discover every angle of every season", picker_html)
        self.assertIn("Choose a season to explore", picker_html)
        self.assertIn("feature-card", picker_html)
        self.assertIn("static/img/homepage/leaderboard.png", picker_html)
        self.assertIn("/2024/index.html", picker_html)
        self.assertIn("/2025/index.html", picker_html)

        # Season landing: season pulse, NOT the feature guide (that lives on the intro)
        self.assertIn("broadcast-shell", index_html)
        self.assertIn("home-hero", index_html)
        self.assertIn("The 2024 season", index_html)
        self.assertIn("Super Bowl champion", index_html)
        self.assertIn("Weekly Leaderboard", index_html)
        self.assertIn("Matchup Simulator", index_html)
        self.assertIn("2024 NFL SEASON", index_html)
        self.assertIn("season-switch", index_html)
        self.assertNotIn("feature-card", index_html)
        self.assertNotIn("img/homepage", index_html)
        self.assertIn("Week 18", week_html)
        self.assertNotIn("Browse every ranking window", week_html)
        self.assertIn("wk-picker-eyebrow-label", week_html)
        self.assertIn("Team directory", teams_html)
        self.assertIn("Profile", teams_html)
        self.assertIn("Chart", teams_html)
        self.assertIn("As a fan, this project came from the same questions fans ask all season", about_html)
        self.assertIn("Source Code", contact_html)
        self.assertIn("https://github.com/charles633-wcu", contact_html)
        self.assertIn("renderHistoryGames", matchup_html)
        self.assertIn("Hosted by", matchup_html)
        self.assertIn(".home-feature-strip__header", app_css)
        self.assertIn("align-items: flex-start;", app_css)
        self.assertNotIn(".home-feature-strip__header {\n  align-items: end;\n}", app_css)
        self.assertIn(".team-card-title", app_css)
        self.assertIn("overflow-wrap: anywhere;", app_css)
        self.assertNotIn("32 teams", teams_html)
        self.assertNotIn("Alphabetical", teams_html)
        self.assertNotIn("Browse every team in one place", teams_html)
        self.assertNotIn("Directory mode", teams_html)
        self.assertNotIn("Coverage", teams_html)
        self.assertIn("margin-top: 40px;", app_css)
        self.assertIn("Open trend chart", team_html)
        self.assertIn("eloChart", chart_html)


if __name__ == "__main__":
    unittest.main()
