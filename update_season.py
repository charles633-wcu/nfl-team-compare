"""
update_season.py

One command to bring an in-progress season up to date:

    python update_season.py 2026 [--dry-run] [--accept-changes] [--from-file feed.json]

Flow: fetch the fixturedownload feed -> normalize -> validate (refuse malformed
data) -> cut to complete weeks -> diff against the saved CSV (stop on suspicious
changes) -> save CSV -> run the pipeline (loader, Data API, compute_elo,
Analytics API, site build) -> report.

The APIs run as real local servers on free ports and are always shut down. A
failed pipeline restores the previous CSV, and the site build is swapped into
ui/dist only after it succeeds. Nothing is deployed to S3.

Exit codes: 0 updated or already current, 1 needs review (--accept-changes),
2 refused or failed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent
for _sub in ("loader", "ui/build"):
    _p = str(REPO_ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import feed  # noqa: E402
import loader  # noqa: E402
from build_site import resolve_dist_dir  # noqa: E402

FEED_URL = "https://fixturedownload.com/feed/json/nfl-{season}"
FEED_TIMEOUT_S = 30
HEALTH_TIMEOUT_S = 20
# loader.build_master knows how to ingest these seasons from CSV.
LIVE_SEASONS = {2026}
CSV_COLUMNS = ["match_number", "week", "game_date", "home_team", "away_team",
               "home_score", "away_score"]
TEAMS_PATH = REPO_ROOT / "elo" / "division_rivals.json"

EXIT_OK, EXIT_REVIEW, EXIT_ERROR = 0, 1, 2


class UpdateError(Exception):
    """A stop with a message meant for the user (bad feed, network, etc.)."""


class PipelineError(UpdateError):
    """A pipeline step (server, Elo, build) failed."""


@dataclass
class Paths:
    """Every file a run writes; tests point these at a temp folder."""

    csv: Path
    master_db: Path
    elo_dir: Path
    elo_db: Path
    dist_dir: Path

    @classmethod
    def default(cls, season: int) -> "Paths":
        """The real locations; dist honours UI_DIST_DIR exactly like build_site.py."""
        return cls(
            csv=loader.DATA_DIR / f"nfl-season-{season}.csv",
            master_db=loader.MASTER_DB_PATH,
            elo_dir=REPO_ROOT / "elo",
            elo_db=REPO_ROOT / "database" / "nfl-elo.db",
            dist_dir=resolve_dist_dir(REPO_ROOT / "ui" / "build" / "build_site.py"),
        )


# --- Feed in -----------------------------------------------------------------

def load_feed(season: int, from_file: Optional[Path] = None) -> Any:
    """Raw feed JSON from a saved file or the network; UpdateError on any failure."""
    if from_file is not None:
        try:
            text = Path(from_file).read_text(encoding="utf-8")
        except OSError as e:
            raise UpdateError(f"Cannot read feed file {from_file}: {e}") from e
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise UpdateError(f"Feed file is not valid JSON: {e}") from e

    url = FEED_URL.format(season=season)
    try:
        return loader.fetch_games(url, timeout=FEED_TIMEOUT_S)
    except json.JSONDecodeError as e:
        raise UpdateError(f"Feed at {url} is not valid JSON: {e}") from e
    except OSError as e:  # URLError, HTTPError and timeouts are all OSError
        raise UpdateError(f"Feed unreachable ({e}) -- retry later or use --from-file") from e


def normalize(raw: Any, season: int) -> List[feed.Row]:
    """Feed JSON -> row dicts; a structural change in the feed becomes an UpdateError."""
    if not isinstance(raw, list):
        raise UpdateError("Feed format changed: expected a list of games")
    try:
        return loader.rows_from_feed(raw, season)
    except (KeyError, TypeError, ValueError) as e:
        raise UpdateError(f"Feed format changed: {e!r}") from e


def valid_teams() -> set:
    """The 32 team names the rest of the project knows."""
    return set(json.loads(TEAMS_PATH.read_text(encoding="utf-8")))


# --- CSV ---------------------------------------------------------------------

def read_csv(path: Path, season: int) -> List[feed.Row]:
    """The saved snapshot, or [] on the first run."""
    return loader.rows_from_csv(path, season) if path.exists() else []


def write_csv(path: Path, rows: List[feed.Row]) -> None:
    """Write the snapshot in the hand-made CSV's shape (LF endings, blank = unplayed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["match_number"]):
            w.writerow(r)  # None scores are written as empty cells


# --- Report ------------------------------------------------------------------

def describe(season: int, cut: feed.Cut, diff: feed.Diff) -> List[str]:
    """Summary lines: how far the season goes and what holds the next week back."""
    lines = [f"{season}: Through Week {cut.week} (+{len(diff.new_scores)} games)"]
    if cut.blocked:
        n = len(cut.blocked)
        games = ", ".join(f"{g['away_team']} @ {g['home_team']}, {g['game_date']}"
                          for g in cut.blocked[:3])
        more = f", +{n - 3} more" if n > 3 else ""
        lines.append(f"Week {cut.week + 1} blocked: {n} game{'s' if n != 1 else ''} "
                     f"without a score ({games}{more})")
    return lines


def top_five(elo_path: Path) -> str:
    """'Top 5: Team 1600, ...' from the latest week of an Elo artifact."""
    data = json.loads(elo_path.read_text(encoding="utf-8"))
    ratings = data["elo"][str(data["weeks"])]
    best = sorted(ratings.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return "Top 5: " + ", ".join(f"{team} {int(elo)}" for team, elo in best)


# --- The flow ----------------------------------------------------------------

def update(season: int, raw: Any, *, paths: Paths, accept_changes: bool = False,
           dry_run: bool = False, pipeline: Optional[Callable[[int, Paths], None]] = None) -> int:
    """Validate, cut, diff, save and rebuild; returns an exit code."""
    # Refusals: malformed data is never saved, whatever the flags.
    rows = normalize(raw, season)
    refusals = feed.validate_rows(rows, valid_teams())
    if refusals:
        print("Refusing feed -- malformed data (nothing saved):")
        for p in refusals:
            print(f"  - {p}")
        return EXIT_ERROR

    cut = feed.complete_through_week(feed.regular_season(rows))
    diff = feed.diff_snapshots(read_csv(paths.csv, season), cut.rows)
    for line in describe(season, cut, diff):
        print(line)

    # Suspicious changes need a human.
    if diff.problems and not accept_changes:
        print("Suspicious changes -- nothing saved:")
        for p in diff.problems:
            print(f"  - {p}")
        print("If these are real corrections, rerun with --accept-changes.")
        return EXIT_REVIEW
    if not diff.new_scores and not diff.problems:
        print(f"Already up to date through Week {cut.week}")
        return EXIT_OK
    if dry_run:
        print("Dry run -- nothing written.")
        return EXIT_OK

    # Save, then rebuild; any failure puts the previous CSV back so the next run retries.
    previous = paths.csv.read_bytes() if paths.csv.exists() else None
    write_csv(paths.csv, cut.rows)
    try:
        (pipeline or run_pipeline)(season, paths)
    except BaseException:
        if previous is None:
            paths.csv.unlink(missing_ok=True)
        else:
            paths.csv.write_bytes(previous)
        raise

    print(top_five(paths.elo_dir / f"elo_{season}.json"))
    return EXIT_OK


# --- Processes ---------------------------------------------------------------

def free_port() -> int:
    """An unused localhost port (the OS picks it), so we never collide with other servers."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def log_tail(log_path: Path, lines: int = 20) -> str:
    """Last lines of a step's log, for error messages."""
    try:
        return "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


class Servers:
    """
    Owns every background server a run starts and always stops them on exit,
    whether the run succeeded or failed. Each server logs to <log_dir>/<name>.log.
    """

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.procs: List[tuple] = []

    def __enter__(self) -> "Servers":
        return self

    def __exit__(self, *exc) -> bool:
        self.stop_all()
        return False  # never swallow the error

    def spawn(self, name: str, cmd: List[str], env: dict) -> subprocess.Popen:
        """Start a server from the repo root with extra env vars; output goes to its log."""
        log = open(self.log_dir / f"{name}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env={**os.environ, **env},
                                stdout=log, stderr=subprocess.STDOUT)
        self.procs.append((proc, log))
        return proc

    def stop_all(self) -> None:
        """terminate(), then kill() after a 5 s grace period."""
        for proc, log in self.procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            log.close()
        self.procs.clear()


def wait_healthy(name: str, url: str, proc: subprocess.Popen, log_path: Path,
                 timeout_s: float = HEALTH_TIMEOUT_S) -> None:
    """Poll a /health URL until it says status ok; fail fast if the process dies."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urlopen(url, timeout=2) as resp:
                if json.loads(resp.read()).get("status") == "ok":
                    return
        except (OSError, ValueError):
            pass  # not up yet
        time.sleep(0.25)
    raise PipelineError(f"{name} did not become healthy at {url}\n"
                        f"--- last lines of {log_path} ---\n{log_tail(log_path)}")


def run_step(name: str, cmd: List[str], env: dict, log_dir: Path) -> None:
    """Run one pipeline command to completion; PipelineError with its log on failure."""
    log_path = Path(log_dir) / f"{name}.log"
    with open(log_path, "w", encoding="utf-8") as log:
        code = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ, **env},
                              stdout=log, stderr=subprocess.STDOUT).returncode
    if code != 0:
        raise PipelineError(f"{name} failed (exit {code})\n"
                            f"--- last lines of {log_path} ---\n{log_tail(log_path)}")


def build_and_swap(cmd: List[str], env: dict, dist_dir: Path, log_dir: Path) -> None:
    """Build into <dist>.staging, then swap it in; a failed build leaves dist untouched."""
    dist_dir = Path(dist_dir)
    staging = dist_dir.with_name(dist_dir.name + ".staging")
    old = dist_dir.with_name(dist_dir.name + ".old")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        run_step("build", cmd, {**env, "UI_DIST_DIR": str(staging)}, log_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Swap: dist -> dist.old, staging -> dist, drop dist.old. Roll back if a rename fails.
    shutil.rmtree(old, ignore_errors=True)
    try:
        if dist_dir.exists():
            dist_dir.rename(old)
        staging.rename(dist_dir)
    except OSError as e:
        if old.exists() and not dist_dir.exists():
            old.rename(dist_dir)
        shutil.rmtree(staging, ignore_errors=True)
        raise PipelineError(f"Could not replace {dist_dir} ({e}). Is a preview server running "
                            "from inside it? Stop it (or use http.server --directory) and rerun.") from e
    shutil.rmtree(old, ignore_errors=True)


def run_pipeline(season: int, paths: Paths) -> None:
    """Placeholder until Task 7."""
    raise PipelineError("pipeline not implemented yet")


# --- CLI ---------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Parse flags, load the feed, run update(); user-facing errors go to stderr."""
    ap = argparse.ArgumentParser(description="Update an in-progress season from the live feed.")
    ap.add_argument("season", type=int)
    ap.add_argument("--accept-changes", action="store_true",
                    help="approve suspicious changes (corrected scores, schedule changes)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    ap.add_argument("--from-file", type=Path, help="read a saved feed JSON instead of the network")
    args = ap.parse_args(argv)

    if args.season not in LIVE_SEASONS:
        print(f"Season {args.season} has no live feed configured "
              f"(supported: {sorted(LIVE_SEASONS)})", file=sys.stderr)
        return EXIT_ERROR
    try:
        raw = load_feed(args.season, args.from_file)
        return update(args.season, raw, paths=Paths.default(args.season),
                      accept_changes=args.accept_changes, dry_run=args.dry_run)
    except UpdateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
