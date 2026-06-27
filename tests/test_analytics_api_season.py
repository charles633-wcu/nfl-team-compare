"""Tests for the season query parameter on the analytics (Elo) API."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_DIR = str(ROOT / "analytics-api")
if ANALYTICS_DIR not in sys.path:
    sys.path.insert(0, ANALYTICS_DIR)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ELO_DIR", str(ROOT / "elo"))
    sys.modules.pop("analytics_api", None)
    import analytics_api
    importlib.reload(analytics_api)
    return TestClient(analytics_api.app)


def test_elo_season_2025_served(client):
    r = client.get("/elo", params={"season": 2025})
    assert r.status_code == 200
    assert r.json()["season"] == 2025


def test_elo_default_is_latest(client):
    assert client.get("/elo").json()["season"] == 2025


def test_elo_season_2024_still_served(client):
    assert client.get("/elo", params={"season": 2024}).json()["season"] == 2024


def test_team_elo_is_season_scoped(client):
    r = client.get("/teams/Detroit Lions/elo", params={"season": 2024})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2024
    assert body["team"] == "Detroit Lions"


def test_unknown_season_returns_404(client):
    assert client.get("/elo", params={"season": 1999}).status_code == 404
