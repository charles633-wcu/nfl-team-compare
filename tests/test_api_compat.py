"""Compatibility tests for API wiring across local and gateway-based setups."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BUILD_DIR = Path(__file__).resolve().parents[1] / "ui" / "build"
ANALYTICS_DIR = Path(__file__).resolve().parents[1] / "analytics-api"

for path in (BUILD_DIR, ANALYTICS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_site  # noqa: E402


class APICompatibilityTests(unittest.TestCase):
    """Verifies the project tolerates both direct and gateway-style local API wiring."""

    def test_build_site_prefers_main_repo_dist_when_running_from_worktree(self) -> None:
        """A worktree build should emit generated HTML into the main repo dist by default."""
        fake_script = Path(
            r"C:\Users\czw53\PycharmProjects\nfl-team-compare\.worktrees\ui-redesign-broadcast\ui\build\build_site.py"
        )
        resolved = build_site.resolve_dist_dir(fake_script)
        expected = Path(r"C:\Users\czw53\PycharmProjects\nfl-team-compare\ui\dist")
        self.assertEqual(resolved, expected)

    def test_ui_build_prefers_reachable_gateway_candidate(self) -> None:
        """The site builder should choose the first reachable analytics base."""

        def fake_http_get_json(url: str, timeout_s: int) -> dict:
            if url == "http://localhost:9080/analytics/health":
                return {"status": "ok"}
            raise RuntimeError(f"unreachable: {url}")

        with patch("build_site.http_get_json", side_effect=fake_http_get_json):
            resolved = build_site.resolve_analytics_api_base(
                configured_base="http://127.0.0.1:8001",
                timeout_s=2,
            )

        self.assertEqual(resolved, "http://localhost:9080/analytics")

    def test_analytics_api_accepts_legacy_api_base_env_name(self) -> None:
        """The analytics service should honor API_BASE when ELO_API_BASE is unset."""
        old_api_base = os.environ.pop("ELO_API_BASE", None)
        old_legacy = os.environ.get("API_BASE")
        os.environ["API_BASE"] = "http://localhost:9080/api"

        try:
            if "analytics_api" in sys.modules:
                del sys.modules["analytics_api"]
            analytics_api = importlib.import_module("analytics_api")
            self.assertEqual(analytics_api.API_BASE, "http://localhost:9080/api")
        finally:
            if "analytics_api" in sys.modules:
                del sys.modules["analytics_api"]
            if old_api_base is not None:
                os.environ["ELO_API_BASE"] = old_api_base
            else:
                os.environ.pop("ELO_API_BASE", None)
            if old_legacy is not None:
                os.environ["API_BASE"] = old_legacy
            else:
                os.environ.pop("API_BASE", None)


if __name__ == "__main__":
    unittest.main()
