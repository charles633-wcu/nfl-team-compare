import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# These helpers support both the direct analytics service and the APISIX gateway.
def fetch_json(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    req = Request(url, headers={"User-Agent": "ui-build/1.0"})
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        raise RuntimeError(f"HTTP error {e.code} for {url}") from e
    except URLError as e:
        raise RuntimeError(
            f"Could not reach Analytics API at {url}. "
            f"Check whether either the direct analytics service or the gateway endpoint is running."
        ) from e

def fetch_week_elo(base_url: str, week: int) -> dict:
    return fetch_json(base_url, f"/elo/{week}")

def fetch_all(base_url: str) -> dict:
    return fetch_json(base_url, "/elo/all")
