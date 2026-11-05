"""Tests for the season updater: loader/feed.py rules and update_season.py orchestration.

Unit tests use small hand-built rows (no network). Orchestration tests inject a
fake pipeline or fake server commands. One end-to-end test runs the real
servers against a saved feed snapshot, with every output in a temp folder.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "loader", ROOT / "ui" / "build"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import loader  # noqa: E402
import feed  # noqa: E402
import update_season as us  # noqa: E402


def _feed_game(match, week, date_utc, hs=None, as_=None,
               home="Buffalo Bills", away="Miami Dolphins"):
    """One game in fixturedownload's JSON shape."""
    return {"MatchNumber": match, "RoundNumber": week, "DateUtc": date_utc,
            "Location": "Stadium", "HomeTeam": home, "AwayTeam": away, "Group": None,
            "HomeTeamScore": hs, "AwayTeamScore": as_, "Winner": ""}


class _Resp:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Loader: feed normalization -------------------------------------------

def test_feed_date_is_the_us_local_game_day():
    # A Thursday 8:15pm ET kickoff is 01:15 UTC on Friday.
    assert loader.to_date_only("2026-11-06 01:15:00Z") == "2026-11-05"
    assert loader.to_date_only("2026-11-01 18:00:00Z") == "2026-11-01"


def test_rows_from_feed_matches_the_hand_made_csv_date():
    rows = loader.rows_from_feed([_feed_game(1, 1, "2026-09-10 00:20:00Z", 13, 10,
                                             "Seattle Seahawks", "New England Patriots")], 2026)
    assert rows[0]["game_date"] == "2026-09-09"  # same as nfl-season-2026.csv row 1


def test_fetch_games_uses_a_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return _Resp(b"[]")

    monkeypatch.setattr(loader, "urlopen", fake_urlopen)
    assert loader.fetch_games("http://example.invalid", timeout=7) == []
    assert seen["timeout"] == 7


TEAMS = set(json.loads((ROOT / "elo" / "division_rivals.json").read_text(encoding="utf-8")))


def _row(match, week, hs=None, as_=None, home="Buffalo Bills", away="Miami Dolphins",
         date="2026-09-13"):
    """One normalized row, the shape rows_from_feed / rows_from_csv produce."""
    return {"season": 2026, "match_number": match, "week": week, "game_date": date,
            "home_team": home, "away_team": away, "home_score": hs, "away_score": as_}


# --- feed.validate_rows: malformed data is refused ------------------------

def test_valid_rows_have_no_refusals():
    assert feed.validate_rows([_row(1, 1, 20, 10), _row(2, 2)], TEAMS) == []


def test_empty_feed_is_refused():
    assert any("empty" in p for p in feed.validate_rows([], TEAMS))


def test_unknown_team_is_refused():
    problems = feed.validate_rows([_row(1, 1, home="Buffalo Bils")], TEAMS)
    assert any("Buffalo Bils" in p for p in problems)


@pytest.mark.parametrize("hs, as_", [(-3, 10), ("24", 10), (1.5, 10), (True, 0)])
def test_non_integer_or_negative_score_is_refused(hs, as_):
    assert feed.validate_rows([_row(1, 1, hs, as_)], TEAMS) != []


def test_one_sided_score_is_refused():
    problems = feed.validate_rows([_row(1, 1, 20, None)], TEAMS)
    assert any("one side" in p for p in problems)


def test_week_zero_is_refused():
    assert feed.validate_rows([_row(1, 0, 20, 10)], TEAMS) != []


def test_duplicate_match_number_is_refused():
    problems = feed.validate_rows([_row(1, 1, 20, 10), _row(1, 1, 20, 10)], TEAMS)
    assert any("Duplicate" in p for p in problems)


def test_postseason_rows_are_ignored_and_dropped():
    playoff = _row(273, 19, home="To be announced", away="To be announced")
    rows = [_row(1, 1, 20, 10), playoff]
    assert feed.validate_rows(rows, TEAMS) == []
    assert feed.regular_season(rows) == [rows[0]]


# --- feed.complete_through_week: only fully-scored weeks count ------------

def test_cut_keeps_complete_weeks_and_blanks_later_scores():
    rows = [_row(1, 1, 20, 10), _row(2, 1, 7, 3), _row(3, 2, 14, 13), _row(4, 2)]
    cut = feed.complete_through_week(rows)
    assert cut.week == 1
    assert [(r["home_score"], r["away_score"]) for r in cut.rows] == [
        (20, 10), (7, 3), (None, None), (None, None)]
    assert rows[2]["home_score"] == 14  # input is not mutated


def test_bye_week_does_not_block_completion():
    # Week 2 schedules only one game (everyone else on bye) and it is scored.
    rows = [_row(1, 1, 20, 10), _row(2, 1, 7, 3), _row(3, 2, 14, 13)]
    assert feed.complete_through_week(rows).week == 2


def test_postponed_game_blocks_its_week_and_is_named():
    late = _row(4, 2, home="New York Jets", away="New England Patriots", date="2026-09-20")
    rows = [_row(1, 1, 20, 10), _row(3, 2, 14, 13), late, _row(5, 3, 21, 17)]
    cut = feed.complete_through_week(rows)
    assert cut.week == 1
    assert cut.blocked == [late]
    assert cut.rows[3]["home_score"] is None  # week 3 waits behind week 2


def test_unstarted_next_week_is_not_reported_as_blocked():
    cut = feed.complete_through_week([_row(1, 1, 20, 10), _row(2, 2)])
    assert cut.week == 1 and cut.blocked == []


def test_nothing_played_is_week_zero():
    cut = feed.complete_through_week([_row(1, 1), _row(2, 2)])
    assert cut.week == 0 and cut.blocked == []


# --- feed.diff_snapshots: new scores vs. suspicious changes ---------------

def test_diff_reports_only_new_scores():
    old = [_row(1, 1, 20, 10), _row(2, 2)]
    new = [_row(1, 1, 20, 10), _row(2, 2, 14, 13)]
    d = feed.diff_snapshots(old, new)
    assert [r["match_number"] for r in d.new_scores] == [2] and d.problems == []


def test_identical_snapshots_are_up_to_date():
    rows = [_row(1, 1, 20, 10), _row(2, 2)]
    d = feed.diff_snapshots(rows, [dict(r) for r in rows])
    assert d.new_scores == [] and d.problems == []


def test_changed_final_score_is_suspicious():
    d = feed.diff_snapshots([_row(1, 1, 20, 10)], [_row(1, 1, 20, 13)])
    assert d.problems == ["Week 1 Miami Dolphins @ Buffalo Bills: 10-20 -> 13-20"]


def test_lost_score_is_suspicious():
    d = feed.diff_snapshots([_row(1, 1, 20, 10)], [_row(1, 1)])
    assert d.problems == ["Week 1 Miami Dolphins @ Buffalo Bills: 10-20 -> (no score)"]


def test_game_removed_from_schedule_is_suspicious():
    d = feed.diff_snapshots([_row(1, 1, 20, 10), _row(2, 2)], [_row(1, 1, 20, 10)])
    assert any(p.startswith("Removed from schedule") for p in d.problems)


def test_game_added_to_schedule_is_suspicious():
    d = feed.diff_snapshots([_row(1, 1, 20, 10)], [_row(1, 1, 20, 10), _row(2, 2)])
    assert any(p.startswith("New on schedule") for p in d.problems)


@pytest.mark.parametrize("changed", [
    {"home_team": "New York Jets"},
    {"week": 2},
])
def test_same_match_number_with_different_game_is_suspicious(changed):
    d = feed.diff_snapshots([_row(1, 1)], [{**_row(1, 1), **changed}])
    assert any(p.startswith("Match 1 changed") for p in d.problems)


def test_date_change_alone_is_not_suspicious():
    # Flexed kickoffs move dates; that is normal.
    d = feed.diff_snapshots([_row(1, 2)], [_row(1, 2, date="2026-09-21")])
    assert d.problems == []


def test_first_run_counts_every_score_as_new():
    d = feed.diff_snapshots([], [_row(1, 1, 20, 10), _row(2, 2)])
    assert [r["match_number"] for r in d.new_scores] == [1] and d.problems == []


# --- update_season: feed loading -------------------------------------------

def test_feed_timeout_suggests_from_file(monkeypatch):
    def boom(url, timeout=30):
        raise TimeoutError("timed out")
    monkeypatch.setattr(us.loader, "fetch_games", boom)
    with pytest.raises(us.UpdateError, match="--from-file"):
        us.load_feed(2026)


def test_network_error_suggests_from_file(monkeypatch):
    from urllib.error import URLError

    def boom(url, timeout=30):
        raise URLError("no route")
    monkeypatch.setattr(us.loader, "fetch_games", boom)
    with pytest.raises(us.UpdateError, match="--from-file"):
        us.load_feed(2026)


def test_feed_file_that_is_not_json_is_refused(tmp_path):
    bad = tmp_path / "feed.json"
    bad.write_text("<html>maintenance</html>", encoding="utf-8")
    with pytest.raises(us.UpdateError, match="not valid JSON"):
        us.load_feed(2026, bad)


def test_missing_feed_file_is_reported(tmp_path):
    with pytest.raises(us.UpdateError, match="Cannot read"):
        us.load_feed(2026, tmp_path / "nope.json")


@pytest.mark.parametrize("raw", [{"error": "x"}, [{"MatchNumber": 1}]])
def test_unexpected_feed_shape_is_refused(raw):
    with pytest.raises(us.UpdateError, match="Feed format changed"):
        us.normalize(raw, 2026)


# --- update_season.update: the flow, with a fake pipeline -----------------

def _paths(tmp_path):
    return us.Paths(csv=tmp_path / "nfl-season-2026.csv", master_db=tmp_path / "nfl-games.db",
                    elo_dir=tmp_path / "elo", elo_db=tmp_path / "nfl-elo.db",
                    dist_dir=tmp_path / "dist")


def _raw(week1_away=10, week2=(24, 3)):
    """Tiny valid feed: two week-1 games, one week-2 game."""
    return [
        _feed_game(1, 1, "2026-09-13 17:00:00Z", 20, week1_away),
        _feed_game(2, 1, "2026-09-13 17:00:00Z", 17, 14, "New York Jets", "New England Patriots"),
        _feed_game(3, 2, "2026-09-20 17:00:00Z", *week2),
    ]


def _fake_pipeline(calls, fail=False):
    """Stands in for run_pipeline: records the call and writes a tiny Elo artifact."""
    def run(season, paths):
        calls.append(season)
        if fail:
            raise us.PipelineError("Analytics API did not become healthy")
        paths.elo_dir.mkdir(parents=True, exist_ok=True)
        (paths.elo_dir / f"elo_{season}.json").write_text(json.dumps(
            {"weeks": 2, "elo": {"2": {"Buffalo Bills": 1550, "Miami Dolphins": 1450}}}))
    return run


def test_first_run_saves_csv_runs_pipeline_and_reports(tmp_path, capsys):
    paths, calls = _paths(tmp_path), []
    assert us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline(calls)) == us.EXIT_OK
    assert calls == [2026]
    saved = loader.rows_from_csv(paths.csv, 2026)
    assert [(r["match_number"], r["game_date"], r["home_score"]) for r in saved] == [
        (1, "2026-09-13", 20), (2, "2026-09-13", 17), (3, "2026-09-20", 24)]
    assert b"\r\n" not in paths.csv.read_bytes()  # LF, like the hand-made CSV
    out = capsys.readouterr().out
    assert "Through Week 2 (+3 games)" in out
    assert "Top 5: Buffalo Bills 1550, Miami Dolphins 1450" in out


def test_second_identical_run_is_up_to_date(tmp_path, capsys):
    paths, calls = _paths(tmp_path), []
    us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline(calls))
    assert us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline(calls)) == us.EXIT_OK
    assert calls == [2026]  # no rebuild the second time
    assert "Already up to date through Week 2" in capsys.readouterr().out


def test_dry_run_writes_nothing(tmp_path):
    paths, calls = _paths(tmp_path), []
    us.update(2026, _raw(week2=(None, None)), paths=paths, pipeline=_fake_pipeline(calls))
    before = paths.csv.stat().st_mtime_ns, paths.csv.read_bytes()
    assert us.update(2026, _raw(), paths=paths, dry_run=True,
                     pipeline=_fake_pipeline(calls)) == us.EXIT_OK
    assert (paths.csv.stat().st_mtime_ns, paths.csv.read_bytes()) == before
    assert calls == [2026]


def test_suspicious_change_stops_without_saving(tmp_path, capsys):
    paths, calls = _paths(tmp_path), []
    us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline(calls))
    before = paths.csv.read_bytes()
    code = us.update(2026, _raw(week1_away=13), paths=paths, pipeline=_fake_pipeline(calls))
    assert code == us.EXIT_REVIEW
    assert paths.csv.read_bytes() == before and calls == [2026]
    out = capsys.readouterr().out
    assert "10-20 -> 13-20" in out and "--accept-changes" in out


def test_accept_changes_applies_the_correction(tmp_path):
    paths, calls = _paths(tmp_path), []
    us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline(calls))
    assert us.update(2026, _raw(week1_away=13), paths=paths, accept_changes=True,
                     pipeline=_fake_pipeline(calls)) == us.EXIT_OK
    assert loader.rows_from_csv(paths.csv, 2026)[0]["away_score"] == 13


def test_malformed_feed_is_refused_even_with_accept_changes(tmp_path, capsys):
    paths, calls = _paths(tmp_path), []
    raw = _raw()
    raw[0]["HomeTeam"] = "Buffalo Bils"
    assert us.update(2026, raw, paths=paths, accept_changes=True,
                     pipeline=_fake_pipeline(calls)) == us.EXIT_ERROR
    assert not paths.csv.exists() and calls == []
    assert "Buffalo Bils" in capsys.readouterr().out


def test_blocked_week_is_explained(tmp_path, capsys):
    raw = _raw() + [_feed_game(4, 2, "2026-09-21 00:20:00Z", None, None,
                               "Kansas City Chiefs", "Denver Broncos")]
    us.update(2026, raw, paths=_paths(tmp_path), pipeline=_fake_pipeline([]))
    out = capsys.readouterr().out
    assert "Through Week 1" in out
    assert ("Week 2 blocked: 1 game without a score "
            "(Denver Broncos @ Kansas City Chiefs, 2026-09-20)") in out


def test_pipeline_failure_restores_previous_csv(tmp_path):
    paths = _paths(tmp_path)
    us.update(2026, _raw(week2=(None, None)), paths=paths, pipeline=_fake_pipeline([]))
    before = paths.csv.read_bytes()
    with pytest.raises(us.PipelineError):
        us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline([], fail=True))
    assert paths.csv.read_bytes() == before


def test_first_run_pipeline_failure_removes_the_new_csv(tmp_path):
    paths = _paths(tmp_path)
    with pytest.raises(us.PipelineError):
        us.update(2026, _raw(), paths=paths, pipeline=_fake_pipeline([], fail=True))
    assert not paths.csv.exists()


def test_cli_rejects_a_season_without_a_live_feed(capsys):
    assert us.main(["2025"]) == us.EXIT_ERROR
    assert "no live feed" in capsys.readouterr().err


def test_cli_reports_bad_feed_file(tmp_path, capsys):
    bad = tmp_path / "feed.json"
    bad.write_text("not json", encoding="utf-8")
    assert us.main(["2026", "--from-file", str(bad)]) == us.EXIT_ERROR
    assert "not valid JSON" in capsys.readouterr().err


# --- update_season: process handling and the dist swap --------------------

SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
WRITE_SITE = ("import os, pathlib; p = pathlib.Path(os.environ['UI_DIST_DIR']); "
              "p.mkdir(parents=True, exist_ok=True); (p / 'index.html').write_text('new')")


def test_servers_are_stopped_even_when_a_step_fails(tmp_path):
    with pytest.raises(RuntimeError):
        with us.Servers(tmp_path) as servers:
            proc = servers.spawn("sleeper", SLEEP, {})
            raise RuntimeError("compute_elo failed")
    assert proc.poll() is not None


def test_server_that_dies_fails_fast_with_its_log(tmp_path):
    crash = [sys.executable, "-c", "print('boom: address already in use'); raise SystemExit(1)"]
    with us.Servers(tmp_path) as servers:
        proc = servers.spawn("broken", crash, {})
        with pytest.raises(us.PipelineError, match="boom: address already in use"):
            us.wait_healthy("Broken API", f"http://127.0.0.1:{us.free_port()}/health",
                            proc, tmp_path / "broken.log", timeout_s=15)


def test_server_that_never_answers_times_out(tmp_path):
    with us.Servers(tmp_path) as servers:
        proc = servers.spawn("silent", SLEEP, {})
        with pytest.raises(us.PipelineError, match="did not become healthy"):
            us.wait_healthy("Silent API", f"http://127.0.0.1:{us.free_port()}/health",
                            proc, tmp_path / "silent.log", timeout_s=1)


def test_failed_step_raises_with_its_log(tmp_path):
    fail = [sys.executable, "-c", "print('No games returned'); raise SystemExit(1)"]
    with pytest.raises(us.PipelineError, match="No games returned"):
        us.run_step("compute-elo", fail, {}, tmp_path)


def test_failed_build_leaves_the_existing_site_untouched(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("old")
    with pytest.raises(us.PipelineError, match="build"):
        us.build_and_swap([sys.executable, "-c", "raise SystemExit(3)"], {}, dist, tmp_path)
    assert (dist / "index.html").read_text() == "old"
    assert not (tmp_path / "dist.staging").exists()


def test_successful_build_replaces_the_site(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("old")
    us.build_and_swap([sys.executable, "-c", WRITE_SITE], {}, dist, tmp_path)
    assert (dist / "index.html").read_text() == "new"
    assert not (tmp_path / "dist.staging").exists() and not (tmp_path / "dist.old").exists()


def test_free_port_is_an_open_local_port():
    import socket
    port = us.free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


# --- End to end: real servers, saved feed, everything in temp folders -----

FIXTURE_FEED = ROOT / "tests" / "fixtures" / "nfl-2026-feed.json"


def test_end_to_end_update_from_saved_feed(tmp_path, capsys):
    paths = _paths(tmp_path)
    paths.elo_dir.mkdir()
    for name in ("elo_2024.json", "elo_2025.json"):
        shutil.copy(ROOT / "elo" / name, paths.elo_dir / name)
    # No saved CSV (first run): the repo's live CSV advances every week, so it can't be the baseline.

    raw = us.load_feed(2026, FIXTURE_FEED)
    assert us.update(2026, raw, paths=paths) == us.EXIT_OK

    elo = json.loads((paths.elo_dir / "elo_2026.json").read_text(encoding="utf-8"))
    assert elo["weeks"] == 8
    home = (paths.dist_dir / "2026" / "index.html").read_text(encoding="utf-8")
    assert "Through Week 8" in home
    assert (paths.dist_dir / "2024" / "index.html").exists()
    assert (paths.dist_dir / "2025" / "index.html").exists()
    assert "Top 5:" in capsys.readouterr().out
