"""Tests for the season query parameter on the games (data) API."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for sub in ("loader", "data-api"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import loader  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "nfl-games.db"
    loader.build_master(
        db,
        ROOT / "loader" / "data" / "nfl-season-2025.csv",
        ROOT / "loader" / "data" / "nfl-season-2024.db",
    )
    monkeypatch.setenv("DB_PATH", str(db))
    sys.modules.pop("data_api", None)
    import data_api
    importlib.reload(data_api)
    return TestClient(data_api.app)


def test_games_2025_returns_272(client):
    r = client.get("/games", params={"season": 2025, "limit": 5000})
    assert r.status_code == 200
    assert r.json()["count"] == 272


def test_games_default_season_is_latest(client):
    default = client.get("/games", params={"limit": 5000}).json()["count"]
    explicit = client.get("/games", params={"season": 2025, "limit": 5000}).json()["count"]
    assert default == explicit == 272


def test_seasons_are_disjoint(client):
    g25 = client.get("/games", params={"season": 2025, "limit": 5000}).json()["games"]
    assert len(g25) == 272
    assert all(g["game_date"].startswith(("2025", "2026")) for g in g25)


def test_2024_still_served(client):
    r = client.get("/games", params={"season": 2024, "limit": 5000})
    assert r.status_code == 200
    assert r.json()["count"] == 272
